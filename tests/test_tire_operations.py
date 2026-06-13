from datetime import date
from io import BytesIO
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
    create_alignment,
    get_tire_cost_summary,
    get_tire_decision_motor,
    get_tire_life_360,
    get_tire_operational_reports,
    get_vehicle_tire_events,
    import_tire_master_rows,
    preview_tire_master_import,
    get_tire_recommendations,
    get_vehicle_tire_map,
    import_providers_csv,
    import_vehicles_csv,
    mount_tire_to_vehicle,
    reconcile_tire_relationships,
    rotate_vehicle_tires,
    router,
    sync_vehicle_tire_mounts,
    update_tire_inspection,
)
from app.db.base import Base
from app.models.entities import Provider, Tire, TireEvent, Vehicle, VehicleTirePosition
from app.schemas.fleet import (
    RelationshipReconcileRequest,
    AlignmentPayload,
    InspectionUpdatePayload,
    MountTirePayload,
    RotateVehicleTiresPayload,
    TireCatalogEntryCreate,
    TireInspectionCreate,
    TireMasterImportRequest,
    TireMasterPreviewRequest,
    TireMovementCreate,
    VehicleTireMountSyncItem,
    VehicleTireMountSyncRequest,
)


ADMIN = {
    "tenant_id": "tenant_test",
    "email": "admin@test.local",
    "role": "admin",
}


