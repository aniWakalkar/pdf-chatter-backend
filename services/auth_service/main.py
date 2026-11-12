import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.auth_service.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from shared.app_factory import create_service_app
from shared.database import get_db
from shared.models import User
from shared.security import create_access_token, get_current_user_id, hash_password, verify_password

app = create_service_app("auth-service")

_DUMMY_HASH = hash_password("timing-equalizer-0")


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@app.post("/api/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, full_name=payload.full_name, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    db.refresh(user)
    return _token_response(user)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is None:
        verify_password(payload.password, _DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _token_response(user)


@app.get("/api/auth/me", response_model=UserOut)
def me(user_id: uuid.UUID = Depends(get_current_user_id), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
