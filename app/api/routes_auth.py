from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.entities import AuditLog, User
from app.schemas.auth import (
    LoginInput,
    TokenOutput,
    RegisterInput,
    MeOut,
    TestUserOut,
    UserAdminCreate,
    UserAdminUpdate,
    UserOut,
)
from app.core.security import verify_password, create_access_token, hash_password
from app.core.config import settings
from app.services.seed import TEST_USERS


router = APIRouter(prefix="/auth", tags=["auth"])


def _tenant_user_or_404(db: Session, item_id: int, tenant_id: str) -> User:
    user = db.query(User).filter(User.id == item_id, User.tenant_id == tenant_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _write_auth_audit_log(
    db: Session,
    actor,
    action: str,
    entity_id: int | None,
    details: str,
):
    db.add(
        AuditLog(
            tenant_id=actor["tenant_id"],
            actor_email=actor["email"],
            role=actor.get("role", "viewer"),
            module="users",
            action=action,
            entity_id=entity_id,
            details=details,
        )
    )
    db.commit()


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


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    return (
        db.query(User)
        .filter(User.tenant_id == user["tenant_id"])
        .order_by(User.id.asc())
        .all()
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserAdminCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
        )

    item = User(
        tenant_id=user["tenant_id"],
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_auth_audit_log(db, user, "create", item.id, item.email)
    return item


@router.put("/users/{item_id}", response_model=UserOut)
def update_user(
    item_id: int,
    payload: UserAdminUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    item = _tenant_user_or_404(db, item_id, user["tenant_id"])
    values = payload.model_dump(exclude_unset=True)
    password = values.pop("password", None)
    if password:
        item.password_hash = hash_password(password)
    for field, value in values.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    _write_auth_audit_log(db, user, "update", item.id, item.email)
    return item


@router.get("/test-users", response_model=list[TestUserOut])
def test_users():
    if settings.APP_ENV not in {"local", "development", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return [TestUserOut(**item) for item in TEST_USERS]
