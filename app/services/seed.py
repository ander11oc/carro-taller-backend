from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.entities import (
    User,
    Vehicle,
    Tire,
    FuelLog,
    InventoryItem,
    Document,
    MaintenanceOrder,
    ClientPortalRecord,
)

TEST_USERS = [
    {
        "tenant_id": settings.DEFAULT_TENANT_ID,
        "email": "admin@fleet.com",
        "full_name": "Administrador Local",
        "password": "admin123",
        "role": "admin",
    },
    {
        "tenant_id": settings.DEFAULT_TENANT_ID,
        "email": "planner@fleet.com",
        "full_name": "Planeador de Mantenimiento",
        "password": "planner123",
        "role": "planner",
    },
    {
        "tenant_id": settings.DEFAULT_TENANT_ID,
        "email": "mechanic@fleet.com",
        "full_name": "Tecnico de Taller",
        "password": "mechanic123",
        "role": "mechanic",
    },
    {
        "tenant_id": settings.DEFAULT_TENANT_ID,
        "email": "viewer@fleet.com",
        "full_name": "Auditor de Flota",
        "password": "viewer123",
        "role": "viewer",
    },
    {
        "tenant_id": settings.DEFAULT_TENANT_ID,
        "email": "client@fleet.com",
        "full_name": "Cliente Portal",
        "password": "client123",
        "role": "client",
    },
]


def seed_admin(db: Session) -> None:
    for item in TEST_USERS:
        user = db.query(User).filter(User.email == item["email"]).first()
        if not user:
            db.add(
                User(
                    tenant_id=item["tenant_id"],
                    email=item["email"],
                    full_name=item["full_name"],
                    password_hash=hash_password(item["password"]),
                    role=item["role"],
                    is_active=True,
                )
            )
            continue

        user.tenant_id = item["tenant_id"]
        user.full_name = item["full_name"]
        user.role = item["role"]
        user.is_active = True

    db.commit()


def seed_demo_data(db: Session) -> None:
    tenant = settings.DEFAULT_TENANT_ID

    if db.query(Vehicle).filter(Vehicle.tenant_id == tenant).count() > 0:
        return

    vehicles = [
        Vehicle(
            tenant_id=tenant,
            plate="ABC-101",
            brand="Toyota",
            model="Hilux",
            year=2022,
            mileage=58000,
            status="active",
            notes="Vehículo principal de operaciones",
        ),
        Vehicle(
            tenant_id=tenant,
            plate="XYZ-202",
            brand="Chevrolet",
            model="NPR",
            year=2020,
            mileage=120000,
            status="active",
            notes="Camión de carga liviana",
        ),
        Vehicle(
            tenant_id=tenant,
            plate="LMN-303",
            brand="Ford",
            model="Ranger",
            year=2019,
            mileage=145000,
            status="maintenance",
            notes="En revisión por sistema de frenos",
        ),
    ]
    db.add_all(vehicles)
    db.flush()

    db.add_all(
        [
            Tire(
                tenant_id=tenant,
                serial_number="TR-A001",
                position="FL",
                remaining_tread_mm=7.5,
                brand="Michelin",
                vehicle_id=vehicles[0].id,
            ),
            Tire(
                tenant_id=tenant,
                serial_number="TR-A002",
                position="FR",
                remaining_tread_mm=2.1,
                brand="Michelin",
                vehicle_id=vehicles[0].id,
            ),
            Tire(
                tenant_id=tenant,
                serial_number="TR-B001",
                position="RL",
                remaining_tread_mm=5.4,
                brand="Bridgestone",
                vehicle_id=vehicles[1].id,
            ),
            Tire(
                tenant_id=tenant,
                serial_number="TR-B002",
                position="RR",
                remaining_tread_mm=2.8,
                brand="Bridgestone",
                vehicle_id=vehicles[1].id,
            ),
        ]
    )

    today = date.today()
    db.add_all(
        [
            FuelLog(
                tenant_id=tenant,
                vehicle_id=vehicles[0].id,
                liters=45.5,
                mileage=57500,
                cost=210000,
                station="Estación Norte",
                logged_on=today - timedelta(days=10),
            ),
            FuelLog(
                tenant_id=tenant,
                vehicle_id=vehicles[0].id,
                liters=48.0,
                mileage=58000,
                cost=222000,
                station="Estación Norte",
                logged_on=today - timedelta(days=2),
            ),
            FuelLog(
                tenant_id=tenant,
                vehicle_id=vehicles[1].id,
                liters=80.0,
                mileage=120000,
                cost=380000,
                station="Estación Centro",
                logged_on=today - timedelta(days=5),
            ),
        ]
    )

    db.add_all(
        [
            InventoryItem(
                tenant_id=tenant,
                sku="FIL-OIL-01",
                name="Filtro de aceite",
                stock=12,
                min_stock=5,
                unit_cost=18000,
                location="Estante A1",
            ),
            InventoryItem(
                tenant_id=tenant,
                sku="FIL-AIR-01",
                name="Filtro de aire",
                stock=3,
                min_stock=5,
                unit_cost=25000,
                location="Estante A2",
            ),
            InventoryItem(
                tenant_id=tenant,
                sku="BRA-PAD-01",
                name="Pastillas de freno",
                stock=8,
                min_stock=4,
                unit_cost=85000,
                location="Estante B1",
            ),
            InventoryItem(
                tenant_id=tenant,
                sku="OIL-15W40",
                name="Aceite 15W-40",
                stock=2,
                min_stock=10,
                unit_cost=42000,
                location="Bodega líquidos",
            ),
        ]
    )

    db.add_all(
        [
            Document(
                tenant_id=tenant,
                vehicle_id=vehicles[0].id,
                doc_type="SOAT",
                file_url="local://docs/abc101-soat.pdf",
                expires_on=today + timedelta(days=15),
                notes="Cubre operación nacional",
            ),
            Document(
                tenant_id=tenant,
                vehicle_id=vehicles[0].id,
                doc_type="Tecnomecánica",
                file_url="local://docs/abc101-tecno.pdf",
                expires_on=today + timedelta(days=90),
                notes="",
            ),
            Document(
                tenant_id=tenant,
                vehicle_id=vehicles[1].id,
                doc_type="SOAT",
                file_url="local://docs/xyz202-soat.pdf",
                expires_on=today + timedelta(days=5),
                notes="Urgente renovación",
            ),
        ]
    )

    db.add_all(
        [
            MaintenanceOrder(
                tenant_id=tenant,
                vehicle_id=vehicles[2].id,
                title="Reemplazo de pastillas",
                description="Cambio completo en eje delantero",
                status="in_progress",
                priority="high",
                scheduled_for=today,
                cost=180000,
            ),
            MaintenanceOrder(
                tenant_id=tenant,
                vehicle_id=vehicles[0].id,
                title="Cambio de aceite",
                description="Servicio preventivo",
                status="open",
                priority="normal",
                scheduled_for=today + timedelta(days=7),
                cost=120000,
            ),
        ]
    )

    db.add_all(
        [
            ClientPortalRecord(
                tenant_id=tenant,
                title="Vehículos asignados",
                value="3",
                category="resumen",
            ),
            ClientPortalRecord(
                tenant_id=tenant,
                title="Costo de mantenimiento mes",
                value="$300,000 COP",
                category="costos",
            ),
        ]
    )

    db.commit()
