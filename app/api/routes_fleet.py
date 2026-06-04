from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import String, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.entities import (
    Vehicle,
    Tire,
    RetiredTireRecord,
    TireRetirementCondition,
    TireBrandDesign,
    FleetOperationCompany,
    FuelLog,
    InventoryItem,
    Document,
    MaintenanceOrder,
    ClientPortalRecord,
)
from app.schemas.fleet import (
    VehicleCreate,
    VehicleUpdate,
    VehicleOut,
    TireCreate,
    TireUpdate,
    TireOut,
    RetiredTireRecordOut,
    TireRetirementConditionOut,
    TireBrandDesignOut,
    FleetOperationCompanyOut,
    RetiredTireImportRequest,
    RetiredTireImportResultOut,
    RetiredTireSummaryOut,
    FuelLogCreate,
    FuelLogUpdate,
    FuelLogOut,
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryItemOut,
    DocumentCreate,
    DocumentUpdate,
    DocumentOut,
    MaintenanceOrderCreate,
    MaintenanceOrderUpdate,
    MaintenanceOrderOut,
    ClientPortalRecordCreate,
    ClientPortalRecordUpdate,
    ClientPortalRecordOut,
    DashboardKpiOut,
    AlertOut,
)
from app.services.retired_tire_import import import_retired_tire_workbook
from app.services.retired_tire_summary import get_retired_tire_summary
from app.services.fleet_alerts import get_fleet_alerts


router = APIRouter(prefix="/fleet", tags=["fleet"])


# =====================================================
# Helpers
# =====================================================
def _scope(model, user):
    return model.tenant_id == user["tenant_id"]


def _get_or_404(db: Session, model, item_id: int, user):
    obj = (
        db.query(model)
        .filter(model.id == item_id, _scope(model, user))
        .first()
    )
    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{model.__name__} not found"
        )
    return obj


def _apply_update(obj, payload):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)