class CsvUpload:
    def __init__(self, content: str):
        self.file = BytesIO(content.encode("utf-8"))


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

    def test_vehicle_tire_events_include_inspection_evidence_url(self):
        create_tire_inspection(
            TireInspectionCreate(
                tire_id=self.tire.id,
                vehicle_id=self.vehicle.id,
                position="P3",
                event_date=date(2026, 6, 9),
                mileage=10600,
                pressure_psi=92,
                tread_outer_mm=11,
                tread_center_mm=10.5,
                tread_inner_mm=10,
                evidence_url="local://foto-inspeccion.jpg",
            ),
            self.db,
            ADMIN,
        )

        events = get_vehicle_tire_events(self.vehicle.id, 1, 50, self.db, ADMIN)

        self.assertEqual(events[0].evidence_url, "local://foto-inspeccion.jpg")

    def test_inspection_uses_four_tread_measurements_and_can_be_corrected_without_duplicate(self):
        payload = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 9),
            mileage=10600,
            pressure_psi=92,
            tread_outer_mm=11,
            tread_center_mm=10.5,
            tread_center_outer_mm=7.25,
            tread_inner_mm=10,
            novelty="Medicion con centro exterior bajo",
        )

        created = create_tire_inspection(payload, self.db, ADMIN)
        created_min_tread = created.min_tread_mm
        corrected = update_tire_inspection(
            created.id,
            InspectionUpdatePayload(
                event_date=date(2026, 6, 9),
                position="P3",
                mileage=10610,
                pressure_psi=94,
                tread_outer_mm=11,
                tread_center_mm=10.5,
                tread_center_outer_mm=8,
                tread_inner_mm=10,
                novelty="Correccion de lectura",
                justification="Error de digitacion en centro exterior",
            ),
            self.db,
            ADMIN,
        )

        tire = self.db.query(Tire).filter(Tire.id == self.tire.id).one()
        events = self.db.query(TireEvent).filter(TireEvent.event_type == "inspection").all()
        self.assertEqual(created_min_tread, 7.25)
        self.assertEqual(corrected.min_tread_mm, 8)
        self.assertEqual(getattr(events[0], "tread_center_outer_mm"), 8)
        self.assertEqual(tire.remaining_tread_mm, 8)
        self.assertEqual(len(events), 1)

    def test_inspection_update_requires_justification(self):
        created = create_tire_inspection(
            TireInspectionCreate(
                tire_id=self.tire.id,
                vehicle_id=self.vehicle.id,
                position="P3",
                event_date=date(2026, 6, 9),
                mileage=10600,
                pressure_psi=92,
                tread_outer_mm=11,
                tread_center_mm=10.5,
                tread_center_outer_mm=10,
                tread_inner_mm=10,
            ),
            self.db,
            ADMIN,
        )

        with self.assertRaises(HTTPException) as err:
            update_tire_inspection(
                created.id,
                InspectionUpdatePayload(
                    event_date=date(2026, 6, 10),
                    position="P3",
                    tread_outer_mm=10,
                    tread_center_mm=10,
                    tread_center_outer_mm=10,
                    tread_inner_mm=10,
                    justification="",
                ),
                self.db,
                ADMIN,
            )

        self.assertEqual(err.exception.status_code, 400)
        self.assertIn("justificacion", err.exception.detail.lower())

    def test_mount_tire_replace_existing_dismounts_previous_tire(self):
        new_tire = Tire(
            tenant_id="tenant_test",
            serial_number="NEW-900",
            position="",
            brand="Michelin",
            remaining_tread_mm=18,
            status="warehouse",
            location="Bodega principal",
        )
        self.db.add(new_tire)
        self.db.commit()
        self.db.refresh(new_tire)

        event = mount_tire_to_vehicle(
            self.vehicle.id,
            MountTirePayload(
                tire_id=new_tire.id,
                position="P3",
                mount_date=date(2026, 6, 14),
                mount_mileage=10800,
                tread_at_mount_mm=18,
                provider="Proveedor Montaje",
                replace_existing=True,
            ),
            self.db,
            ADMIN,
        )

        old_tire = self.db.query(Tire).filter(Tire.id == self.tire.id).one()
        position = self.db.query(VehicleTirePosition).filter(VehicleTirePosition.position_code == "P3").one()
        dismount_event = self.db.query(TireEvent).filter(TireEvent.event_type == "dismount").one()
        self.assertEqual(event.event_type, "mount")
        self.assertEqual(old_tire.status, "warehouse")
        self.assertIsNone(old_tire.vehicle_id)
        self.assertEqual(position.tire_id, new_tire.id)
        self.assertEqual(dismount_event.tire_id, self.tire.id)

    def test_mount_tire_rejects_occupied_position_without_replace_flag(self):
        new_tire = Tire(
            tenant_id="tenant_test",
            serial_number="NEW-901",
            position="",
            brand="Michelin",
            remaining_tread_mm=18,
            status="warehouse",
        )
        self.db.add(new_tire)
        self.db.commit()

        with self.assertRaises(HTTPException) as err:
            mount_tire_to_vehicle(
                self.vehicle.id,
                MountTirePayload(
                    tire_id=new_tire.id,
                    position="P3",
                    mount_date=date(2026, 6, 14),
                    replace_existing=False,
                ),
                self.db,
                ADMIN,
            )

        self.assertEqual(err.exception.status_code, 409)

    def test_mount_tire_links_existing_provider_and_normalizes_position(self):
        provider = Provider(
            tenant_id="tenant_test",
            name="Solistica",
            normalized_name="SOLISTICA",
            provider_type="montaje",
            is_active=True,
        )
        new_tire = Tire(
            tenant_id="tenant_test",
            serial_number="NEW-902",
            position="",
            brand="Michelin",
            remaining_tread_mm=18,
            status="warehouse",
        )
        self.db.add_all([provider, new_tire])
        self.db.commit()
        self.db.refresh(new_tire)
        self.db.refresh(provider)

        event = mount_tire_to_vehicle(
            self.vehicle.id,
            MountTirePayload(
                tire_id=new_tire.id,
                position=" P1 ",
                mount_date=date(2026, 6, 14),
                mount_mileage=10800,
                tread_at_mount_mm=18,
                provider=" Solistica ",
            ),
            self.db,
            ADMIN,
        )

        self.db.refresh(new_tire)
        stored_event = self.db.query(TireEvent).filter(TireEvent.id == event.id).one()
        position = self.db.query(VehicleTirePosition).filter(VehicleTirePosition.position_code == "P1").one()
        self.assertEqual(new_tire.position, "P1")
        self.assertEqual(new_tire.provider, "Solistica")
        self.assertEqual(new_tire.provider_id, provider.id)
        self.assertEqual(stored_event.provider_id, provider.id)
        self.assertEqual(position.tire_id, new_tire.id)

    def test_rotate_vehicle_tires_swaps_positions_and_records_event(self):
        other = Tire(
            tenant_id="tenant_test",
            serial_number="8230",
            vehicle_id=self.vehicle.id,
            position="P1",
            brand="Goodyear",
            remaining_tread_mm=13,
            status="mounted",
        )
        self.db.add(other)
        pos1 = self.db.query(VehicleTirePosition).filter(VehicleTirePosition.position_code == "P1").one()
        pos1.tire_id = other.id
        self.db.commit()
        self.db.refresh(other)

        event = rotate_vehicle_tires(
            self.vehicle.id,
            RotateVehicleTiresPayload(
                from_position="P3",
                to_position="P1",
                rotation_date=date(2026, 6, 14),
                mileage=10900,
                provider="Taller Rotacion",
                cost=50000,
                observation="Rotacion preventiva",
            ),
            self.db,
            ADMIN,
        )

        self.db.refresh(self.tire)
        self.db.refresh(other)
        pos1 = self.db.query(VehicleTirePosition).filter(VehicleTirePosition.position_code == "P1").one()
        pos3 = self.db.query(VehicleTirePosition).filter(VehicleTirePosition.position_code == "P3").one()
        self.assertEqual(event.event_type, "rotation")
        self.assertEqual(self.tire.position, "P1")
        self.assertEqual(other.position, "P3")
        self.assertEqual(pos1.tire_id, self.tire.id)
        self.assertEqual(pos3.tire_id, other.id)

    def test_rotate_vehicle_tires_records_tread_and_pressure_for_moved_tire(self):
        other = Tire(
            tenant_id="tenant_test",
            serial_number="8230",
            vehicle_id=self.vehicle.id,
            position="P1",
            brand="Goodyear",
            remaining_tread_mm=13,
            status="mounted",
        )
        self.db.add(other)
        self.db.commit()
        self.db.refresh(other)
        pos1 = self.db.query(VehicleTirePosition).filter(VehicleTirePosition.position_code == "P1").one()
        pos1.tire_id = other.id
        self.db.commit()

        event = rotate_vehicle_tires(
            self.vehicle.id,
            RotateVehicleTiresPayload(
                from_position="P3",
                to_position="P1",
                rotation_date=date(2026, 6, 14),
                mileage=10900,
                provider="Taller Rotacion",
                cost=50000,
                observation="Rotacion con medicion",
                tread_inner_mm=14,
                tread_center_mm=13.5,
                tread_center_outer_mm=12.75,
                tread_outer_mm=15,
                pressure_psi=100,
            ),
            self.db,
            ADMIN,
        )

        self.db.refresh(self.tire)
        stored_event = self.db.query(TireEvent).filter(TireEvent.id == event.id).one()
        self.assertEqual(self.tire.position, "P1")
        self.assertEqual(self.tire.remaining_tread_mm, 12.75)
        self.assertEqual(stored_event.pressure_psi, 100)
        self.assertEqual(stored_event.tread_inner_mm, 14)
        self.assertEqual(stored_event.tread_center_mm, 13.5)
        self.assertEqual(stored_event.tread_center_outer_mm, 12.75)
        self.assertEqual(stored_event.tread_outer_mm, 15)
        self.assertEqual(stored_event.min_tread_mm, 12.75)

    def test_alignment_records_selected_positions(self):
        event = create_alignment(
            self.vehicle.id,
            AlignmentPayload(
                alignment_date=date(2026, 6, 14),
                mileage=10900,
                provider="Alineaciones Norte",
                cost=120000,
                alignment_type="direccion",
                positions=["P1", "P3"],
                observation="Alineacion eje delantero",
            ),
            self.db,
            ADMIN,
        )

        stored = self.db.query(TireEvent).filter(TireEvent.id == event.id).one()
        self.assertEqual(event.event_type, "alignment")
        self.assertEqual(stored.position, "P1,P3")
        self.assertEqual(stored.provider, "Alineaciones Norte")

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

    def test_inspection_rejects_negative_or_zero_measurements(self):
        payload = TireInspectionCreate(
            tire_id=self.tire.id,
            vehicle_id=self.vehicle.id,
            position="P3",
            event_date=date(2026, 6, 9),
            mileage=10600,
            pressure_psi=-1,
            tread_outer_mm=-0.1,
            tread_center_mm=0.1,
            tread_inner_mm=0.1,
        )

        with self.assertRaises(HTTPException) as err:
            create_tire_inspection(payload, self.db, ADMIN)

        self.assertEqual(err.exception.status_code, 400)
        self.assertIn("mayores que cero", err.exception.detail)

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
        self.assertEqual(getattr(rows[0], "vehicle_plate"), "CAUCA-808")

    def test_vehicle_search_route_is_registered_before_numeric_vehicle_route(self):
        paths = [route.path for route in router.routes if hasattr(route, "path")]
        self.assertLess(paths.index("/fleet/vehicles/search"), paths.index("/fleet/vehicles/{item_id}"))

    def test_vehicle_csv_import_uses_existing_vehicle_fields(self):
        csv_text = "\n".join(
            [
                "Reporte exportado",
                "Vehiculo,Tipo,Marca/Linea,km Actual,Conductor,Ciudad,Centro de Costos,Grupo primario,Grupo secundario",
                "abc-123,Camion,Chevrolet NPR,42.949,Ana Ruiz,Medellin,CC-01,Primario A,Secundario B",
            ]
        )

        result = import_vehicles_csv(CsvUpload(csv_text), self.db, ADMIN)

        vehicle = self.db.query(Vehicle).filter(Vehicle.plate == "ABC-123").one()
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.errors, [])
        self.assertEqual(vehicle.brand, "Chevrolet")
        self.assertEqual(vehicle.model, "NPR")
        self.assertEqual(vehicle.current_driver, "Ana Ruiz")
        self.assertEqual(vehicle.cost_center, "CC-01")
        self.assertEqual(vehicle.line, "NPR")
        self.assertEqual(vehicle.mileage, 42949)
        self.assertIn("Camion", vehicle.notes)
        self.assertIn("Medellin", vehicle.notes)
        self.assertIn("Grupo primario: Primario A", vehicle.notes)
        self.assertIn("Grupo secundario: Secundario B", vehicle.notes)

    def test_vehicle_csv_import_updates_existing_vehicle_fields(self):
        existing = Vehicle(
            tenant_id="tenant_test",
            plate="QJL223",
            brand="OLD",
            model="OLD",
            year=2020,
            mileage=0,
            status="active",
            notes="",
            line="",
            current_driver="",
            cost_center="",
        )
        self.db.add(existing)
        self.db.commit()

        csv_text = "\n".join(
            [
                "Reporte exportado",
                "Vehiculo,Tipo,Marca/Linea,km Actual,Conductor,Ciudad,Centro de Costos,Grupo primario,Grupo secundario",
                "QJL223,TRACTOCAMION,SHACMAN X5000,42.949,Sin Definir,BOGOTA,218,Operacion,Primario",
            ]
        )

        result = import_vehicles_csv(CsvUpload(csv_text), self.db, ADMIN)

        vehicle = self.db.query(Vehicle).filter(
            Vehicle.plate == "QJL223",
            Vehicle.tenant_id == "tenant_test",
        ).one()
        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.updated, 1)
        self.assertEqual(vehicle.brand, "SHACMAN")
        self.assertEqual(vehicle.model, "X5000")
        self.assertEqual(vehicle.line, "X5000")
        self.assertEqual(vehicle.mileage, 42949)
        self.assertEqual(vehicle.current_driver, "Sin Definir")
        self.assertEqual(vehicle.cost_center, "218")
        self.assertIn("TRACTOCAMION", vehicle.notes)
        self.assertIn("Grupo primario: Operacion", vehicle.notes)
        self.assertIn("Grupo secundario: Primario", vehicle.notes)

    def test_vehicle_csv_import_accepts_equipment_search_export_columns(self):
        csv_text = "\n".join(
            [
                "Buscar Equipo",
                "Vehiculo,Identificacion Aux.,km Actual,Horometro Actual,Marca,Linea,Tipo Vehiculo,Centro de Costos,Ciudad",
                "QJL223,,42.949,N/D,SHACMAN,X5000,TRACTOCAMION,218,BOGOTA",
            ]
        )

        result = import_vehicles_csv(CsvUpload(csv_text), self.db, ADMIN)

        vehicle = self.db.query(Vehicle).filter(
            Vehicle.plate == "QJL223",
            Vehicle.tenant_id == "tenant_test",
        ).one()
        self.assertEqual(result.created, 1)
        self.assertEqual(vehicle.brand, "SHACMAN")
        self.assertEqual(vehicle.model, "X5000")
        self.assertEqual(vehicle.line, "X5000")
        self.assertEqual(vehicle.mileage, 42949)
        self.assertEqual(vehicle.cost_center, "218")
        self.assertIn("Tipo: TRACTOCAMION", vehicle.notes)
        self.assertIn("Ciudad: BOGOTA", vehicle.notes)

    def test_vehicle_csv_import_preserves_existing_values_when_source_is_incomplete(self):
        existing = Vehicle(
            tenant_id="tenant_test",
            plate="QJL223",
            brand="SHACMAN",
            model="X5000",
            year=2020,
            mileage=42949,
            status="active",
            notes="Tipo: TRACTOCAMION; Ciudad: BOGOTA; Grupo primario: Operacion; Grupo secundario: Primario",
            line="X5000",
            current_driver="Sin Definir",
            cost_center="218",
        )
        self.db.add(existing)
        self.db.commit()

        csv_text = "\n".join(
            [
                "Reporte exportado",
                "Vehiculo,Tipo,Marca/Linea,Conductor,Ciudad,Centro de Costos,Grupo primario,Grupo secundario,Tolerancia",
                "QJL223,TRACTOCAMION,SHACMAN X5000,,,,,,Disponible completo",
            ]
        )

        result = import_vehicles_csv(CsvUpload(csv_text), self.db, ADMIN)

        vehicle = self.db.query(Vehicle).filter(
            Vehicle.plate == "QJL223",
            Vehicle.tenant_id == "tenant_test",
        ).one()
        self.assertEqual(result.updated, 1)
        self.assertEqual(vehicle.mileage, 42949)
        self.assertEqual(vehicle.current_driver, "Sin Definir")
        self.assertEqual(vehicle.cost_center, "218")
        self.assertEqual(vehicle.line, "X5000")
        self.assertIn("Ciudad: BOGOTA", vehicle.notes)
        self.assertIn("Grupo primario: Operacion", vehicle.notes)
        self.assertIn("Grupo secundario: Primario", vehicle.notes)

    def test_provider_csv_import_creates_and_updates_dedicated_provider_rows(self):
        csv_text = "\n".join(
            [
                "INFORME:,Lista de Proveedores",
                "FECHA:,12/jun./2026 22:58",
                "",
                "Nombre,Contacto,E-Mail,Tipo,Categorias,Ciudad,",
                "\"AUTOMUNDIAL SA\",\"Michell\",\"ventas@automundial.com.co\",\"Llantas\",\"\",\"BOGOTA\",",
                "\"REMAX\",\"\",\"\",\"Llantas\",\"\",\"CALI\",",
            ]
        )

        first = import_providers_csv(CsvUpload(csv_text), self.db, ADMIN)
        second = import_providers_csv(
            CsvUpload(csv_text.replace("Michell", "Michell Actualizada")),
            self.db,
            ADMIN,
        )

        providers = self.db.query(Provider).order_by(Provider.name).all()
        automundial = (
            self.db.query(Provider)
            .filter(Provider.normalized_name == "AUTOMUNDIAL SA")
            .one()
        )

        self.assertEqual(first.created, 2)
        self.assertEqual(first.updated, 0)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.updated, 2)
        self.assertEqual(len(providers), 2)
        self.assertEqual(automundial.provider_type, "Llantas")
        self.assertEqual(automundial.contact, "Michell Actualizada")
        self.assertEqual(automundial.city, "BOGOTA")

    def test_vehicle_tire_mount_sync_creates_six_tires_positions_events_and_provider_links(self):
        self.db.add(
            Provider(
                tenant_id="tenant_test",
                name="Solistica",
                normalized_name="SOLISTICA",
                provider_type="Llantas",
            )
        )
        vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="JKV615",
            brand="KENWORTH",
            model="T460",
            year=2020,
            mileage=538643,
        )
        self.db.add(vehicle)
        self.db.commit()

        payload = VehicleTireMountSyncRequest(
            plate="JKV615",
            source="cloudfleet-test",
            mounted=[
                VehicleTireMountSyncItem(
                    position=str(position),
                    code=str(code),
                    tire_label=label,
                    life_code="VN",
                    mount_date=date(2026, 3, 11),
                    mount_mileage=529585 if position <= 2 else 459514,
                    last_tread_date=date(2026, 3, 11),
                    last_tread_km=529585 if position <= 2 else 459514,
                    km_in_vehicle=9058,
                    tire_cost=1700000 if position <= 2 else 1352000,
                    original_tread_mm=17.5 if position <= 2 else 20,
                    effective_tread_mm=14.5 if position <= 2 else 17,
                    lowest_tread_mm=17.5 if position <= 2 else 20,
                    provider="Solistica",
                )
                for position, code, label in [
                    (1, 8819, "MICHELIN X INCITY Z 295/80R22.5"),
                    (2, 8820, "MICHELIN X INCITY Z 295/80R22.5"),
                    (3, 8264, "SUPERCARGO SC558 295/80R22.5"),
                    (4, 8262, "SUPERCARGO SC558 295/80R22.5"),
                    (5, 8263, "SUPERCARGO SC558 295/80R22.5"),
                    (6, 8261, "SUPERCARGO SC558 295/80R22.5"),
                ]
            ],
        )

        result = sync_vehicle_tire_mounts(payload, self.db, ADMIN)

        tires = self.db.query(Tire).filter(Tire.vehicle_id == vehicle.id).all()
        positions = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == vehicle.id
        ).all()
        events = self.db.query(TireEvent).filter(TireEvent.event_type == "mount_sync").all()
        self.assertEqual(result.created_tires, 6)
        self.assertEqual(result.created_events, 6)
        self.assertEqual(len(tires), 6)
        self.assertEqual({position.position_code for position in positions}, {"1", "2", "3", "4", "5", "6"})
        self.assertEqual(len(events), 6)
        self.assertTrue(all(tire.provider_id is not None for tire in tires))

    def test_vehicle_tire_mount_sync_updates_existing_warehouse_tire(self):
        vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="JUY925",
            brand="STARK",
            model="E-CARGO",
            year=2020,
            mileage=61625,
        )
        existing = Tire(
            tenant_id="tenant_test",
            serial_number="7982",
            vehicle_id=None,
            position="N/A",
            brand="LAUFEN",
            status="warehouse",
            remaining_tread_mm=0,
        )
        self.db.add_all([vehicle, existing])
        self.db.commit()

        result = sync_vehicle_tire_mounts(
            VehicleTireMountSyncRequest(
                plate="JUY925",
                mounted=[
                    VehicleTireMountSyncItem(
                        position="2",
                        code="7982",
                        tire_label="LAUFEN LF21 215/75R17.5",
                        life_code="VN",
                        mount_date=date(2023, 10, 10),
                        mount_mileage=31611,
                        last_tread_km=60998,
                        km_total=29387,
                        km_in_vehicle=29387,
                        tire_cost=950000,
                        original_tread_mm=16,
                        effective_tread_mm=13,
                        lowest_tread_mm=9,
                    )
                ],
            ),
            self.db,
            ADMIN,
        )

        tire = self.db.query(Tire).filter(Tire.serial_number == "7982").one()
        position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == vehicle.id,
            VehicleTirePosition.position_code == "2",
        ).one()
        self.assertEqual(result.created_tires, 0)
        self.assertEqual(result.updated_tires, 1)
        self.assertEqual(tire.vehicle_id, vehicle.id)
        self.assertEqual(tire.status, "mounted")
        self.assertEqual(tire.position, "2")
        self.assertEqual(tire.mount_mileage, 31611)
        self.assertEqual(tire.remaining_tread_mm, 9)
        self.assertEqual(position.tire_id, tire.id)

    def test_vehicle_tire_mount_sync_is_idempotent_for_same_vehicle_snapshot(self):
        vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="JUY925",
            brand="STARK",
            model="E-CARGO",
            year=2020,
            mileage=61625,
        )
        self.db.add(vehicle)
        self.db.commit()
        payload = VehicleTireMountSyncRequest(
            plate="JUY925",
            mounted=[
                VehicleTireMountSyncItem(
                    position="1",
                    code="7981",
                    tire_label="LAUFEN LF21 215/75R17.5",
                    mount_date=date(2024, 9, 6),
                    mount_mileage=42854,
                    last_tread_km=60998,
                    lowest_tread_mm=9,
                    tire_cost=1235000,
                )
            ],
        )

        first = sync_vehicle_tire_mounts(payload, self.db, ADMIN)
        second = sync_vehicle_tire_mounts(payload, self.db, ADMIN)

        events = self.db.query(TireEvent).filter(TireEvent.event_type == "mount_sync").all()
        self.assertEqual(first.created_events, 1)
        self.assertEqual(second.created_events, 0)
        self.assertEqual(len(events), 1)

    def test_vehicle_tire_mount_sync_moves_tire_from_previous_vehicle_with_history(self):
        old_vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="OLD001",
            brand="OLD",
            model="OLD",
            year=2020,
            mileage=0,
        )
        new_vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="NEW001",
            brand="NEW",
            model="NEW",
            year=2020,
            mileage=0,
        )
        tire = Tire(
            tenant_id="tenant_test",
            serial_number="MOVE-1",
            vehicle_id=None,
            position="1",
            brand="MICHELIN",
            remaining_tread_mm=12,
        )
        self.db.add_all([old_vehicle, new_vehicle, tire])
        self.db.commit()
        tire.vehicle_id = old_vehicle.id
        self.db.add(
            VehicleTirePosition(
                tenant_id="tenant_test",
                vehicle_id=old_vehicle.id,
                position_code="1",
                tire_id=tire.id,
            )
        )
        self.db.commit()

        result = sync_vehicle_tire_mounts(
            VehicleTireMountSyncRequest(
                plate="NEW001",
                mounted=[
                    VehicleTireMountSyncItem(
                        position="3",
                        code="MOVE-1",
                        tire_label="MICHELIN X MULTI 295/80R22.5",
                        mount_date=date(2026, 6, 12),
                        lowest_tread_mm=11,
                    )
                ],
            ),
            self.db,
            ADMIN,
        )

        old_position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == old_vehicle.id,
            VehicleTirePosition.position_code == "1",
        ).one()
        tire = self.db.query(Tire).filter(Tire.serial_number == "MOVE-1").one()
        transfer = self.db.query(TireEvent).filter(TireEvent.event_type == "dismount_sync").one()
        self.assertEqual(result.moved_tires, 1)
        self.assertIsNone(old_position.tire_id)
        self.assertEqual(tire.vehicle_id, new_vehicle.id)
        self.assertEqual(tire.position, "3")
        self.assertEqual(transfer.vehicle_id, old_vehicle.id)

    def test_vehicle_tire_mount_sync_clears_vehicle_positions_when_cloudfleet_has_no_mounts(self):
        vehicle = Vehicle(
            tenant_id="tenant_test",
            plate="VACIO1",
            brand="FORD",
            model="RANGER",
            year=2020,
            mileage=0,
        )
        tire = Tire(
            tenant_id="tenant_test",
            serial_number="VAC-1",
            vehicle_id=None,
            position="1",
            brand="MICHELIN",
            status="mounted",
            remaining_tread_mm=10,
        )
        self.db.add_all([vehicle, tire])
        self.db.commit()
        tire.vehicle_id = vehicle.id
        self.db.add(
            VehicleTirePosition(
                tenant_id="tenant_test",
                vehicle_id=vehicle.id,
                position_code="1",
                tire_id=tire.id,
            )
        )
        self.db.commit()

        result = sync_vehicle_tire_mounts(
            VehicleTireMountSyncRequest(plate="VACIO1", mounted=[], clear_missing=True),
            self.db,
            ADMIN,
        )

        position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == vehicle.id,
            VehicleTirePosition.position_code == "1",
        ).one()
        tire = self.db.query(Tire).filter(Tire.serial_number == "VAC-1").one()
        self.assertEqual(result.cleared_positions, 1)
        self.assertIsNone(position.tire_id)
        self.assertIsNone(tire.vehicle_id)
        self.assertEqual(tire.status, "warehouse")

    def test_reconcile_tire_relationships_links_provider_and_repairs_position_mismatch(self):
        provider = Provider(
            tenant_id="tenant_test",
            name="AUTOMUNDIAL SA",
            normalized_name="AUTOMUNDIAL SA",
            provider_type="Llantas",
        )
        tire = Tire(
            tenant_id="tenant_test",
            serial_number="REC-1",
            vehicle_id=self.vehicle.id,
            position="P5",
            brand="MICHELIN",
            provider="Automundial SA",
            remaining_tread_mm=10,
        )
        self.db.add_all([provider, tire])
        self.db.commit()
        self.db.add(
            VehicleTirePosition(
                tenant_id="tenant_test",
                vehicle_id=self.vehicle.id,
                position_code="P5",
                tire_id=None,
            )
        )
        self.db.commit()

        result = reconcile_tire_relationships(
            RelationshipReconcileRequest(apply=True),
            self.db,
            ADMIN,
        )

        position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == self.vehicle.id,
            VehicleTirePosition.position_code == "P5",
        ).one()
        tire = self.db.query(Tire).filter(Tire.serial_number == "REC-1").one()
        self.assertGreaterEqual(result.fixed_provider_links, 1)
        self.assertGreaterEqual(result.fixed_positions, 1)
        self.assertEqual(tire.provider_id, provider.id)
        self.assertEqual(position.tire_id, tire.id)

    def test_reconcile_tire_relationships_treats_na_position_as_missing(self):
        tire = Tire(
            tenant_id="tenant_test",
            serial_number="REC-NA",
            vehicle_id=self.vehicle.id,
            position="N/A",
            brand="MICHELIN",
            status="mounted",
            remaining_tread_mm=10,
        )
        self.db.add(tire)
        self.db.commit()

        result = reconcile_tire_relationships(
            RelationshipReconcileRequest(apply=True),
            self.db,
            ADMIN,
        )

        position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == self.vehicle.id,
            VehicleTirePosition.position_code == "N/A",
        ).first()
        self.assertGreaterEqual(result.mounted_without_vehicle_or_position, 1)
        self.assertIsNone(position)

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
        self.assertEqual(tire.mount_mileage, 134.9)
        self.assertEqual(tire.tread_at_mount_mm, 16)
        self.assertEqual(tire.remaining_tread_mm, 4.5)
        self.assertEqual(tire.original_tread_mm, 16)
        self.assertEqual(tire.vehicle_id, vehicle.id)
        self.assertEqual(position.tire_id, tire.id)
        self.assertEqual(event.event_type, "master_import")
        self.assertEqual(event.mileage, 134.9)
        self.assertIn("03_Llantas", event.novelty)
        self.assertIn("fila 502", event.novelty)
        self.assertEqual(result.import_batch_id, "llantas-test-batch")

    def test_master_import_reads_cloudfleet_catalog_location_as_mount(self):
        result = import_tire_master_rows(
            TireMasterImportRequest(
                source_sheet="ListaLlantas20260612",
                import_batch_id="catalog-location-batch",
                source_row_start=2,
                rows=[
                    {
                        "Codigo Llanta": "7982",
                        "Llanta": "LAUFEN LF21 215/75R17.5",
                        "Ubicacion": "Montada\nVehiculo: JUY925\nPosicion: 2",
                        "Proveedor": "Solistica",
                        "Costo": "950000",
                        "Codigo Vida": "VN",
                        "% Desgaste": "43,75",
                        "Tipo Posicion": "Toda posicion (All Position)",
                    }
                ],
            ),
            self.db,
            ADMIN,
        )

        tire = self.db.query(Tire).filter(Tire.serial_number == "7982").one()
        vehicle = self.db.query(Vehicle).filter(Vehicle.plate == "JUY925").one()
        position = self.db.query(VehicleTirePosition).filter(
            VehicleTirePosition.vehicle_id == vehicle.id,
            VehicleTirePosition.position_code == "2",
        ).one()

        self.assertEqual(result.created_tires, 1)
        self.assertEqual(tire.vehicle_id, vehicle.id)
        self.assertEqual(tire.position, "2")
        self.assertEqual(tire.brand, "LAUFEN")
        self.assertEqual(tire.design, "LF21")
        self.assertEqual(tire.dimension, "215/75R17.5")
        self.assertEqual(tire.status, "mounted")
        self.assertEqual(tire.provider, "Solistica")
        self.assertEqual(tire.initial_cost, 950000)
        self.assertEqual(position.tire_id, tire.id)

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
