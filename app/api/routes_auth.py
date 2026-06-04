from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.entities import User
from app.schemas.auth import LoginInput, TokenOutput, RegisterInput, MeOut, TestUserOut
from app.core.security import verify_password, create_access_token, hash_password
from app.core.config import settings
from app.services.seed import TEST_USERS


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOutput)
def register(payload: RegisterInput, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
        )

    user = User(
        tenant_id=settings.DEFAULT_TENANT_ID,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.email, user.tenant_id, user.role)
    return TokenOutput(access_token=token)


@router.post("/login", response_model=TokenOutput)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    token = create_access_token(user.email, user.tenant_id, user.role)
    return TokenOutput(access_token=token)


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), user=Depends(get_current_user)):
    db_user = db.query(User).filter(User.email == user["email"]).first()
    return MeOut(
        email=user["email"],
        full_name=db_user.full_name if db_user else user["email"],
        role=user["role"],
        tenant_id=user["tenant_id"],
    )


@router.get("/test-users", response_model=list[TestUserOut])
def test_users():
    if settings.APP_ENV not in {"local", "development", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return [TestUserOut(**item) for item in TEST_USERS]
