import os
import hashlib
import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from models import UserInDB, UserSession, RecommendationRecord

# Secret & Token Settings
SECRET_KEY = os.getenv("SECRET_KEY", "pocketsmart_super_secure_jwt_secret_key_2025_prod")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Password context with bcrypt and fallback
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:
    pwd_context = None

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

# In-memory database with persistent disk backing for testing
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

users_db: Dict[str, UserInDB] = {}
active_sessions: Dict[str, UserSession] = {}
blacklisted_tokens: set = set()
user_recommendations: Dict[str, List[RecommendationRecord]] = {}

def _load_data():
    global users_db, user_recommendations
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                raw_users = json.load(f)
                for uname, udata in raw_users.items():
                    users_db[uname] = UserInDB(**udata)
        except Exception as e:
            print("Error loading users:", e)
            
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                raw_hist = json.load(f)
                for uname, items in raw_hist.items():
                    user_recommendations[uname] = [
                        RecommendationRecord(
                            id=item["id"],
                            username=item["username"],
                            timestamp=datetime.fromisoformat(item["timestamp"]),
                            recommendation_type=item["recommendation_type"],
                            input_summary=item["input_summary"],
                            result_summary=item["result_summary"],
                            full_result=item["full_result"]
                        )
                        for item in items
                    ]
        except Exception as e:
            print("Error loading history:", e)

def _save_users():
    try:
        data = {uname: u.model_dump() for uname, u in users_db.items()}
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Error saving users:", e)

def _save_history():
    try:
        data = {
            uname: [
                {
                    "id": item.id,
                    "username": item.username,
                    "timestamp": item.timestamp.isoformat(),
                    "recommendation_type": item.recommendation_type,
                    "input_summary": item.input_summary,
                    "result_summary": item.result_summary,
                    "full_result": item.full_result
                }
                for item in items
            ]
            for uname, items in user_recommendations.items()
        }
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Error saving history:", e)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if pwd_context:
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception:
            pass
    # Fallback SHA256 comparison
    return hashlib.sha256(plain_password.encode('utf-8')).hexdigest() == hashed_password

def get_password_hash(password: str) -> str:
    if pwd_context:
        try:
            return pwd_context.hash(password)
        except Exception:
            pass
    # Fallback SHA256 hash
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def authenticate_user(db: Dict[str, UserInDB], username: str, password: str) -> Optional[UserInDB]:
    user = db.get(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_token(request: Request) -> Optional[str]:
    """Retrieve token from authorization header or HTTP-only cookie."""
    # First check cookie
    token = request.cookies.get("access_token")
    if token:
        return token
    # Second check Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    return None

async def get_current_user(request: Request, token: Optional[str] = Depends(oauth2_scheme)) -> Optional[UserInDB]:
    # Fallback to cookie if token is not passed via Bearer header
    if not token:
        token = await get_token(request)

    if not token or token in blacklisted_tokens:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    user = users_db.get(username)
    return user

async def get_current_active_user(request: Request, current_user: Optional[UserInDB] = Depends(get_current_user)) -> UserInDB:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if current_user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    
    # Update last activity in active session
    if current_user.username in active_sessions:
        active_sessions[current_user.username].last_activity = datetime.now(timezone.utc)
        
    return current_user

def save_to_history(username: str, recommendation_type: str, input_data: Dict[str, Any], result: Dict[str, Any]) -> str:
    """Save recommendation record into user history."""
    rec_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Summaries
    input_summary = {
        "budget": input_data.get("total_budget", 0),
        "details": input_data
    }
    
    result_summary = {
        "remaining_budget": result.get("remaining_budget", 0),
        "total_budget": result.get("total_budget", input_data.get("total_budget", 0)),
        "item_count": len(result.get("budget_breakdown", [])) or len(result.get("jewelry_recommendations", []))
    }
    
    record = RecommendationRecord(
        id=rec_id,
        username=username,
        timestamp=now,
        recommendation_type=recommendation_type,
        input_summary=input_summary,
        result_summary=result_summary,
        full_result=result
    )
    
    if username not in user_recommendations:
        user_recommendations[username] = []
    user_recommendations[username].insert(0, record)
    _save_history()
    return rec_id

def save_upload_file(upload_file) -> Optional[str]:
    """Save uploaded image file to static/uploads directory."""
    if not upload_file or not upload_file.filename:
        return None
    uploads_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{upload_file.filename}"
    file_path = os.path.join(uploads_dir, filename)
    with open(file_path, "wb") as buffer:
        buffer.write(upload_file.file.read())
    return file_path

# Load saved data on startup
_load_data()
