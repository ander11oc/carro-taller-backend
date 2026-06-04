from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Fleet Management API"
    APP_ENV: str = "local"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    DATABASE_URL: str = "postgresql+psycopg2://fleet:fleet@db:5432/fleetdb"
    REDIS_URL: str = "redis://redis:6379/0"

    JWT_SECRET_KEY: str = "supersecret-local-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    DEFAULT_TENANT_ID: str = "tenant_local"

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,https://web-lyart-eight-62.vercel.app"


settings = Settings()
