from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class VehicleBase(BaseModel):
    plate: str
    model: str
    brand: str
    year: int
    mileage: float = 0
    status: str = "active"
    notes: str = ""


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    plate: Optional[str] = None
    model: Optional[str] = None
    brand: Optional[str] = None
    year: Optional[int] = None
    mileage: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class VehicleOut(VehicleBase):
    id: int

    class Config:
        from_attributes = True


class TireBase(BaseModel):
    serial_number: str
    position: str
    remaining_tread_mm: float = 0
    brand: str = ""
    vehicle_id: int


class TireCreate(TireBase):
    pass


class TireUpdate(BaseModel):
    serial_number: Optional[str] = None
    position: Optional[str] = None
    remaining_tread_mm: Optional[float] = None
    brand: Optional[str] = None
    vehicle_id: Optional[int] = None


class TireOut(TireBase):
    id: int

    class Config:
        from_attributes = True


class RetiredTireRecordOut(BaseModel):
    id: int
    source_sheet: str
    source_row: int
    quantity: Optional[int] = None
    mount_date: Optional[date] = None
    dismount_date: Optional[date] = None
    month: str = ""
    year: Optional[int] = None
    company: str = ""
    typology: str = ""
    design: str = ""
    brand: str = ""
    dimension: str = ""
    ply_rating: str = ""
    internal_number: str = ""
    observations: str = ""
    repair: str = ""
    repair_status: str = ""
    patch_count: Optional[int] = None
    condition_code: str = ""
    tire_area: str = ""
    retirement_condition: str = ""
    original_tread_depth: Optional[float] = None
    exterior_tread: Optional[float] = None
    center_tread: Optional[float] = None
    interior_tread: Optional[float] = None
    min_tread: Optional[float] = None
    max_tread: Optional[float] = None
    tread_diff: Optional[float] = None
    unused_bdr_pct: Optional[float] = None
    tread_wear: str = ""
    new_or_retread: str = ""
    retread_band_design: str = ""
    application: str = ""
    lives: Optional[int] = None
    casing_use: Optional[float] = None
    unused_mm: Optional[float] = None
    new_tire_value: Optional[float] = None
    retread_value: Optional[float] = None
    total_cost: Optional[float] = None
    work_time_years: Optional[float] = None
    final_new_tire_km: Optional[float] = None
    final_retread_1_km: Optional[float] = None
    final_retread_2_km: Optional[float] = None
    final_retread_3_km: Optional[float] = None
    regravation_km: Optional[float] = None
    total_km: Optional[float] = None
    cpk: Optional[float] = None

    class Config:
        from_attributes = True


class TireRetirementConditionOut(BaseModel):
    id: int
    code_description: str = ""
    description: str = ""
    column_code: str = ""
    zone: str = ""
    motive_group: str = ""
    area_code: Optional[int] = None

    class Config:
        from_attributes = True


class TireBrandDesignOut(BaseModel):
    id: int
    design: str = ""
    brand: str = ""
    nks: Optional[int] = None
    application: str = ""

    class Config:
        from_attributes = True


class FleetOperationCompanyOut(BaseModel):
    id: int
    company: str = ""
    operation: str = ""
    route: str = ""

    class Config:
        from_attributes = True


class RetiredTireImportRequest(BaseModel):
    workbook_path: str


class RetiredTireImportResultOut(BaseModel):
    retired_tires: int
    conditions: int
    brand_designs: int
    operation_companies: int


class RetiredTireSummaryItemOut(BaseModel):
    label: str
    value: int


class RetiredTireSummaryOut(BaseModel):
    total: int
    retread_count: int
    new_count: int
    avg_casing_use: float
    avg_cpk: float
    by_brand: list[RetiredTireSummaryItemOut]
    by_area: list[RetiredTireSummaryItemOut]
    by_condition: list[RetiredTireSummaryItemOut]
    by_month: list[RetiredTireSummaryItemOut]


class FuelLogBase(BaseModel):
    vehicle_id: int
    liters: float
    mileage: float
    cost: float = 0
    station: str = ""
    logged_on: date = Field(default_factory=date.today)


class FuelLogCreate(FuelLogBase):
    pass


class FuelLogUpdate(BaseModel):
    vehicle_id: Optional[int] = None
    liters: Optional[float] = None
    mileage: Optional[float] = None
    cost: Optional[float] = None
    station: Optional[str] = None
    logged_on: Optional[date] = None


class FuelLogOut(FuelLogBase):
    id: int

    class Config:
        from_attributes = True


class InventoryItemBase(BaseModel):
    sku: str
    name: str
    stock: int = 0
    min_stock: int = 0
    unit_cost: float = 0
    location: str = ""


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    stock: Optional[int] = None
    min_stock: Optional[int] = None
    unit_cost: Optional[float] = None
    location: Optional[str] = None


class InventoryItemOut(InventoryItemBase):
    id: int

    class Config:
        from_attributes = True


class DocumentBase(BaseModel):
    vehicle_id: int
    doc_type: str
    file_url: str
    expires_on: date
    notes: str = ""


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    vehicle_id: Optional[int] = None
    doc_type: Optional[str] = None
    file_url: Optional[str] = None
    expires_on: Optional[date] = None
    notes: Optional[str] = None


class DocumentOut(DocumentBase):
    id: int

    class Config:
        from_attributes = True


class MaintenanceOrderBase(BaseModel):
    vehicle_id: int
    title: str
    description: str = ""
    status: str = "open"
    priority: str = "normal"
    scheduled_for: date = Field(default_factory=date.today)
    cost: float = 0


class MaintenanceOrderCreate(MaintenanceOrderBase):
    pass


class MaintenanceOrderUpdate(BaseModel):
    vehicle_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    scheduled_for: Optional[date] = None
    cost: Optional[float] = None


class MaintenanceOrderOut(MaintenanceOrderBase):
    id: int

    class Config:
        from_attributes = True


class ClientPortalRecordBase(BaseModel):
    title: str
    value: str
    category: str = "general"


class ClientPortalRecordCreate(ClientPortalRecordBase):
    pass


class ClientPortalRecordUpdate(BaseModel):
    title: Optional[str] = None
    value: Optional[str] = None
    category: Optional[str] = None


class ClientPortalRecordOut(ClientPortalRecordBase):
    id: int

    class Config:
        from_attributes = True


class DashboardKpiOut(BaseModel):
    vehicles_total: int
    vehicles_active: int
    tires_total: int
    tires_critical: int
    fuel_logs_count: int
    fuel_total_liters: float
    fuel_total_cost: float
    inventory_items: int
    inventory_low_stock: int
    documents_expiring_soon: int
    maintenance_open: int


class AlertOut(BaseModel):
    id: str
    severity: str
    kind: str
    title: str
    message: str
    entity_id: Optional[int] = None
    entity_type: Optional[str] = None
    action_url: str = ""
    created_at: date
    channels: list[str] = ["web"]
    whatsapp_ready: bool = False


class AuditLogOut(BaseModel):
    id: int
    actor_email: str
    role: str
    module: str
    action: str
    entity_id: Optional[int] = None
    details: str = ""
    created_at: datetime

    class Config:
        from_attributes = True
