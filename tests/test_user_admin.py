import unittest
import os

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routes_auth import router
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.models.entities import User


class UserAdminRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        db = self.SessionLocal()
        db.add(
            User(
                tenant_id="tenant_local",
                email="admin@fleet.local",
                full_name="Administrador Local",
                password_hash=hash_password("admin123"),
                role="admin",
            )
        )
        db.add(
            User(
                tenant_id="tenant_local",
                email="viewer@fleet.local",
                full_name="Auditor de Flota",
                password_hash=hash_password("viewer123"),
                role="viewer",
            )
        )
        db.commit()
        db.close()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def as_user(self, role: str, email: str = "admin@fleet.local"):
        self.app.dependency_overrides[get_current_user] = lambda: {
            "email": email,
            "tenant_id": "tenant_local",
            "role": role,
        }

    def test_admin_lists_tenant_users(self):
        self.as_user("admin")

        response = self.client.get("/api/v1/auth/users")

        self.assertEqual(response.status_code, 200)
        emails = [item["email"] for item in response.json()]
        self.assertIn("admin@fleet.local", emails)
        self.assertIn("viewer@fleet.local", emails)

    def test_viewer_cannot_list_users(self):
        self.as_user("viewer", "viewer@fleet.local")

        response = self.client.get("/api/v1/auth/users")

        self.assertEqual(response.status_code, 403)

    def test_admin_creates_user_with_role(self):
        self.as_user("admin")

        response = self.client.post(
            "/api/v1/auth/users",
            json={
                "email": "newplanner@fleet.local",
                "full_name": "Nuevo Planner",
                "password": "planner456",
                "role": "planner",
                "is_active": True,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], "newplanner@fleet.local")
        self.assertEqual(response.json()["role"], "planner")

    def test_admin_updates_user_status(self):
        self.as_user("admin")

        response = self.client.put(
            "/api/v1/auth/users/2",
            json={"full_name": "Auditor Inactivo", "is_active": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "Auditor Inactivo")
        self.assertFalse(response.json()["is_active"])


if __name__ == "__main__":
    unittest.main()
