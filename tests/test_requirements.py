import os
import unittest

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes_fleet import create_requirement, list_requirements, update_requirement
from app.db.base import Base
from app.schemas.fleet import RequirementCreate, RequirementUpdate


ADMIN = {
    "tenant_id": "tenant_test",
    "email": "admin@test.local",
    "role": "admin",
}

VIEWER = {
    "tenant_id": "tenant_test",
    "email": "viewer@test.local",
    "role": "viewer",
}


class RequirementWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_requirement_status_moves_from_pending_to_completed_to_approved(self):
        created = create_requirement(
            RequirementCreate(
                title="Agregar filtro de fecha",
                description="El usuario necesita filtrar reportes por fecha.",
                requester="Cliente",
                images=["data:image/png;base64,abc123"],
            ),
            self.db,
            ADMIN,
        )

        self.assertEqual(created.status, "pending")
        self.assertFalse(created.team_done)
        self.assertFalse(created.client_ok)
        self.assertEqual(created.images, ["data:image/png;base64,abc123"])

        completed = update_requirement(
            created.id,
            RequirementUpdate(team_done=True),
            self.db,
            ADMIN,
        )

        self.assertEqual(completed.status, "completed")
        self.assertTrue(completed.team_done)
        self.assertFalse(completed.client_ok)

        approved = update_requirement(
            created.id,
            RequirementUpdate(client_ok=True),
            self.db,
            ADMIN,
        )

        self.assertEqual(approved.status, "approved")
        self.assertTrue(approved.team_done)
        self.assertTrue(approved.client_ok)

        all_rows = list_requirements(None, self.db, ADMIN)
        approved_rows = list_requirements("approved", self.db, ADMIN)
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(len(approved_rows), 1)

    def test_viewer_cannot_create_requirement(self):
        with self.assertRaises(HTTPException) as ctx:
            create_requirement(
                RequirementCreate(title="Solo lectura", description="", requester="Auditor"),
                self.db,
                VIEWER,
            )

        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
