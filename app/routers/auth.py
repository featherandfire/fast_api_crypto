from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.database import get_db
from app.email_service import generate_code, code_expiry, send_verification_code
from app.models import User
from app.schemas import UserCreate, UserOut, Token, VerifyRequest, ResendRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already registered")

    code = generate_code()
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_verified=False,
        verification_code=code,
        verification_expires=code_expiry(),
    )
    db.add(user)
    await db.commit()

    await send_verification_code(payload.email, code)
    return {"message": "Verification code sent", "email": payload.email}


# ── Verify ────────────────────────────────────────────────────────────────────

@router.post("/verify", response_model=Token)
async def verify(payload: VerifyRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or user.is_verified:
        raise HTTPException(status_code=400, detail="Invalid request")

    if not user.verification_code or user.verification_code != payload.code.strip():
        raise HTTPException(status_code=400, detail="Incorrect code")

    if not user.verification_expires or datetime.now(timezone.utc) > user.verification_expires:
        raise HTTPException(status_code=400, detail="Code has expired — request a new one")

    user.is_verified = True
    user.verification_code = None
    user.verification_expires = None
    await db.commit()

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token)


# ── Resend ────────────────────────────────────────────────────────────────────

@router.post("/resend", status_code=status.HTTP_200_OK)
async def resend(payload: ResendRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always return 200 to avoid email enumeration
    if not user or user.is_verified:
        return {"message": "If that account exists, a new code has been sent"}

    code = generate_code()
    user.verification_code = code
    user.verification_expires = code_expiry()
    await db.commit()

    await send_verification_code(payload.email, code)
    return {"message": "New code sent"}


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/token", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    if not user.is_verified:
        # Re-send a fresh code so they can complete verification
        code = generate_code()
        user.verification_code = code
        user.verification_expires = code_expiry()
        await db.commit()
        await send_verification_code(user.email, code)
        raise HTTPException(
            status_code=403,
            detail="Account not verified",
            headers={"X-Verify-Email": user.email},
        )

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token)


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
