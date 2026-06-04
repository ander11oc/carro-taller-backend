from datetime import datetime, date
from sqlalchemy import String, Integer, DateTime, ForeignKey, Float, Date, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    actor_email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(50), default="viewer")
    module: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    plate: Mapped[str] = mapped_column(String(30), index=True)
    model: Mapped[str] = mapped_column(String(100))
    brand: Mapped[str] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(Integer)
    mileage: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(40), default="active")
    notes: Mapped[str] = mapped_column(Text, default="")


class Tire(Base, TimestampMixin):
    __tablename__ = "tires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    serial_number: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    position: Mapped[str] = mapped_column(String(40))
    remaining_tread_mm: Mapped[float] = mapped_column(Float, default=0)
    brand: Mapped[str] = mapped_column(String(80), default="")
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))


class RetiredTireRecord(Base, TimestampMixin):
    __tablename__ = "retired_tire_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    source_sheet: Mapped[str] = mapped_column(String(80), default="Data")
    source_row: Mapped[int] = mapped_column(Integer, default=0)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mount_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dismount_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    month: Mapped[str] = mapped_column(String(40), default="", index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    company: Mapped[str] = mapped_column(String(160), default="", index=True)
    typology: Mapped[str] = mapped_column(String(120), default="")
    design: Mapped[str] = mapped_column(String(120), default="")
    brand: Mapped[str] = mapped_column(String(120), default="", index=True)
    dimension: Mapped[str] = mapped_column(String(80), default="")
    ply_rating: Mapped[str] = mapped_column(String(40), default="")
    internal_number: Mapped[str] = mapped_column(String(120), default="", index=True)
    observations: Mapped[str] = mapped_column(Text, default="")
    repair: Mapped[str] = mapped_column(String(120), default="")
    repair_status: Mapped[str] = mapped_column(String(120), default="")
    patch_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_code: Mapped[str] = mapped_column(String(80), default="", index=True)
    tire_area: Mapped[str] = mapped_column(String(120), default="", index=True)
    retirement_condition: Mapped[str] = mapped_column(Text, default="")
    original_tread_depth: Mapped[float | None] = mapped_column(Float, nullable=True)
    exterior_tread: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_tread: Mapped[float | None] = mapped_column(Float, nullable=True)
    interior_tread: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_tread: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tread: Mapped[float | None] = mapped_column(Float, nullable=True)
    tread_diff: Mapped[float | None] = mapped_column(Float, nullable=True)
    unused_bdr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tread_wear: Mapped[str] = mapped_column(String(120), default="")
    new_or_retread: Mapped[str] = mapped_column(String(20), default="", index=True)
    retread_band_design: Mapped[str] = mapped_column(String(120), default="")
    application: Mapped[str] = mapped_column(String(120), default="")
    lives: Mapped[int | None] = mapped_column(Integer, nullable=True)
    casing_use: Mapped[float | None] = mapped_column(Float, nullable=True)
    unused_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_tire_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    retread_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    work_time_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_new_tire_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_retread_1_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_retread_2_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_retread_3_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    regravation_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpk: Mapped[float | None] = mapped_column(Float, nullable=True)


class TireRetirementCondition(Base, TimestampMixin):
    __tablename__ = "tire_retirement_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    code_description: Mapped[str] = mapped_column(String(80), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    column_code: Mapped[str] = mapped_column(String(80), default="")
    zone: Mapped[str] = mapped_column(String(120), default="", index=True)
    motive_group: Mapped[str] = mapped_column(String(120), default="")
    area_code: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TireBrandDesign(Base, TimestampMixin):
    __tablename__ = "tire_brand_designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    design: Mapped[str] = mapped_column(String(120), default="", index=True)
    brand: Mapped[str] = mapped_column(String(120), default="", index=True)
    nks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application: Mapped[str] = mapped_column(String(120), default="")


class FleetOperationCompany(Base, TimestampMixin):
    __tablename__ = "fleet_operation_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    company: Mapped[str] = mapped_column(String(160), default="", index=True)
    operation: Mapped[str] = mapped_column(String(180), default="")
    route: Mapped[str] = mapped_column(String(120), default="")


class FuelLog(Base, TimestampMixin):
    __tablename__ = "fuel_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    liters: Mapped[float] = mapped_column(Float)
    mileage: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float, default=0)
    station: Mapped[str] = mapped_column(String(120), default="")
    logged_on: Mapped[date] = mapped_column(Date, default=date.today)


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    location: Mapped[str] = mapped_column(String(120), default="")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    doc_type: Mapped[str] = mapped_column(String(80))
    file_url: Mapped[str] = mapped_column(String(255))
    expires_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")


class MaintenanceOrder(Base, TimestampMixin):
    __tablename__ = "maintenance_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="open")
    priority: Mapped[str] = mapped_column(String(30), default="normal")
    scheduled_for: Mapped[date] = mapped_column(Date, default=date.today)
    cost: Mapped[float] = mapped_column(Float, default=0)


class ClientPortalRecord(Base, TimestampMixin):
    __tablename__ = "client_portal_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(60), default="general")
