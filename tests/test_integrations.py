import unittest
import os
from datetime import date

os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes_integrations import create_integration_webhook, parse_integration_file, retry_integration_run
from app.api.routes_media import create_media_upload_url
from app.db.base import Base
from app.models.entities import (
    FuelLog,
    IntegrationEvent,
    IntegrationRun,
    MediaAsset,
    NotificationMessage,
    PurchaseRequest,
    Tire,
    TireEvent,
    Vehicle,
    VehicleTirePosition,
)
from app.schemas.integrations import IntegrationWebhookRequest
from app.schemas.media import MediaUploadRequest


ADMIN = {"tenant_id": "tenant_test", "email": "admin@test.local", "role": "admin"}


class IntegrationsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="GPS-101",
            brand="Kenworth",
            model="T800",
            year=2022,
            mileage=1000,
        )
        self.db.add(self.vehicle)
        self.db.flush()
        self.tire = Tire(
            tenant_id="tenant_test",
            serial_number="LL-GPS-001",
            vehicle_id=self.vehicle.id,
            position="D1",
            brand="Michelin",
            remaining_tread_mm=2.8,
        )
        self.db.add(self.tire)
        self.db.add(
            VehicleTirePosition(
                tenant_id="tenant_test",
                vehicle_id=self.vehicle.id,
                position_code="D1",
                tire_id=self.tire.id,
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_gps_updates_mileage_but_does_not_lower_without_losing_traceability(self):
        create_integration_webhook(
            "gps_telematics",
            IntegrationWebhookRequest(
                records=[
                    {"plate": "GPS-101", "timestamp": "2026-06-09T10:00:00", "odometer": 1200, "speed": 92, "lat": 4.7, "lng": -74.1},
                    {"plate": "GPS-101", "timestamp": "2026-06-09T11:00:00", "odometer": 900, "speed": 40},
                ]
            ),
            self.db,
            ADMIN,
        )

        self.db.refresh(self.vehicle)
        events = self.db.query(IntegrationEvent).all()

        self.assertEqual(self.vehicle.mileage, 1200)
        self.assertEqual(len(events), 2)
        self.assertTrue(any("Kilometraje menor" in event.message for event in events))

    def test_fuel_integration_creates_fuel_log_once_per_plate_date_station(self):
        payload = IntegrationWebhookRequest(
            records=[
                {"plate": "GPS-101", "date": "2026-06-09", "liters": 42, "mileage": 1220, "cost": 210000, "station": "Norte"},
            ]
        )

        create_integration_webhook("fuel", payload, self.db, ADMIN)
        create_integration_webhook("fuel", payload, self.db, ADMIN)

        self.assertEqual(self.db.query(FuelLog).count(), 1)

    def test_maintenance_integration_links_axle_work_to_mounted_tires(self):
        create_integration_webhook(
            "maintenance_system",
            IntegrationWebhookRequest(
                records=[
                    {
                        "plate": "GPS-101",
                        "title": "Revision de ejes y suspension",
                        "description": "Desgaste irregular en eje delantero",
                        "status": "open",
                        "priority": "high",
                    }
                ]
            ),
            self.db,
            ADMIN,
        )

        event = self.db.query(TireEvent).filter(TireEvent.event_type == "maintenance_linked").one()
        self.assertEqual(event.tire_id, self.tire.id)
        self.assertIn("suspension", event.novelty.lower())

    def test_purchase_retread_media_and_notifications_are_recorded_without_duplicates(self):
        create_integration_webhook(
            "purchases",
            IntegrationWebhookRequest(records=[{"type": "tire", "origin": "critical_tire", "quantity": 2, "provider": "Proveedor A"}]),
            self.db,
            ADMIN,
        )
        create_integration_webhook(
            "retread_providers",
            IntegrationWebhookRequest(records=[{"serial": "LL-GPS-001", "status": "received", "cost": 350000, "band": "Banda X"}]),
            self.db,
            ADMIN,
        )
        create_integration_webhook(
            "notifications",
            IntegrationWebhookRequest(records=[{"channel": "whatsapp", "template": "llanta_critica", "entity_type": "tire", "entity_id": self.tire.id}]),
            self.db,
            ADMIN,
        )
        create_integration_webhook(
            "notifications",
            IntegrationWebhookRequest(records=[{"channel": "whatsapp", "template": "llanta_critica", "entity_type": "tire", "entity_id": self.tire.id}]),
            self.db,
            ADMIN,
        )
        media_run = create_integration_webhook(
            "media_storage",
            IntegrationWebhookRequest(records=[{"filename": "inspeccion.jpg", "content_type": "image/jpeg", "entity_type": "tire", "entity_id": self.tire.id, "url": "local://media/inspeccion.jpg"}]),
            self.db,
            ADMIN,
        )
        media = create_media_upload_url(
            MediaUploadRequest(filename="evidencia.jpg", content_type="image/jpeg", entity_type="tire", entity_id=self.tire.id),
            self.db,
            ADMIN,
        )

        self.assertEqual(self.db.query(PurchaseRequest).count(), 1)
        self.assertEqual(self.db.query(TireEvent).filter(TireEvent.event_type == "retread_received").count(), 1)
        self.assertEqual(self.db.query(NotificationMessage).count(), 1)
        self.assertEqual(media_run.status, "completed")
        self.assertEqual(self.db.query(MediaAsset).count(), 2)
        self.assertTrue(media.upload_url.startswith("local://media/"))

    def test_retry_reprocesses_failed_run_and_updates_status(self):
        run = IntegrationRun(
            tenant_id="tenant_test",
            system="gps_telematics",
            source="webhook",
            status="failed",
            total_records=1,
            payload={"records": [{"plate": "GPS-101", "odometer": 1300}]},
            errors=["manual failure"],
            created_by="admin@test.local",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        retried = retry_integration_run(run.id, self.db, ADMIN)

        self.assertEqual(retried.status, "completed")
        self.assertEqual(retried.processed_records, 1)
        self.db.refresh(self.vehicle)
        self.assertEqual(self.vehicle.mileage, 1300)

    def test_csv_upload_parser_creates_records_for_integration_processing(self):
        csv_bytes = b"plate,odometer,speed\nGPS-101,1400,55\n"

        records = parse_integration_file("gps.csv", csv_bytes, first_row_header=True)
        run = create_integration_webhook("gps_telematics", IntegrationWebhookRequest(records=records, source="upload"), self.db, ADMIN)

        self.db.refresh(self.vehicle)
        self.assertEqual(run.source, "upload")
        self.assertEqual(run.processed_records, 1)
        self.assertEqual(self.vehicle.mileage, 1400)


if __name__ == "__main__":
    unittest.main()
