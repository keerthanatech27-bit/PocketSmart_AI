import os
import json
import re
import base64
import shutil
import urllib.parse
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Union
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

from fastapi import (
    FastAPI, HTTPException, Depends, File, UploadFile,
    Form, Request, status, Cookie
)
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Load environment variables
load_dotenv()

from models import (
    RegisterUser, UserInDB, Token, UserSession,
    HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput, RecommendationRecord
)
from auth import (
    users_db, active_sessions, blacklisted_tokens, user_recommendations,
    get_password_hash, authenticate_user, create_access_token,
    get_token, get_current_user, get_current_active_user,
    save_to_history, save_upload_file, _save_users,
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
)
from gemini_utils import (
    get_home_recommendations,
    get_party_recommendations,
    get_jewelry_recommendations
)

# FastAPI app initialization
app = FastAPI(
    title="PocketSmart: AI Budget Planner",
    description="GenAI-powered, cross-platform recommendation system for home interior, party planning, and jewelry shopping.",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def usd_to_inr(amount_usd: float, exchange_rate: float = 83.0) -> float:
    """Convert USD amount to INR using the specified exchange rate"""
    return amount_usd * exchange_rate

# Background task for session cleanup
@app.on_event("startup")
async def setup_session_cleanup():
    """Background task to clean up expired sessions"""
    async def cleanup_expired_sessions():
        while True:
            current_time = datetime.now(timezone.utc)
            expired_sessions = [
                username for username, session in active_sessions.items()
                if (current_time - session.last_activity).total_seconds() > 1800  # 30 minutes
            ]
            for username in expired_sessions:
                if username in active_sessions:
                    print(f"Removing expired session for {username}")
                    del active_sessions[username]
            await asyncio.sleep(300)

    asyncio.create_task(cleanup_expired_sessions())

# ==========================================
# Authentication & Page Routing
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def home_landing_page(request: Request):
    """Landing Page"""
    user = None
    try:
        token = await get_token(request)
        if token:
            user = await get_current_user(request, token)
    except Exception:
        pass
    return templates.TemplateResponse(request=request, name="index.html", context={"user": user})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page"""
    try:
        token = await get_token(request)
        if token:
            user = await get_current_user(request, token)
            if user:
                return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except Exception:
        pass
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve the registration page"""
    try:
        token = await get_token(request)
        if token:
            user = await get_current_user(request, token)
            if user:
                return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except Exception:
        pass
    return templates.TemplateResponse(request=request, name="register.html", context={})

@app.post("/register")
async def register(
    request: Request,
    username: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    full_name: Optional[str] = Form(None)
):
    """Register a new user via JSON or Form Submission"""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
            username = data.get("username")
            email = data.get("email")
            password = data.get("password")
            full_name = data.get("full_name")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="Username, email and password are required")

    if username in users_db:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_pw = get_password_hash(password)
    new_user = UserInDB(
        username=username,
        email=email,
        full_name=full_name or username,
        hashed_password=hashed_pw
    )
    users_db[username] = new_user
    _save_users()

    # Automatically create session & token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": username},
        expires_delta=access_token_expires
    )
    active_sessions[username] = UserSession(
        username=username,
        login_time=datetime.now(timezone.utc),
        last_activity=datetime.now(timezone.utc),
        token=access_token,
        user_data={}
    )

    response = JSONResponse(content={"message": "User registered successfully", "access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get access token"""
    user = authenticate_user(users_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    existing_user_data = {}
    if user.username in active_sessions:
        existing_user_data = active_sessions[user.username].user_data
        old_token = active_sessions[user.username].token
        blacklisted_tokens.add(old_token)

    active_sessions[user.username] = UserSession(
        username=user.username,
        login_time=datetime.now(timezone.utc),
        last_activity=datetime.now(timezone.utc),
        token=access_token,
        user_data=existing_user_data
    )

    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response

@app.post("/login")
async def login(
    request: Request,
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None)
):
    """Universal login endpoint supporting JSON and Form submissions"""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
            username = data.get("username")
            password = data.get("password")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    user = authenticate_user(users_db, username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    existing_user_data = {}
    if user.username in active_sessions:
        existing_user_data = active_sessions[user.username].user_data
        old_token = active_sessions[user.username].token
        blacklisted_tokens.add(old_token)

    active_sessions[user.username] = UserSession(
        username=user.username,
        login_time=datetime.now(timezone.utc),
        last_activity=datetime.now(timezone.utc),
        token=access_token,
        user_data=existing_user_data
    )

    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response

@app.post("/logout")
async def logout(request: Request):
    """Logout user by blacklisting their token and clearing session"""
    token = await get_token(request)
    if token:
        blacklisted_tokens.add(token)
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username and username in active_sessions:
                del active_sessions[username]
        except JWTError:
            pass

    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response

# ==========================================
# User Dashboard & Planners View Routing
# ==========================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """User Dashboard page"""
    history = user_recommendations.get(current_user.username, [])
    recent_activity = history[:5]
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"user": current_user, "recent_activity": recent_activity}
    )

@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Home budget planner page"""
    return templates.TemplateResponse(request=request, name="home_planner.html", context={"user": current_user})

@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Party budget planner page"""
    return templates.TemplateResponse(request=request, name="party_planner.html", context={"user": current_user})

@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Jewelry budget planner page"""
    return templates.TemplateResponse(request=request, name="jewelry_planner.html", context={"user": current_user})

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """History page to view past recommendations"""
    return templates.TemplateResponse(request=request, name="history.html", context={"user": current_user})

# ==========================================
# Core AI Recommendation Endpoints
# ==========================================

@app.post("/home-budget")
@app.post("/generate-home")
async def plan_home_budget(
    budget_input: HomeBudgetInput,
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Generate home budget recommendations"""
    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data["last_home_budget"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "budget": budget_input.total_budget,
            "requirements": {
                "lights": budget_input.num_lights,
                "fans": budget_input.num_fans,
                "furniture": budget_input.num_furniture,
                "dining_tables": budget_input.num_dining_tables
            }
        }

    # Get recommendations
    try:
        result = get_home_recommendations(budget_input)
    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")

    # Save to history
    save_to_history(
        username=current_user.username,
        recommendation_type="home",
        input_data=budget_input.model_dump(),
        result=result
    )

    return result

@app.post("/party-budget")
@app.post("/generate-party")
async def plan_party_budget(
    budget_input: PartyBudgetInput,
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Generate party budget recommendations"""
    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data["last_party_budget"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "budget": budget_input.total_budget,
            "party_type": budget_input.party_type,
            "guests": budget_input.num_guests
        }

    # Get recommendations
    try:
        result = get_party_recommendations(budget_input)
    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")

    # Save to history
    save_to_history(
        username=current_user.username,
        recommendation_type="party",
        input_data=budget_input.model_dump(),
        result=result
    )

    return result

@app.post("/jewelry-budget")
@app.post("/generate-jewelry")
async def plan_jewelry_budget(
    total_budget: float = Form(...),
    occasion: str = Form(...),
    preferences: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    request: Request = None,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Generate jewelry budget recommendations with optional outfit image"""
    budget_input = JewelryBudgetInput(
        total_budget=total_budget,
        occasion=occasion,
        preferences=preferences or ""
    )

    image_path = None
    if image and image.filename:
        image_path = save_upload_file(image)
        budget_input.image_filename = os.path.basename(image_path)

    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data["last_jewelry_budget"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "budget": budget_input.total_budget,
            "occasion": budget_input.occasion,
            "has_image": image is not None and bool(image.filename)
        }

    # Get recommendations
    try:
        result = get_jewelry_recommendations(budget_input, image_path)
    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")

    # Save to history with image info
    input_data = budget_input.model_dump()
    if image and image.filename:
        input_data["image"] = image.filename

    save_to_history(
        username=current_user.username,
        recommendation_type="jewelry",
        input_data=input_data,
        result=result
    )

    return result

# ==========================================
# History & Session Management APIs
# ==========================================

@app.get("/recommendation-history")
async def get_recommendation_history(
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get the user's recommendation history"""
    if current_user.username not in user_recommendations:
        return {"history": []}

    history = sorted(
        user_recommendations[current_user.username],
        key=lambda x: x.timestamp,
        reverse=True
    )

    history_data = []
    for item in history:
        history_data.append({
            "id": item.id,
            "timestamp": item.timestamp.strftime("%b %d, %Y, %I:%M %p"),
            "type": item.recommendation_type,
            "input": item.input_summary,
            "summary": item.result_summary,
            "full_result": item.full_result
        })

    return {"history": history_data}

@app.get("/recommendation-details/{recommendation_id}")
async def get_recommendation_details(
    recommendation_id: str,
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get the full details of a specific recommendation"""
    if current_user.username not in user_recommendations:
        raise HTTPException(status_code=404, detail="No recommendations found")

    for item in user_recommendations[current_user.username]:
        if item.id == recommendation_id:
            return {
                "id": item.id,
                "timestamp": item.timestamp.strftime("%b %d, %Y, %I:%M %p"),
                "type": item.recommendation_type,
                "input": item.input_summary,
                "full_result": item.full_result
            }

    raise HTTPException(status_code=404, detail="Recommendation not found")

@app.get("/session-info")
async def get_session_info(
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get current user's session information"""
    if current_user.username in active_sessions:
        session = active_sessions[current_user.username]
        duration_minutes = (datetime.now(timezone.utc) - session.login_time).total_seconds() // 60
        return {
            "username": session.username,
            "login_time": session.login_time.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "session_duration": duration_minutes,
            "user_data": session.user_data
        }
    else:
        raise HTTPException(status_code=404, detail="No active session found")

@app.post("/session-data")
async def update_session_data(
    data: Dict[str, Any],
    request: Request,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update user's session data"""
    if current_user.username in active_sessions:
        active_sessions[current_user.username].user_data.update(data)
        active_sessions[current_user.username].last_activity = datetime.now(timezone.utc)
        return {"message": "Session data updated", "data": active_sessions[current_user.username].user_data}
    else:
        raise HTTPException(status_code=404, detail="No active session found")

# ==========================================
# Main Entry Point
# ==========================================
if __name__ == "__main__":
    import uvicorn
    print("Starting PocketSmart: AI Budget Planner...")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=True)
