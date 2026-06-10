from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


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
    dot: str = ""
    design: str = ""
    dimension: str = ""
    life_cycle: str = "new"
    retread_band: str = ""
    status: str = "mounted"
    location: str = ""
    site: str = ""
    provider: str = ""
    target_pressure_psi: Optional[float] = None
    original_tread_mm: Optional[float] = None
    min_tread_mm: Optional[float] = None
    initial_cost: Optional[float] = None
    purchase_date: Optional[date] = None
    source_sheet: str = ""
    source_row: Optional[int] = None
    import_batch_id: str = ""


class TireCreate(TireBase):
    pass


class TireUpdate(BaseModel):
    serial_number: Optional[str] = None
    position: Optional[str] = None
    remaining_tread_mm: Optional[float] = None
    brand: Optional[str] = None
    vehicle_id: Optional[int] = None
    dot: Optional[str] = None
    design: Optional[str] = None
    dimension: Optional[str] = None
    life_cycle: Optional[str] = None
    retread_band: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None
    site: Optional[str] = None
    provider: Optional[str] = None
    target_pressure_psi: Optional[float] = None
    original_tread_mm: Optional[float] = None
    min_tread_mm: Optional[float] = None
    initial_cost: Optional[float] = None
    purchase_date: Optional[date] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    import_batch_id: Optional[str] = None


class TireOut(TireBase):
    id: int

    class Config:
        from_attributes = True


class TireCatalogEntryCreate(BaseModel):
    catalog_type: str
    value: str
    description: str = ""


class TireCatalogEntryOut(TireCatalogEntryCreate):
    id: int
    normalized_value: str
    is_active: bool = True

    class Config:
        from_attributes = True


class VehicleTirePositionCreate(BaseModel):
    vehicle_id: int
    position_code: str
    axle: str = ""
    side: str = ""
    tire_id: Optional[int] = None
    target_pressure_psi: Optional[float] = None
    min_tread_mm: Optional[float] = None


class VehicleTirePositionOut(VehicleTirePositionCreate):
    id: int
    tire_serial: str = ""
    tire_brand: str = ""
    remaining_tread_mm: Optional[float] = None
    status: str = "missing"

    class Config:
        from_attributes = True


class VehicleTireMapOut(BaseModel):
    vehicle_id: int
    plate: str
    has_missing_positions: bool
    positions: list[VehicleTirePositionOut]


class TireInspectionCreate(BaseModel):
    tire_id: int
    vehicle_id: int
    position: str
    event_date: date = Field(default_factory=date.today)
    mileage: Optional[float] = None
    pressure_psi: Optional[float] = None
    tread_outer_mm: float
    tread_center_mm: float
    tread_inner_mm: float
    damage: str = ""
    novelty: str = ""
    evidence_url: str = ""
    justification: str = ""


class TireMovementCreate(BaseModel):
    tire_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    event_type: str = "movement"
    event_date: date = Field(default_factory=date.today)
    position: str = ""
    mileage: Optional[float] = None
    origin: str = ""
    destination: str = ""
    provider: str = ""
    cost: Optional[float] = None
    novelty: str = ""
    evidence_url: str = ""
    justification: str = ""


class TireEventOut(BaseModel):
    id: int
    tire_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    event_type: str
    event_date: date
    position: str = ""
    mileage: Optional[float] = None
    pressure_psi: Optional[float] = None
    tread_outer_mm: Optional[float] = None
    tread_center_mm: Optional[float] = None
    tread_inner_mm: Optional[float] = None
    min_tread_mm: Optional[float] = None
    damage: str = ""
    novelty: str = ""
    origin: str = ""
    destination: str = ""
    provider: str = ""
    cost: Optional[float] = None
    evidence_url: str = ""
    justification: str = ""
    guidance: str = ""
    created_by: str = ""
    created_role: str = ""
    requires_approval: bool = False
    approved_by: str = ""

    class Config:
        from_attributes = True


