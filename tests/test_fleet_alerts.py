import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.entities import Document, InventoryItem, MaintenanceOrder, Tire, TireEvent, Vehicle, VehicleTirePosition
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

    def test_get_fleet_alerts_includes_missing_positions_and_low_pressure(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        tenant = "tenant_test"
        vehicle = Vehicle(
            tenant_id=tenant,
            plate="CAUCA-808",
            brand="Kenworth",
            model="T800",
            year=2020,
            mileage=1000,
        )
        db.add(vehicle)
        db.flush()
        tire = Tire(
            tenant_id=tenant,
            serial_number="8229",
            position="P3",
            remaining_tread_mm=8,
            brand="Supercargo",
            vehicle_id=vehicle.id,
        )
        db.add(tire)
        db.flush()
        db.add_all(
            [
                VehicleTirePosition(
                    tenant_id=tenant,
                    vehicle_id=vehicle.id,
                    position_code="P1",
                    target_pressure_psi=95,
                    min_tread_mm=3.5,
                ),
                VehicleTirePosition(
                    tenant_id=tenant,
                    vehicle_id=vehicle.id,
                    position_code="P3",
                    tire_id=tire.id,
                    target_pressure_psi=95,
                    min_tread_mm=3.5,
                ),
                TireEvent(
                    tenant_id=tenant,
                    tire_id=tire.id,
                    vehicle_id=vehicle.id,
                    event_type="inspection",
                    position="P3",
                    pressure_psi=80,
                    min_tread_mm=8,
                ),
            ]
        )
        db.commit()

        alerts = get_fleet_alerts(db, tenant)
        kinds = {alert["kind"] for alert in alerts}

        self.assertIn("vehicle_position_missing", kinds)
        self.assertIn("tire_pressure_low", kinds)

        db.close()
        engine.dispose()

    def test_get_fleet_alerts_filters_operational_alerts_for_client_role(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        tenant = "tenant_test"
        vehicle = Vehicle(
            tenant_id=tenant,
            plate="CLI-101",
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
                    serial_number="CLIENT-HIDDEN",
                    position="FR",
                    remaining_tread_mm=2.4,
                    brand="KUMHO",
                    vehicle_id=vehicle.id,
                ),
                InventoryItem(
                    tenant_id=tenant,
                    sku="ACEITE",
                    name="Aceite",
                    stock=1,
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
                    title="Servicio publicado",
                    status="open",
                    priority="high",
                ),
            ]
        )
        db.commit()

        admin_kinds = {alert["kind"] for alert in get_fleet_alerts(db, tenant, role="admin")}
        client_kinds = {alert["kind"] for alert in get_fleet_alerts(db, tenant, role="client")}

        self.assertIn("tire_tread", admin_kinds)
        self.assertIn("inventory_low", admin_kinds)
        self.assertEqual(client_kinds, {"document_expiring", "maintenance_high"})

        db.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
