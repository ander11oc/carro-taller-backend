from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from app.core.config import settings
from app.core.security import JWT_SIGNING_KEY


bearer_scheme = HTTPBearer(auto_error=False)


def decode_access_token_payload(token: str) -> dict:
    return jwt.decode(
        token,
        JWT_SIGNING_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_aud": False, "verify_sub": False},
    )


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token"
        )
    token = credentials.credentials
    try:
        payload = decode_access_token_payload(token)
        return {
            "email": payload.get("sub"),
            "tenant_id": payload.get("tenant_id"),
            "role": payload.get("role", "viewer"),
        }
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


def require_role(*roles: str):
    def checker(user=Depends(get_current_user)):
        if roles and user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role"
            )
        return user

    return checker
