"""
Authentication — JWT + OAuth2 (Google / GitHub)
Stateless sessions via signed tokens
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
import httpx
import os

from database import get_db, User

router   = APIRouter()
bearer   = HTTPBearer()
pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY   = os.getenv("JWT_SECRET_KEY", "change-me-in-production-fabian")
ALGORITHM    = "HS256"
ACCESS_TTL   = timedelta(hours=8)
REFRESH_TTL  = timedelta(days=30)

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email:    EmailStr
    username: str
    password: str

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user: dict

class OAuthCallbackRequest(BaseModel):
    code:     str
    provider: str  # "google" | "github"


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_token(data: dict, expires: timedelta) -> str:
    payload = {**data, "exp": datetime.utcnow() + expires}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


# ── Dependency: current user ─────────────────────────────────────────────────

async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(creds.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def _user_dict(user: User) -> dict:
    return {
        "id":       str(user.id),
        "email":    user.email,
        "username": user.username,
        "provider": user.oauth_provider,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email           = body.email,
        username        = body.username,
        hashed_password = hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    uid = str(user.id)
    return TokenResponse(
        access_token  = create_token({"sub": uid}, ACCESS_TTL),
        refresh_token = create_token({"sub": uid, "type": "refresh"}, REFRESH_TTL),
        user          = _user_dict(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user   = result.scalar_one_or_none()

    if not user or not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login = datetime.utcnow()
    await db.commit()

    uid = str(user.id)
    return TokenResponse(
        access_token  = create_token({"sub": uid}, ACCESS_TTL),
        refresh_token = create_token({"sub": uid, "type": "refresh"}, REFRESH_TTL),
        user          = _user_dict(user),
    )


@router.post("/oauth/callback", response_model=TokenResponse)
async def oauth_callback(body: OAuthCallbackRequest, db: AsyncSession = Depends(get_db)):
    """Exchange OAuth code for user profile, then issue JWT."""

    if body.provider == "google":
        profile = await _google_profile(body.code)
    elif body.provider == "github":
        profile = await _github_profile(body.code)
    else:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    oauth_id = str(profile["id"])
    result   = await db.execute(
        select(User).where(User.oauth_provider == body.provider, User.oauth_id == oauth_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        # First OAuth login — create account
        user = User(
            email          = profile.get("email", f"{oauth_id}@{body.provider}.oauth"),
            username       = profile.get("login") or profile.get("name", oauth_id)[:50],
            oauth_provider = body.provider,
            oauth_id       = oauth_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    user.last_login = datetime.utcnow()
    await db.commit()

    uid = str(user.id)
    return TokenResponse(
        access_token  = create_token({"sub": uid}, ACCESS_TTL),
        refresh_token = create_token({"sub": uid, "type": "refresh"}, REFRESH_TTL),
        user          = _user_dict(user),
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return _user_dict(user)


# ── OAuth profile fetchers ────────────────────────────────────────────────────

async def _google_profile(code: str) -> dict:
    #  Usamos las variables de entorno para que sea flexible
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    # Si no existe la variable, usamos el 5174 como respaldo
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5174/auth/callback")
    #Ruta de repaldo en caso de que VITE nos redireccione a traves de 5173  o en caso de que el puerto 5174 este ocupado por otras apps
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5173/auth/callback")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  redirect_uri, # <--- ¡AHORA COINCIDE CON TU NAVEGADOR!
            "grant_type":    "authorization_code",
        })
        
        # Esto te dirá exactamente qué dice Google si vuelve a fallar
        if token_resp.status_code != 200:
            log.error(f"Google Token Error: {token_resp.text}")
            
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        profile = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile.raise_for_status()
        return profile.json()

async def _github_profile(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "code":          code,
                "client_id":     GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        profile = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile.raise_for_status()
        data = profile.json()

        if not data.get("email"):
            emails = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            primary = next((e["email"] for e in emails.json() if e["primary"]), None)
            data["email"] = primary

        return data


# ── DEMO MODE BYPASS ──────────────────────────────────────────────────────────
# Set DEMO_MODE=true in .env to skip all authentication for hackathon demos.
# Google OAuth stays in codebase but is unreachable unless DEMO_MODE=false.

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

DEMO_USER = {
    "id": 1,
    "email": "demo@trafficos.ai",
    "username": "MISSION_CTRL",
    "role": "admin",
}
DEMO_TOKEN = "demo-bypass-token-trafficos"

@router.get("/demo-token")
async def get_demo_token():
    """Returns a demo token when DEMO_MODE=true. Used by frontend on load."""
    if not DEMO_MODE:
        raise HTTPException(status_code=403, detail="Demo mode is not enabled")
    return {"access_token": DEMO_TOKEN, "user": DEMO_USER, "token_type": "bearer"}

async def get_current_user_demo_aware(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db)
):
    """Drop-in replacement for get_current_user that respects DEMO_MODE."""
    if DEMO_MODE and credentials.credentials == DEMO_TOKEN:
        return type("User", (), DEMO_USER)()
    # Fall through to real JWT validation
    return await get_current_user(credentials, db)