def _csv_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# =====================================================
# Vehicles
# =====================================================
@router.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    q: Optional[str] = Query(None),
    status_f: Optional[str] = Query(None, alias="status"),
):
    query = db.query(Vehicle).filter(_scope(Vehicle, user))
    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Vehicle.plate).like(pattern)
            | func.lower(Vehicle.brand).like(pattern)
            | func.lower(Vehicle.model).like(pattern)
        )
    if status_f:
        query = query.filter(Vehicle.status == status_f)
    return query.order_by(Vehicle.id.desc()).all()


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(
    payload: VehicleCreate, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = Vehicle(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/vehicles/{item_id}", response_model=VehicleOut)
def get_vehicle(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_or_404(db, Vehicle, item_id, user)


@router.put("/vehicles/{item_id}", response_model=VehicleOut)
def update_vehicle(
    item_id: int,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, Vehicle, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/vehicles/{item_id}", status_code=204)
def delete_vehicle(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = _get_or_404(db, Vehicle, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Tires
# =====================================================
@router.get("/tires", response_model=list[TireOut])
def list_tires(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    vehicle_id: Optional[int] = None,
):
    query = db.query(Tire).filter(_scope(Tire, user))
    if vehicle_id is not None:
        query = query.filter(Tire.vehicle_id == vehicle_id)
    return query.order_by(Tire.id.desc()).all()


@router.post("/tires", response_model=TireOut, status_code=201)
def create_tire(
    payload: TireCreate, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = Tire(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/tires/{item_id}", response_model=TireOut)
def get_tire(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_or_404(db, Tire, item_id, user)


@router.put("/tires/{item_id}", response_model=TireOut)
def update_tire(
    item_id: int,
    payload: TireUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, Tire, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/tires/{item_id}", status_code=204)
def delete_tire(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item = _get_or_404(db, Tire, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Retired tire import + catalogs
# =====================================================
@router.post("/retired-tires/import", response_model=RetiredTireImportResultOut)
def import_retired_tires(
    payload: RetiredTireImportRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        return import_retired_tire_workbook(
            db, payload.workbook_path, tenant_id=user["tenant_id"]
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/retired-tires/summary", response_model=RetiredTireSummaryOut)
def retired_tire_summary(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    q: Optional[str] = None,
    company: Optional[str] = None,
    brand: Optional[str] = None,
    brands: Optional[str] = None,
    year: Optional[int] = None,
    area: Optional[str] = None,
    areas: Optional[str] = None,
    conditions: Optional[str] = None,
    months: Optional[str] = None,
):
    return get_retired_tire_summary(
        db,
        user["tenant_id"],
        q=q,
        company=company,
        brand=brand,
        brands=_csv_values(brands),
        year=year,
        area=area,
        areas=_csv_values(areas),
        conditions=_csv_values(conditions),
        months=_csv_values(months),
    )


@router.get("/retired-tires", response_model=list[RetiredTireRecordOut])
def list_retired_tires(
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    q: Optional[str] = None,
    company: Optional[str] = None,
    brand: Optional[str] = None,
    brands: Optional[str] = None,
    year: Optional[int] = None,
    area: Optional[str] = None,
    areas: Optional[str] = None,
    conditions: Optional[str] = None,
    months: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(RetiredTireRecord).filter(_scope(RetiredTireRecord, user))
    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            func.lower(RetiredTireRecord.internal_number).like(pattern)
            | func.lower(RetiredTireRecord.retirement_condition).like(pattern)
            | func.lower(RetiredTireRecord.condition_code).like(pattern)
        )
    if company:
        query = query.filter(RetiredTireRecord.company == company)
    if brand:
        query = query.filter(RetiredTireRecord.brand == brand)
    brand_values = _csv_values(brands)
    if brand_values:
        query = query.filter(RetiredTireRecord.brand.in_(brand_values))
    if year is not None:
        query = query.filter(RetiredTireRecord.year == year)
    if area:
        query = query.filter(RetiredTireRecord.tire_area == area)
    area_values = _csv_values(areas)
    if area_values:
        query = query.filter(RetiredTireRecord.tire_area.in_(area_values))
    condition_values = _csv_values(conditions)
    if condition_values:
        query = query.filter(RetiredTireRecord.retirement_condition.in_(condition_values))
    month_values = _csv_values(months)
    if month_values:
        query = query.filter(
            (func.cast(RetiredTireRecord.year, String) + " " + RetiredTireRecord.month).in_(month_values)
        )
    response.headers["X-Total-Count"] = str(query.count())
    return (
        query.order_by(
            RetiredTireRecord.dismount_date.desc().nullslast(),
            RetiredTireRecord.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get(
    "/retired-tire-conditions", response_model=list[TireRetirementConditionOut]
)
def list_retired_tire_conditions(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    zone: Optional[str] = None,
):
    query = db.query(TireRetirementCondition).filter(
        _scope(TireRetirementCondition, user)
    )
    if zone:
        query = query.filter(TireRetirementCondition.zone == zone)
    return query.order_by(TireRetirementCondition.code_description.asc()).all()


@router.get("/tire-brand-designs", response_model=list[TireBrandDesignOut])
def list_tire_brand_designs(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    brand: Optional[str] = None,
):
    query = db.query(TireBrandDesign).filter(_scope(TireBrandDesign, user))
    if brand:
        query = query.filter(TireBrandDesign.brand == brand)
    return query.order_by(TireBrandDesign.brand.asc(), TireBrandDesign.design.asc()).all()


@router.get("/operation-companies", response_model=list[FleetOperationCompanyOut])
def list_operation_companies(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    route: Optional[str] = None,
):
    query = db.query(FleetOperationCompany).filter(_scope(FleetOperationCompany, user))
    if route:
        query = query.filter(FleetOperationCompany.route == route)
    return query.order_by(FleetOperationCompany.company.asc()).all()


# =====================================================
# Fuel logs
# =====================================================
@router.get("/fuel-logs", response_model=list[FuelLogOut])
def list_fuel_logs(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    vehicle_id: Optional[int] = None,
):
    query = db.query(FuelLog).filter(_scope(FuelLog, user))
    if vehicle_id is not None:
        query = query.filter(FuelLog.vehicle_id == vehicle_id)
    return query.order_by(FuelLog.id.desc()).all()


@router.post("/fuel-logs", response_model=FuelLogOut, status_code=201)
def create_fuel_log(
    payload: FuelLogCreate, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = FuelLog(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/fuel-logs/{item_id}", response_model=FuelLogOut)
def get_fuel_log(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_or_404(db, FuelLog, item_id, user)


@router.put("/fuel-logs/{item_id}", response_model=FuelLogOut)
def update_fuel_log(
    item_id: int,
    payload: FuelLogUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, FuelLog, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/fuel-logs/{item_id}", status_code=204)
def delete_fuel_log(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = _get_or_404(db, FuelLog, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Inventory
# =====================================================
@router.get("/inventory", response_model=list[InventoryItemOut])
def list_inventory(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    q: Optional[str] = None,
    low_only: bool = False,
):
    query = db.query(InventoryItem).filter(_scope(InventoryItem, user))
    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            func.lower(InventoryItem.sku).like(pattern)
            | func.lower(InventoryItem.name).like(pattern)
        )
    if low_only:
        query = query.filter(InventoryItem.stock <= InventoryItem.min_stock)
    return query.order_by(InventoryItem.id.desc()).all()


@router.post("/inventory", response_model=InventoryItemOut, status_code=201)
def create_inventory(
    payload: InventoryItemCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = InventoryItem(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/inventory/{item_id}", response_model=InventoryItemOut)
def get_inventory(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_or_404(db, InventoryItem, item_id, user)


@router.put("/inventory/{item_id}", response_model=InventoryItemOut)
def update_inventory(
    item_id: int,
    payload: InventoryItemUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, InventoryItem, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/inventory/{item_id}", status_code=204)
def delete_inventory(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = _get_or_404(db, InventoryItem, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Documents
# =====================================================
@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    vehicle_id: Optional[int] = None,
    expiring_in_days: Optional[int] = None,
):
    query = db.query(Document).filter(_scope(Document, user))
    if vehicle_id is not None:
        query = query.filter(Document.vehicle_id == vehicle_id)
    if expiring_in_days is not None:
        target = date.today() + timedelta(days=expiring_in_days)
        query = query.filter(Document.expires_on <= target)
    return query.order_by(Document.expires_on.asc()).all()


@router.post("/documents", response_model=DocumentOut, status_code=201)
def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = Document(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/documents/{item_id}", response_model=DocumentOut)
def get_document(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_or_404(db, Document, item_id, user)


@router.put("/documents/{item_id}", response_model=DocumentOut)
def update_document(
    item_id: int,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, Document, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/documents/{item_id}", status_code=204)
def delete_document(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = _get_or_404(db, Document, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Maintenance orders
# =====================================================
@router.get("/maintenance", response_model=list[MaintenanceOrderOut])
def list_maintenance(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    status_f: Optional[str] = Query(None, alias="status"),
):
    query = db.query(MaintenanceOrder).filter(_scope(MaintenanceOrder, user))
    if status_f:
        query = query.filter(MaintenanceOrder.status == status_f)
    return query.order_by(MaintenanceOrder.scheduled_for.asc()).all()


@router.post("/maintenance", response_model=MaintenanceOrderOut, status_code=201)
def create_maintenance(
    payload: MaintenanceOrderCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = MaintenanceOrder(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/maintenance/{item_id}", response_model=MaintenanceOrderOut)
def get_maintenance(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    return _get_or_404(db, MaintenanceOrder, item_id, user)


@router.put("/maintenance/{item_id}", response_model=MaintenanceOrderOut)
def update_maintenance(
    item_id: int,
    payload: MaintenanceOrderUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, MaintenanceOrder, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/maintenance/{item_id}", status_code=204)
def delete_maintenance(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = _get_or_404(db, MaintenanceOrder, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Client portal
# =====================================================
@router.get("/portal", response_model=list[ClientPortalRecordOut])
def list_portal(
    db: Session = Depends(get_db), user=Depends(get_current_user)
):
    return (
        db.query(ClientPortalRecord)
        .filter(_scope(ClientPortalRecord, user))
        .order_by(ClientPortalRecord.id.desc())
        .all()
    )


@router.post("/portal", response_model=ClientPortalRecordOut, status_code=201)
def create_portal(
    payload: ClientPortalRecordCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = ClientPortalRecord(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/portal/{item_id}", response_model=ClientPortalRecordOut)
def get_portal(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_or_404(db, ClientPortalRecord, item_id, user)


@router.put("/portal/{item_id}", response_model=ClientPortalRecordOut)
def update_portal(
    item_id: int,
    payload: ClientPortalRecordUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_or_404(db, ClientPortalRecord, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/portal/{item_id}", status_code=204)
def delete_portal(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    item = _get_or_404(db, ClientPortalRecord, item_id, user)
    db.delete(item)
    db.commit()
    return None


# =====================================================
# Dashboard + alerts
# =====================================================
TIRE_CRITICAL_MM = 3.0
DOC_EXPIRING_WINDOW_DAYS = 30


@router.get("/dashboard", response_model=DashboardKpiOut)
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    tenant = user["tenant_id"]
    vehicles_total = db.query(Vehicle).filter(Vehicle.tenant_id == tenant).count()
    vehicles_active = (
        db.query(Vehicle)
        .filter(Vehicle.tenant_id == tenant, Vehicle.status == "active")
        .count()
    )
    tires_total = db.query(Tire).filter(Tire.tenant_id == tenant).count()
    tires_critical = (
        db.query(Tire)
        .filter(Tire.tenant_id == tenant, Tire.remaining_tread_mm <= TIRE_CRITICAL_MM)
        .count()
    )
    fuel_logs_count = db.query(FuelLog).filter(FuelLog.tenant_id == tenant).count()
    fuel_total_liters = (
        db.query(func.coalesce(func.sum(FuelLog.liters), 0))
        .filter(FuelLog.tenant_id == tenant)
        .scalar()
        or 0
    )
    fuel_total_cost = (
        db.query(func.coalesce(func.sum(FuelLog.cost), 0))
        .filter(FuelLog.tenant_id == tenant)
        .scalar()
        or 0
    )
    inventory_items = (
        db.query(InventoryItem).filter(InventoryItem.tenant_id == tenant).count()
    )
    inventory_low_stock = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.tenant_id == tenant,
            InventoryItem.stock <= InventoryItem.min_stock,
        )
        .count()
    )
    soon = date.today() + timedelta(days=DOC_EXPIRING_WINDOW_DAYS)
    documents_expiring_soon = (
        db.query(Document)
        .filter(Document.tenant_id == tenant, Document.expires_on <= soon)
        .count()
    )
    maintenance_open = (
        db.query(MaintenanceOrder)
        .filter(
            MaintenanceOrder.tenant_id == tenant,
            MaintenanceOrder.status.in_(["open", "in_progress"]),
        )
        .count()
    )
    return DashboardKpiOut(
        vehicles_total=vehicles_total,
        vehicles_active=vehicles_active,
        tires_total=tires_total,
        tires_critical=tires_critical,
        fuel_logs_count=fuel_logs_count,
        fuel_total_liters=float(fuel_total_liters),
        fuel_total_cost=float(fuel_total_cost),
        inventory_items=inventory_items,
        inventory_low_stock=inventory_low_stock,
        documents_expiring_soon=documents_expiring_soon,
        maintenance_open=maintenance_open,
    )


@router.get("/alerts", response_model=list[AlertOut])
def alerts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return get_fleet_alerts(db, user["tenant_id"])
