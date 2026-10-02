from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

# User Authentication Models
class RegisterUser(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    password: str

class UserInDB(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    hashed_password: str
    disabled: bool = False

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserSession(BaseModel):
    username: str
    login_time: datetime
    last_activity: datetime
    token: str
    user_data: Dict[str, Any] = Field(default_factory=dict)

# Budget Input Models
class HomeBudgetInput(BaseModel):
    total_budget: float
    num_lights: int = 0
    num_fans: int = 0
    num_furniture: int = 0
    num_dining_tables: int = 0
    has_living_room: bool = False
    has_kitchen: bool = False
    has_bedroom: bool = False
    additional_requirements: Optional[str] = ""

class PartyBudgetInput(BaseModel):
    total_budget: float
    num_guests: int = 1
    party_type: str = "Birthday"
    venue_type: Optional[str] = "Home"
    needs_catering: bool = True
    needs_decoration: bool = False
    needs_entertainment: bool = False
    additional_requirements: Optional[str] = ""

class JewelryBudgetInput(BaseModel):
    total_budget: float
    occasion: str = "Casual"
    preferences: Optional[str] = ""
    image_filename: Optional[str] = None

# History & Detail Models
class RecommendationRecord(BaseModel):
    id: str
    username: str
    timestamp: datetime
    recommendation_type: str  # 'home', 'party', 'jewelry'
    input_summary: Dict[str, Any]
    result_summary: Dict[str, Any]
    full_result: Dict[str, Any]
