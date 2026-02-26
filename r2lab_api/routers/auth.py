from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import create_token, hash_password, verify_password
from ..database import get_db
from ..models.user import User, UserStatus
from ..schemas import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if user.status != UserStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.status.value}",
        )
    token = create_token(user.email)
    return TokenResponse(access_token=token)


@router.post("/register", status_code=status.HTTP_201_CREATED,
             response_model=dict)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.exec(select(User).where(User.email == body.email)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        status=UserStatus.pending,
    )
    db.add(user)
    db.commit()
    return {"detail": "Registration submitted — awaiting admin approval"}
