from pydantic import BaseModel


class LoginInput(BaseModel):
    email: str
    password: str


class TokenOutput(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterInput(BaseModel):
    email: str
    full_name: str
    password: str
    role: str = "admin"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    tenant_id: str

    class Config:
        from_attributes = True


class MeOut(BaseModel):
    email: str
    full_name: str
    role: str
    tenant_id: str


class TestUserOut(BaseModel):
    email: str
    password: str
    full_name: str
    role: str
    tenant_id: str