class TireRecommendationOut(BaseModel):
    action: str
    severity: str
    title: str
    reason: str
    tire_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    position: str = ""


class TireCostSummaryOut(BaseModel):
    total_cost: float
    total_km: float
    cost_per_km: Optional[float] = None
    by_tire: list[dict[str, str | int | float | None]]
    by_vehicle: list[dict[str, str | int | float | None]]
    by_provider: list[dict[str, str | int | float | None]]
    by_brand: list[dict[str, str | int | float | None]]
    by_design: list[dict[str, str | int | float | None]]
    by_life: list[dict[str, str | int | float | None]]


class TireOperationalReportsOut(BaseModel):
    sections: dict[str, list[dict[str, str | int | float | bool | None]]]


class TireDecisionMotorOut(BaseModel):
    recommendations: list[TireRecommendationOut]
    rankings: dict[str, list[dict[str, str | int | float | None]]]


class TireMasterPreviewRequest(BaseModel):
    rows: list[dict[str, str | int | float | None]]


class TireMasterPreviewOut(BaseModel):
    total_rows: int
    valid_count: int
    incomplete_count: int
    duplicate_serials: list[str]
    missing_catalogs: dict[str, list[str]]
    guidance: str


class TireMasterImportRequest(TireMasterPreviewRequest):
    source_sheet: str = "03_Llantas"
    import_batch_id: str = ""
    source_row_start: int = 2
    create_missing_catalogs: bool = True
    create_missing_vehicles: bool = True
    update_existing: bool = True


class TireMasterImportOut(BaseModel):
    total_rows: int
    created_tires: int
    updated_tires: int
    created_vehicles: int
    created_positions: int
    created_events: int
    skipped_rows: int
    duplicate_serials: list[str]
    errors: list[str]
    import_batch_id: str
    guidance: str


class TireLife360Out(BaseModel):
    tire_id: int
    identification: dict[str, str | int | float | None]
    current_state: dict[str, str | int | float | bool | None]
    mounting_history: list[dict[str, str | int | float | bool | None]]
    inspections: list[dict[str, str | int | float | bool | None]]
    maintenance: list[dict[str, str | int | float | bool | None]]
    retread: list[dict[str, str | int | float | bool | None]]
    warranties: list[dict[str, str | int | float | bool | None]]
    costs: dict[str, str | int | float | None]
    risks: list[dict[str, str | int | float | bool | None]]
    evidence: list[dict[str, str | int | float | bool | None]]


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


MAX_REQUIREMENT_IMAGES = 6
MAX_REQUIREMENT_IMAGE_CHARS = 850_000


def _validate_requirement_images(images: Optional[list[str]]) -> Optional[list[str]]:
    if images is None:
        return images
    if len(images) > MAX_REQUIREMENT_IMAGES:
        raise ValueError("maximo 6 imagenes por requerimiento")
    for image in images:
        if len(image) > MAX_REQUIREMENT_IMAGE_CHARS:
            raise ValueError("cada imagen debe pesar maximo 600KB aproximados")
    return images


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = ""
    requester: str = ""
    images: list[str] = Field(default_factory=list)

    @field_validator("images")
    @classmethod
    def validate_images(cls, images: list[str]) -> list[str]:
        return _validate_requirement_images(images) or []


class RequirementUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=180)
    description: Optional[str] = None
    requester: Optional[str] = None
    status: Optional[str] = None
    team_done: Optional[bool] = None
    client_ok: Optional[bool] = None
    images: Optional[list[str]] = None

    @field_validator("images")
    @classmethod
    def validate_images(cls, images: Optional[list[str]]) -> Optional[list[str]]:
        return _validate_requirement_images(images)


class RequirementOut(BaseModel):
    id: int
    title: str
    description: str = ""
    requester: str = ""
    status: str = "pending"
    team_done: bool = False
    client_ok: bool = False
    images: list[str] = Field(default_factory=list)
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime
    updated_at: datetime

    @field_validator("images", mode="before")
    @classmethod
    def normalize_images(cls, images):
        return images or []

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
