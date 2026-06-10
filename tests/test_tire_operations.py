from datetime import date
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes_fleet import (
    approve_tire_event,
    create_tire_inspection,
    create_tire_disposal_event,
    create_tire_retread_event,
    create_tire_warranty_event,
    get_tire_cost_summary,
    get_tire_decision_motor,
    get_tire_life_360,
    get_tire_operational_reports,
    import_tire_master_rows,
    preview_tire_master_import,
    get_tire_recommendations,
    get_vehicle_tire_map,
)
from app.db.base import Base
from app.models.entities import Tire, TireEvent, Vehicle, VehicleTirePosition
from app.schemas.fleet import TireCatalogEntryCreate, TireInspectionCreate, TireMasterImportRequest, TireMasterPreviewRequest, TireMovementCreate


ADMIN = {
    "tenant_id": "tenant_test",
    "email": "admin@test.local",
    "role": "admin",
}


class TireOperationsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        self.vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="CAUCA-808",
            brand="Kenworth",
            model="T800",
            year=2020,
            mileage=10530,
        )
        self.db.add(self.vehicle)
        self.db.commit()
        self.db.refresh(self.vehicle)

        self.tire = Tire(
            tenant_id="tenant_test",
            serial_number="8229",
            vehicle_id=self.vehicle.id,
            position="P3",
            brand="Supercargo",
            remaining_tread_mm=12,
        )
        self.db.add(self.tire)
        self.db.add_all(
            [
                VehicleTirePosition(
                    tenant_id="tenant_test",
                    vehicle_id=self.vehicle.id,
                    position_code="P1",
                    axle="Direccion",
                    tire_id=None,
                ),
                VehicleTirePosition(
                    tenant_id="tenant_test",
                    vehicle_id=self.vehicle.id,
                    position_code="P3",
                    axle="Traccion",
                    tire_id=self.tire.id,
                    target_pressure_psi=95,
                    min_tread_mm=3.5,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_inspection_records_event_and_updates_tire_tread(self):
        payload = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 9),
            mileage=10600,
            pressure_psi=92,
            tread_outer_mm=11,
            tread_center_mm=10.5,
            tread_inner_mm=10,
            damage="",
            novelty="Presion levemente baja",
            evidence_url="local://foto.jpg",
        )

        result = create_tire_inspection(payload, self.db, ADMIN)

        self.assertEqual(result.event_type, "inspection")
        self.assertEqual(result.min_tread_mm, 10)
        self.assertEqual(result.guidance, "Presion por debajo del objetivo. Calibrar y revisar en la proxima inspeccion.")
        self.assertEqual(self.db.query(TireEvent).count(), 1)
        self.assertEqual(self.db.query(Tire).one().remaining_tread_mm, 10)

    def test_inspection_rejects_tread_growth_without_explanation(self):
        first = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 9),
            mileage=10600,
            pressure_psi=95,
            tread_outer_mm=10,
            tread_center_mm=10,
            tread_inner_mm=10,
        )
        create_tire_inspection(first, self.db, ADMIN)

        second = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 20),
            mileage=10700,
            pressure_psi=95,
            tread_outer_mm=11,
            tread_center_mm=11,
            tread_inner_mm=11,
        )

        with self.assertRaises(HTTPException) as err:
            create_tire_inspection(second, self.db, ADMIN)

        self.assertEqual(err.exception.status_code, 400)
        self.assertIn("profundidad no puede subir", err.exception.detail)

    def test_vehicle_map_marks_missing_positions_and_recommendations_are_explainable(self):
        payload = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 9),
            mileage=10600,
            pressure_psi=80,
            tread_outer_mm=3,
            tread_center_mm=3,
            tread_inner_mm=3,
            damage="Corte en costado",
        )
        create_tire_inspection(payload, self.db, ADMIN)

        vehicle_map = get_vehicle_tire_map(self.vehicle.id, self.db, ADMIN)
        p1 = next(item for item in vehicle_map.positions if item.position_code == "P1")
        p3 = next(item for item in vehicle_map.positions if item.position_code == "P3")

        self.assertEqual(p1.status, "missing")
        self.assertEqual(p3.status, "critical")
        self.assertTrue(vehicle_map.has_missing_positions)

        recommendations = get_tire_recommendations(self.db, ADMIN, vehicle_id=self.vehicle.id)
        actions = {item.action for item in recommendations}
        self.assertIn("calibrar", actions)
        self.assertIn("retirar", actions)
        self.assertIn("completar_mapa", actions)

    def test_list_tires_is_paginated_and_reports_total_count(self):
        from app.api.routes_fleet import list_tires

        self.db.add(
            Tire(
                tenant_id="tenant_test",
                serial_number="TR-PAGE-002",
                position="P4",
                brand="Michelin",
                vehicle_id=self.vehicle.id,
                remaining_tread_mm=8,
            )
        )
        self.db.commit()

        response = Response()
        rows = list_tires(response=response, db=self.db, user=ADMIN, status_f=None, limit=1, offset=0)

        self.assertEqual(len(rows), 1)
        self.assertEqual(response.headers["X-Total-Count"], "2")

    def test_master_preview_detects_incomplete_rows_duplicates_and_missing_catalogs(self):
        preview = preview_tire_master_import(
            TireMasterPreviewRequest(
                rows=[
                    {"serial_number": "A1", "brand": "Supercargo", "design": "ESC 508", "dimension": "295/80R22.5", "original_tread_mm": 16, "remaining_tread_mm": 12, "plate": "LG001", "position": "D1"},
                    {"serial_number": "A1", "brand": "Super Cargo", "design": "ESC 508", "dimension": "295/80R22.5", "original_tread_mm": 16, "remaining_tread_mm": 10, "plate": "LG001", "position": "D2"},
                    {"serial_number": "", "brand": "Kumho", "design": "KRT 03", "dimension": "", "plate": "LG001"},
                ]
            ),
            self.db,
            ADMIN,
        )

        self.assertEqual(preview.valid_count, 2)
        self.assertEqual(preview.incomplete_count, 1)
        self.assertEqual(preview.duplicate_serials, ["A1"])
        self.assertIn("brand", preview.missing_catalogs)
        self.assertIn("SUPERCARGO", preview.missing_catalogs["brand"])

    def test_master_import_creates_tire_vehicle_position_and_initial_event_from_sheet_fields(self):
        result = import_tire_master_rows(
            TireMasterImportRequest(
                source_sheet="03_Llantas",
                import_batch_id="llantas-test-batch",
                source_row_start=502,
                rows=[
                    {
                        "Serial": "LL-000004",
                        "DOT": "5125",
                        "Marca": "Double Coin",
                        "Diseño": "Larga distancia",
                        "Medida": "285/70R19.5",
                        "Vida": 1,
                        "Prof. original mm": 16,
                        "Prof. actual mm": "4,5",
                        "Estado": "Montada",
                        "Placa actual": "LG001",
                        "Posición": "T2",
                        "Sede": "Bogotá",
                        "Fecha compra": "2025-05-12",
                        "Valor compra": "751.343",
                        "Km desde montaje": "134.9",
                    }
                ],
            ),
            self.db,
            ADMIN,
        )

        tire = self.db.query(Tire).filter(Tire.serial_number == "LL-000004").one()
        vehicle = self.db.query(Vehicle).filter(Vehicle.plate == "LG001").one()
        position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == vehicle.id,
            VehicleTirePosition.position_code == "T2",
        ).one()
        event = self.db.query(TireEvent).filter(TireEvent.tire_id == tire.id).one()

        self.assertEqual(result.created_tires, 1)
        self.assertEqual(result.created_vehicles, 1)
        self.assertEqual(tire.dot, "5125")
        self.assertEqual(tire.site, "Bogotá")
        self.assertEqual(tire.initial_cost, 751343)
        self.assertEqual(tire.purchase_date, date(2025, 5, 12))
        self.assertEqual(tire.remaining_tread_mm, 4.5)
        self.assertEqual(tire.original_tread_mm, 16)
        self.assertEqual(tire.vehicle_id, vehicle.id)
        self.assertEqual(position.tire_id, tire.id)
        self.assertEqual(event.event_type, "master_import")
        self.assertEqual(event.mileage, 134.9)
        self.assertIn("03_Llantas", event.novelty)
        self.assertIn("fila 502", event.novelty)
        self.assertEqual(result.import_batch_id, "llantas-test-batch")

    def test_master_import_retry_same_batch_does_not_duplicate_initial_event(self):
        payload = TireMasterImportRequest(
            source_sheet="03_Llantas",
            import_batch_id="retry-safe-batch",
            source_row_start=20,
            rows=[
                {
                    "Serial": "LL-RETRY-001",
                    "Marca": "Michelin",
                    "Diseño": "Direccional",
                    "Medida": "295/80R22.5",
                    "Prof. original mm": 20,
                    "Prof. actual mm": 12,
                    "Placa actual": "LG777",
                    "Posición": "D1",
                }
            ],
        )

        first = import_tire_master_rows(payload, self.db, ADMIN)
        second = import_tire_master_rows(payload, self.db, ADMIN)

        tire = self.db.query(Tire).filter(Tire.serial_number == "LL-RETRY-001").one()
        events = (
            self.db.query(TireEvent)
            .filter(TireEvent.tire_id == tire.id, TireEvent.event_type == "master_import")
            .all()
        )
        self.assertEqual(first.created_tires, 1)
        self.assertEqual(second.created_tires, 0)
        self.assertEqual(second.updated_tires, 0)
        self.assertEqual(second.skipped_rows, 1)
        self.assertEqual(len(events), 1)

    def test_master_import_matches_serials_by_canonical_code(self):
        first = TireMasterImportRequest(
            source_sheet="03_Llantas",
            import_batch_id="canonical-a",
            source_row_start=30,
            rows=[
                {
                    "Serial": " ll-dup-001 ",
                    "Marca": "Michelin",
                    "design": "Direccional",
                    "Medida": "295/80R22.5",
                    "Prof. original mm": 20,
                    "Prof. actual mm": 12,
                    "Placa actual": "LG880",
                    "position": "D1",
                }
            ],
        )
        second = TireMasterImportRequest(
            source_sheet="03_Llantas",
            import_batch_id="canonical-b",
            source_row_start=31,
            rows=[
                {
                    "Serial": "LL-DUP-001",
                    "Marca": "Michelin",
                    "design": "Direccional",
                    "Medida": "295/80R22.5",
                    "Prof. original mm": 20,
                    "Prof. actual mm": 10,
                    "Placa actual": "LG880",
                    "position": "D1",
                }
            ],
        )

        created = import_tire_master_rows(first, self.db, ADMIN)
        updated = import_tire_master_rows(second, self.db, ADMIN)

        tires = self.db.query(Tire).filter(Tire.serial_number == "LL-DUP-001").all()
        self.assertEqual(created.created_tires, 1)
        self.assertEqual(updated.created_tires, 0)
        self.assertEqual(updated.updated_tires, 1)
        self.assertEqual(len(tires), 1)
        self.assertEqual(tires[0].remaining_tread_mm, 10)

    def test_tire_life_360_groups_identity_events_costs_risks_and_evidence(self):
        inspection = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 9),
            mileage=10600,
            pressure_psi=80,
            tread_outer_mm=3,
            tread_center_mm=3,
            tread_inner_mm=3,
            damage="Corte en costado",
            novelty="Desgaste critico",
            evidence_url="local://foto-8229.jpg",
        )
        create_tire_inspection(inspection, self.db, ADMIN)

        life = get_tire_life_360(self.tire.id, self.db, ADMIN)

        self.assertEqual(life.identification["serial_number"], "8229")
        self.assertEqual(life.current_state["vehicle_plate"], "CAUCA-808")
        self.assertEqual(life.current_state["position"], "P3")
        self.assertEqual(life.costs["accumulated_cost"], 0)
        self.assertEqual(len(life.inspections), 1)
        self.assertEqual(life.inspections[0]["evidence_url"], "local://foto-8229.jpg")
        self.assertTrue(any(risk["action"] == "retirar" for risk in life.risks))
        self.assertTrue(any(item["source"] == "inspection" for item in life.evidence))

    def test_specific_retread_warranty_disposal_and_approval_flows(self):
        retread = create_tire_retread_event(
            TireMovementCreate(
                tire_id=self.tire.id,
                vehicle_id=self.vehicle.id,
                event_date=date(2026, 6, 10),
                position="P3",
                destination="reencauche",
                provider="Renovadora Centro",
                cost=480000,
                novelty="Banda XM aplicada",
                evidence_url="local://orden-reencauche.pdf",
            ),
            self.db,
            ADMIN,
        )
        warranty = create_tire_warranty_event(
            TireMovementCreate(
                tire_id=self.tire.id,
                vehicle_id=self.vehicle.id,
                event_date=date(2026, 6, 11),
                provider="Proveedor Norte",
                cost=-120000,
                novelty="Radicado GAR-77 reconocido parcialmente",
            ),
            self.db,
            ADMIN,
        )
        disposal = create_tire_disposal_event(
            TireMovementCreate(
                tire_id=self.tire.id,
                vehicle_id=self.vehicle.id,
                event_date=date(2026, 6, 12),
                destination="FBU",
                cost=30000,
                justification="Profundidad critica y corte no reparable",
            ),
            self.db,
            ADMIN,
        )
        approved = approve_tire_event(retread.id, self.db, ADMIN)

        self.assertEqual(retread.event_type, "retread")
        self.assertEqual(warranty.event_type, "warranty")
        self.assertEqual(disposal.event_type, "disposal")
        self.assertEqual(approved.approved_by, "admin@test.local")
        self.assertFalse(approved.requires_approval)
        self.assertEqual(self.db.query(Tire).one().status, "disposal")

    def test_cost_reports_and_decision_motor_cover_pending_modules(self):
        self.tire.initial_cost = 1000000
        self.tire.design = "ESC 508"
        self.tire.dimension = "295/80R22.5"
        self.tire.provider = "Proveedor Norte"
        self.tire.min_tread_mm = 3.5
        self.db.commit()
        create_tire_inspection(
            TireInspectionCreate(
                tire_id=self.tire.id,
                vehicle_id=self.vehicle.id,
                position="P3",
                event_date=date(2026, 6, 9),
                mileage=10000,
                pressure_psi=78,
                tread_outer_mm=8,
                tread_center_mm=5,
                tread_inner_mm=2.8,
                damage="Desgaste irregular por eje",
            ),
            self.db,
            ADMIN,
        )

        costs = get_tire_cost_summary(self.db, ADMIN)
        reports = get_tire_operational_reports(self.db, ADMIN)
        decisions = get_tire_decision_motor(self.db, ADMIN, vehicle_id=self.vehicle.id)
        actions = {item.action for item in decisions.recommendations}

        self.assertEqual(costs.total_cost, 1000000)
        self.assertEqual(costs.by_brand[0]["label"], "Supercargo")
        self.assertIn("inspections", reports.sections)
        self.assertIn("reencauchar", actions)
        self.assertIn("rotar", actions)
        self.assertIn("desgaste_anormal", actions)
        self.assertIn("prediccion_falla", actions)
        self.assertTrue(decisions.rankings["brands"])


if __name__ == "__main__":
    unittest.main()
