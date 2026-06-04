import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.entities import Document, InventoryItem, MaintenanceOrder, Tire, Vehicle
from app.services.fleet_alerts import get_fleet_alerts


class FleetAlertsTest(unittest.TestCase):
    def test_get_fleet_alerts_returns_stable_web_and_whatsapp_metadata(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        tenant = "tenant_test"
        vehicle = Vehicle(
            tenant_id=tenant,
            plate="ABC-101",
            brand="Toyota",
            model="Hilux",
            year=2020,
            mileage=1000,
        )
        db.add(vehicle)
        db.flush()
        db.add_all(
            [
                Tire(
                    tenant_id=tenant,
                    serial_number="TR-001",
                    position="FR",
                    remaining_tread_mm=2.4,
                    brand="KUMHO",
                    vehicle_id=vehicle.id,
                ),
                InventoryItem(
                    tenant_id=tenant,
                    sku="FIL-AIR",
                    name="Filtro aire",
                    stock=2,
                    min_stock=5,
                ),
                Document(
                    tenant_id=tenant,
                    vehicle_id=vehicle.id,
                    doc_type="SOAT",
                    file_url="local://soat.pdf",
                    expires_on=date.today() + timedelta(days=3),
                ),
                MaintenanceOrder(
                    tenant_id=tenant,
                    vehicle_id=vehicle.id,
                    title="Frenos",
                    status="open",
                    priority="high",
                ),
            ]
        )
        db.commit()

        alerts = get_fleet_alerts(db, tenant)
        high_alerts = [alert for alert in alerts if alert["severity"] == "high"]

        self.assertEqual(len(alerts), 4)
        self.assertTrue(all(alert["id"] for alert in alerts))
        self.assertTrue(all("web" in alert["channels"] for alert in alerts))
        self.assertTrue(all(alert["whatsapp_ready"] for alert in high_alerts))
        self.assertEqual(
            get_fleet_alerts(db, tenant)[0]["id"],
            alerts[0]["id"],
        )

        db.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
