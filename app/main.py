from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.base import Base
from app.db.schema_sync import ensure_model_columns
from app.db.session import engine, SessionLocal
from app.api.routes_auth import router as auth_router
from app.api.routes_fleet import router as fleet_router
from app.api.routes_integrations import router as integrations_router
from app.api.routes_media import router as media_router
from app.services.seed import seed_admin, seed_demo_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_model_columns(engine)
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_demo_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

origins = [item.strip() for item in settings.CORS_ORIGINS.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost(:\d+)?|https://localhost(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.APP_NAME, "env": settings.APP_ENV}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(fleet_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(media_router, prefix="/api/v1")
