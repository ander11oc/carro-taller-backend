import os
import unittest

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routes_fleet import router
from app.db.base import Base
from app.db.session import get_db
from app.models.entities import Vehicle


class AuditLogRoutesTest(unittest.TestCase):
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
            Vehicle(
                tenant_id="tenant_local",
                plate="BASE-001",
                brand="Toyota",
                model="Hilux",
                year=2025,
                mileage=100,
                status="active",
                notes="base vehicle",
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

    def test_create_vehicle_writes_audit_log(self):
        self.as_user("admin")

        create_response = self.client.post(
            "/api/v1/fleet/vehicles",
            json={
                "plate": "AUD-001",
                "brand": "Toyota",
                "model": "Hilux",
                "year": 2025,
                "mileage": 100,
                "status": "active",
                "notes": "audit test",
            },
        )
        logs_response = self.client.get("/api/v1/fleet/audit-logs")

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(logs_response.status_code, 200)
        logs = logs_response.json()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["module"], "vehicles")
        self.assertEqual(logs[0]["action"], "create")
        self.assertEqual(logs[0]["actor_email"], "admin@fleet.local")

    def test_update_maintenance_writes_audit_log(self):
        self.as_user("planner", "planner@fleet.local")

        create_response = self.client.post(
            "/api/v1/fleet/maintenance",
            json={
                "vehicle_id": 1,
                "title": "Revision auditoria",
                "description": "test",
                "status": "open",
                "priority": "normal",
                "scheduled_for": "2026-06-04",
                "cost": 0,
            },
        )
        update_response = self.client.put(
            f"/api/v1/fleet/maintenance/{create_response.json()['id']}",
            json={"status": "in_progress"},
        )
        logs_response = self.client.get("/api/v1/fleet/audit-logs")

        self.assertEqual(update_response.status_code, 200)
        logs = logs_response.json()
        self.assertEqual(logs[0]["module"], "maintenance")
        self.assertEqual(logs[0]["action"], "update")
        self.assertEqual(logs[0]["actor_email"], "planner@fleet.local")

    def test_create_inventory_writes_audit_log(self):
        self.as_user("planner", "planner@fleet.local")

        create_response = self.client.post(
            "/api/v1/fleet/inventory",
            json={
                "sku": "INV-AUD",
                "name": "Filtro auditoria",
                "stock": 2,
                "min_stock": 1,
                "unit_cost": 10,
                "location": "A1",
            },
        )
        logs_response = self.client.get("/api/v1/fleet/audit-logs")

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(logs_response.json()[0]["module"], "inventory")
        self.assertEqual(logs_response.json()[0]["action"], "create")

    def test_viewer_can_read_audit_logs(self):
        self.as_user("viewer", "viewer@fleet.local")

        response = self.client.get("/api/v1/fleet/audit-logs")

        self.assertEqual(response.status_code, 200)

    def test_client_cannot_read_audit_logs(self):
        self.as_user("client", "client@fleet.local")

        response = self.client.get("/api/v1/fleet/audit-logs")

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
