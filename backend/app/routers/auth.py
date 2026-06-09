"""
Auth and Sync Router.
Provides endpoints for login, registration, logout, and profile sync.
"""

import hmac
import json
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.db import (
    create_session,
    create_user,
    delete_session,
    get_session_user,
    get_user_by_email,
    sync_user_data,
    verify_password,
)

router = APIRouter()

# --- Pydantic Models ---

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class WeddingProject(BaseModel):
    couple_name: str
    event_date: str = ""
    guest_count: str = "0"
    budget: str = ""
    notes: str = ""

class SyncRequest(BaseModel):
    wedding_project: WeddingProject
    venue_statuses: Dict[str, str]
    contacted_venues: Dict[str, str]
    activity_feed: List[dict]

class UserResponse(BaseModel):
    email: str
    name: str
    token: Optional[str] = None
    is_admin: bool = False
    wedding_project: Optional[dict] = None
    venue_statuses: Optional[dict] = None
    contacted_venues: Optional[dict] = None
    activity_feed: Optional[list] = None


def is_supervisor(email: str) -> bool:
    """True if the email matches the configured supervisor account."""
    supervisor = settings.supervisor_email.strip().lower()
    return bool(supervisor) and email.strip().lower() == supervisor

# --- Auth Helper ---

def authenticate_session(authorization: str = Header(None)) -> dict:
    """Dependency that validates the Bearer token and returns the current user profile."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Access token is missing or invalid format")
    token = authorization.split(" ")[1]
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid token")
    return user

def build_user_response(user: dict, token: str = None) -> UserResponse:
    """Utility to map user dict from DB to UserResponse model."""
    # Deserialize JSON fields
    project = {
        "couple_name": user.get("couple_name") or user["name"],
        "event_date": user.get("event_date") or "",
        "guest_count": user.get("guest_count") or "0",
        "budget": user.get("budget") or "",
        "notes": user.get("notes") or "",
    }
    
    statuses = {}
    if user.get("venue_statuses"):
        try:
            statuses = json.loads(user["venue_statuses"])
        except Exception:
            pass
            
    contacted = {}
    if user.get("contacted_venues"):
        try:
            contacted = json.loads(user["contacted_venues"])
        except Exception:
            pass
            
    feed = []
    if user.get("activity_feed"):
        try:
            feed = json.loads(user["activity_feed"])
        except Exception:
            pass

    return UserResponse(
        email=user["email"],
        name=user["name"],
        token=token,
        is_admin=is_supervisor(user["email"]),
        wedding_project=project,
        venue_statuses=statuses,
        contacted_venues=contacted,
        activity_feed=feed
    )

# --- Routes ---

@router.post("/auth/register", response_model=UserResponse)
async def register(req: RegisterRequest):
    """Registers a new user and generates a session token."""
    email = req.email.strip().lower()

    # The supervisor account is provisioned via login only — registering it
    # would let anyone claim the admin flag
    if is_supervisor(email):
        raise HTTPException(status_code=400, detail="Cet email est déjà enregistré")

    # Check if user already exists
    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=400, detail="Cet email est déjà enregistré")
        
    success = create_user(email, req.name, req.password)
    if not success:
        raise HTTPException(status_code=500, detail="Impossible de créer le compte")
        
    # Generate session
    token = create_session(email)
    user = get_user_by_email(email)
    return build_user_response(user, token)

@router.post("/auth/login", response_model=UserResponse)
async def login(req: LoginRequest):
    """Logs in an existing user and generates a session token.

    The supervisor account (SUPERVISOR_EMAIL/SUPERVISOR_PASSWORD in .env) can
    always log in: its password is checked against the configuration rather
    than the database, and the user row is auto-provisioned if missing.
    """
    email = req.email.strip().lower()

    if is_supervisor(email):
        if not hmac.compare_digest(req.password, settings.supervisor_password):
            raise HTTPException(status_code=400, detail="Identifiants incorrects")
        user = get_user_by_email(email)
        if not user:
            create_user(email, "Supervisor", req.password)
            user = get_user_by_email(email)
        token = create_session(email)
        return build_user_response(user, token)

    user = get_user_by_email(email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Identifiants incorrects")

    token = create_session(email)
    return build_user_response(user, token)

@router.post("/auth/logout")
async def logout(authorization: str = Header(None)):
    """Logs out the user by deleting their active session token."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        delete_session(token)
    return {"status": "logged_out"}

@router.get("/user/profile", response_model=UserResponse)
async def get_profile(user: dict = Depends(authenticate_session)):
    """Retrieves the user profile and current project state."""
    return build_user_response(user)

@router.post("/user/sync")
async def sync_data(req: SyncRequest, user: dict = Depends(authenticate_session)):
    """Syncs local browser state to the server."""
    email = user["email"]
    
    # Package details
    sync_payload = {
        "couple_name": req.wedding_project.couple_name,
        "event_date": req.wedding_project.event_date,
        "guest_count": req.wedding_project.guest_count,
        "budget": req.wedding_project.budget,
        "notes": req.wedding_project.notes,
        "venue_statuses": json.dumps(req.venue_statuses),
        "contacted_venues": json.dumps(req.contacted_venues),
        "activity_feed": json.dumps(req.activity_feed)
    }
    
    success = sync_user_data(email, sync_payload)
    if not success:
        raise HTTPException(status_code=500, detail="Erreur lors de la synchronisation des données")
        
    return {"status": "synced"}
