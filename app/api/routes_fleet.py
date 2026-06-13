from datetime import date, datetime, timedelta
import csv
import io
import re
import unicodedata
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import String, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.entities import (
    Vehicle,
    Tire,
    TireCatalogEntry,
    Provider,
    TireEvent,
    VehicleTirePosition,
    RetiredTireRecord,
    TireRetirementCondition,
    TireBrandDesign,
    FleetOperationCompany,
    FuelLog,
    InventoryItem,
    Document,
    MaintenanceOrder,
    ClientPortalRecord,
    Requirement,
    AuditLog,
)
from app.schemas.fleet import (
    VehicleCreate,
    VehicleUpdate,
    VehicleOut,
    TireCreate,
    TireUpdate,
    TireOut,
    TireCatalogEntryCreate,
    TireCatalogEntryOut,
    ProviderCreate,
    ProviderUpdate,
    ProviderOut,
    ProviderImportResultOut,
    TireInspectionCreate,
    TireMovementCreate,
    TireEventOut,
    TireCostSummaryOut,
    TireDecisionMotorOut,
    TireLife360Out,
    TireMasterImportRequest,
    TireMasterImportOut,
    TireMasterPreviewRequest,
    TireMasterPreviewOut,
    VehicleTireMountSyncRequest,
    VehicleTireMountSyncOut,
    RelationshipReconcileRequest,
    RelationshipReconcileOut,
    TireOperationalReportsOut,
    TireRecommendationOut,
    VehicleTirePositionCreate,
    VehicleTirePositionOut,
    VehicleTireMapOut,
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
    RequirementCreate,
    RequirementUpdate,
    RequirementOut,
    DashboardKpiOut,
    AlertOut,
    AuditLogOut,
    # VehicleTireView
    VehicleInfoOut,
    VehicleTireRowOut,
    VehicleEventItemOut,
    MountTirePayload,
    DismountBatchPayload,
    AlignmentPayload,
    DismountBatchResult,
)
from app.api.permissions import require_module_action
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


def _attach_tire_vehicle_plates(db: Session, user, tires: list[Tire]) -> list[Tire]:
    vehicle_ids = {tire.vehicle_id for tire in tires if tire.vehicle_id is not None}
    if not vehicle_ids:
        return tires
    plates = {
        vehicle_id: plate
        for vehicle_id, plate in (
            db.query(Vehicle.id, Vehicle.plate)
            .filter(_scope(Vehicle, user), Vehicle.id.in_(vehicle_ids))
            .all()
        )
    }
    for tire in tires:
        tire.vehicle_plate = plates.get(tire.vehicle_id, "")
    return tires


def _attach_tire_vehicle_plate(db: Session, user, tire: Tire) -> Tire:
    return _attach_tire_vehicle_plates(db, user, [tire])[0]


def _apply_update(obj, payload):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)


def _write_audit_log(
    db: Session,
    user,
    module: str,
    action: str,
    entity_id: int | None = None,
    details: str = "",
):
    db.add(
        AuditLog(
            tenant_id=user["tenant_id"],
            actor_email=user["email"],
            role=user.get("role", "viewer"),
            module=module,
            action=action,
            entity_id=entity_id,
            details=details,
        )
    )
    db.commit()


def _normalize_requirement_state(item: Requirement) -> None:
    if item.client_ok:
        item.team_done = True
    item.status = "approved" if item.client_ok else "completed" if item.team_done else "pending"


def _csv_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_catalog_value(value: str) -> str:
    return " ".join(value.strip().upper().replace("-", " ").split())


def _normalize_serial(value: str) -> str:
    return "".join(value.strip().upper().split())


def _find_tire_by_serial(db: Session, user, serial: str) -> Tire | None:
    normalized = _normalize_serial(serial)
    return (
        db.query(Tire)
        .filter(
            _scope(Tire, user),
            func.upper(func.replace(func.trim(Tire.serial_number), " ", "")) == normalized,
        )
        .first()
    )


def _normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return "".join(
        char.lower()
        for char in normalized
        if char.isalnum()
    )

def _row_text(row: dict, *names: str) -> str:
    normalized_row = {_normalize_header(str(key)): value for key, value in row.items()}
    for name in names:
        value = row.get(name)
        if value is None:
            value = normalized_row.get(_normalize_header(name))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _row_float(row: dict, *names: str) -> float | None:
    value = _row_text(row, *names)
    if not value:
        return None
    clean = value.replace("$", "").replace(" ", "")
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    elif clean.count(".") > 1:
        clean = clean.replace(".", "")
    try:
        return float(clean)
    except ValueError:
        return None


def _row_money(row: dict, *names: str) -> float | None:
    value = _row_text(row, *names)
    if not value:
        return None
    clean = value.replace("$", "").replace(" ", "")
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "." in clean and len(clean.rsplit(".", 1)[-1]) == 3:
        clean = clean.replace(".", "")
    elif "," in clean:
        clean = clean.replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return None


def _row_date(row: dict, *names: str) -> date | None:
    value = _row_text(row, *names)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _status_from_sheet(value: str) -> str:
    normalized = _normalize_catalog_value(value)
    if normalized.startswith("MONTADA") or normalized.startswith("MONTADO"):
        return "mounted"
    if normalized.startswith("BODEGA"):
        return "warehouse"
    mapping = {
        "MONTADA": "mounted",
        "MONTADO": "mounted",
        "BODEGA": "warehouse",
        "ALMACEN": "warehouse",
        "REENCAUCHE": "retread",
        "GARANTIA": "warranty",
        "BAJA": "disposal",
        "FBU": "disposal",
    }
    return mapping.get(normalized, value.strip().lower() or "mounted")


def _parse_tire_label(label: str) -> dict[str, str]:
    text = " ".join((label or "").split())
    if not text:
        return {"brand": "", "design": "", "dimension": ""}
    upper = text.upper()
    known_brands = (
        "BF GOODRICH",
        "DOUBLE COIN",
        "GOOD YEAR",
        "SUPER CARGO",
        "SUPER ALLIANCE",
        "CONTINENTAL",
        "GOODYEAR",
        "MICHELIN",
        "LAUFEN",
        "CHENGSHAN",
        "KUMHO",
        "APLUS",
        "DUNLOP",
        "PIRELLI",
        "BRIDGESTONE",
        "FIRESTONE",
        "HANKOOK",
        "WESTLAKE",
    )
    brand = ""
    for candidate in known_brands:
        if upper == candidate or upper.startswith(f"{candidate} "):
            brand = text[: len(candidate)]
            break
    if not brand:
        brand = text.split(" ", 1)[0]

    dimension_match = re.search(r"\b\d{3}/\d{2}R\d{2}(?:\.\d)?\b", upper)
    dimension = dimension_match.group(0) if dimension_match else ""
    design = text[len(brand):].strip()
    if dimension:
        design = re.sub(re.escape(dimension), "", design, flags=re.IGNORECASE).strip()
    return {"brand": brand.strip(), "design": design.strip(), "dimension": dimension.strip()}


def _parse_tire_location(value: str) -> dict[str, str]:
    text = " ".join((value or "").replace("\r", "\n").split())
    vehicle_match = re.search(r"veh[iÃ­]culo\s*:\s*([A-Za-z0-9-]+)", text, flags=re.IGNORECASE)
    position_match = re.search(r"posici[oÃ³]n\s*:\s*([A-Za-z0-9()/-]+)", text, flags=re.IGNORECASE)
    status = text
    for separator in (" Vehiculo:", " VehÃ­culo:", " Posicion:", " PosiciÃ³n:"):
        if separator in status:
            status = status.split(separator, 1)[0].strip()
    return {
        "status": status,
        "plate": vehicle_match.group(1).upper() if vehicle_match else "",
        "position": position_match.group(1).upper() if position_match else "",
    }


def _default_original_tread(dimension: str) -> float | None:
    if not dimension:
        return None
    if "17.5" in dimension:
        return 17.0
    if "22.5" in dimension:
        return 18.0
    return 16.0


def _tire_master_values(row: dict) -> dict[str, str | float | None]:
    label = _row_text(row, "llanta", "tire", "descripcion", "descripciÃ³n")
    parsed_label = _parse_tire_label(label)
    location = _row_text(row, "ubicacion", "ubicaciÃ³n", "location")
    parsed_location = _parse_tire_location(location)

    original_tread = _row_float(
        row,
        "prof. original mm",
        "prof original mm",
        "profundidad original",
        "original_tread_mm",
    )
    dimension = _row_text(row, "dimension", "medida", "dim") or parsed_label["dimension"]
    if original_tread is None:
        original_tread = _default_original_tread(dimension)

    remaining_tread = _row_float(
        row,
        "prof. actual mm",
        "prof actual mm",
        "profundidad actual",
        "remaining_tread_mm",
    )
    wear_pct = _row_float(row, "% desgaste", "desgaste", "wear_pct")
    if remaining_tread is None and original_tread is not None and wear_pct is not None:
        remaining_tread = round(original_tread * max(0.0, 100.0 - wear_pct) / 100.0, 2)

    return {
        "serial": _normalize_serial(_row_text(
            row,
            "serial_number",
            "serial",
            "codigo llanta",
            "cÃ³digo llanta",
            "codigo",
            "code",
            "internal_number",
        )),
        "brand": _row_text(row, "brand", "marca") or parsed_label["brand"],
        "design": _row_text(row, "design", "diseno", "diseÃ±o") or parsed_label["design"],
        "dimension": dimension,
        "plate": _row_text(row, "placa actual", "placa", "plate", "vehicle_plate", "vehiculo", "vehÃ­culo") or parsed_location["plate"],
        "position": _row_text(row, "posicion", "posiciÃ³n", "position") or parsed_location["position"],
        "location": location,
        "status_source": _row_text(row, "estado", "status") or parsed_location["status"] or location,
        "life_cycle": _row_text(row, "vida", "codigo vida", "cÃ³digo vida", "life_cycle") or "VN",
        "original_tread": original_tread,
        "remaining_tread": remaining_tread,
    }


def _inspection_min_tread(payload: TireInspectionCreate) -> float:
    return min(payload.tread_outer_mm, payload.tread_center_mm, payload.tread_inner_mm)


def _latest_tire_event(db: Session, tenant_id: str, tire_id: int) -> TireEvent | None:
    return (
        db.query(TireEvent)
        .filter(TireEvent.tenant_id == tenant_id, TireEvent.tire_id == tire_id)
        .order_by(TireEvent.event_date.desc(), TireEvent.id.desc())
        .first()
    )


def _position_status(tire: Tire | None, position: VehicleTirePosition) -> str:
    if not tire:
        return "missing"
    minimum = position.min_tread_mm or tire.min_tread_mm or 3.5
    if tire.remaining_tread_mm <= minimum:
        return "critical"
    if tire.remaining_tread_mm <= minimum + 2:
        return "alert"
    return "ok"


def _inspection_guidance(tire: Tire, position: VehicleTirePosition | None, min_tread: float, pressure: float | None) -> str:
    target_pressure = (
        position.target_pressure_psi
        if position and position.target_pressure_psi is not None
        else tire.target_pressure_psi
    )
    min_allowed = (
        position.min_tread_mm
        if position and position.min_tread_mm is not None
        else tire.min_tread_mm
    ) or 3.5
    if min_tread <= min_allowed:
        return "Profundidad critica. Programar retiro o revision tecnica inmediata."
    if pressure is not None and target_pressure is not None and pressure < target_pressure:
        return "Presion por debajo del objetivo. Calibrar y revisar en la proxima inspeccion."
    if pressure is not None and target_pressure is not None and pressure > target_pressure + 10:
        return "Presion por encima del rango. Verificar calibracion y condicion de operacion."
    return "Inspeccion registrada sin alertas criticas."


def _event_payload(event: TireEvent) -> dict[str, str | int | float | bool | None]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "event_date": event.event_date.isoformat() if event.event_date else "",
        "position": event.position,
        "mileage": event.mileage,
        "pressure_psi": event.pressure_psi,
        "tread_outer_mm": event.tread_outer_mm,
        "tread_center_mm": event.tread_center_mm,
        "tread_inner_mm": event.tread_inner_mm,
        "min_tread_mm": event.min_tread_mm,
        "damage": event.damage,
        "novelty": event.novelty,
        "origin": event.origin,
        "destination": event.destination,
        "provider": event.provider,
        "cost": event.cost,
        "evidence_url": event.evidence_url,
        "justification": event.justification,
        "guidance": event.guidance,
        "created_by": event.created_by,
        "created_role": event.created_role,
        "requires_approval": event.requires_approval,
    }


def _event_evidence(event: TireEvent) -> dict[str, str | int | float | bool | None] | None:
    if not event.evidence_url:
        return None
    return {
        "source": event.event_type,
        "event_id": event.id,
        "event_date": event.event_date.isoformat() if event.event_date else "",
        "title": event.novelty or event.damage or event.guidance or "Evidencia de llanta",
        "url": event.evidence_url,
        "created_by": event.created_by,
    }


def _group_add(
    groups: dict[str, dict[str, str | int | float | None]],
    label: str,
    cost: float,
    km: float = 0,
) -> None:
    key = label or "Sin clasificar"
    if key not in groups:
        groups[key] = {"label": key, "cost": 0.0, "km": 0.0, "count": 0, "cost_per_km": None}
    groups[key]["cost"] = float(groups[key]["cost"] or 0) + cost
    groups[key]["km"] = float(groups[key]["km"] or 0) + km
    groups[key]["count"] = int(groups[key]["count"] or 0) + 1
    total_km = float(groups[key]["km"] or 0)
    groups[key]["cost_per_km"] = float(groups[key]["cost"] or 0) / total_km if total_km else None


def _group_values(groups: dict[str, dict[str, str | int | float | None]]) -> list[dict[str, str | int | float | None]]:
    return sorted(groups.values(), key=lambda item: float(item.get("cost") or 0), reverse=True)


def _create_tire_named_event(
    payload: TireMovementCreate,
    db: Session,
    user,
    event_type: str,
    status_value: str,
    approval_required: bool = True,
) -> TireEvent:
    data = payload.model_copy(update={"event_type": event_type})
    event = create_tire_movement(data, db, user)
    event.requires_approval = approval_required
    tire = db.query(Tire).filter(_scope(Tire, user), Tire.id == payload.tire_id).first() if payload.tire_id else None
    if tire:
        tire.status = status_value
        if event_type == "retread":
            tire.life_cycle = "retread"
            tire.retread_band = payload.novelty or tire.retread_band
        if event_type == "disposal":
            tire.location = payload.destination or "FBU"
    db.commit()
    db.refresh(event)
    return event


def _ensure_tire_catalog(db: Session, user, catalog_type: str, value: str) -> None:
    if not value:
        return
    normalized = _normalize_catalog_value(value)
    existing = (
        db.query(TireCatalogEntry)
        .filter(
            _scope(TireCatalogEntry, user),
            TireCatalogEntry.catalog_type == catalog_type,
            TireCatalogEntry.normalized_value == normalized,
        )
        .first()
    )
    if existing:
        return
    db.add(
        TireCatalogEntry(
            tenant_id=user["tenant_id"],
            catalog_type=catalog_type,
            value=value.strip(),
            normalized_value=normalized,
        )
    )


def _normalize_provider_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.upper().split())


def _provider_from_row(row: dict, source_sheet: str, source_row: int) -> dict[str, str | int]:
    return {
        "name": _row_text(row, "nombre", "name"),
        "contact": _row_text(row, "contacto", "contact"),
        "email": _row_text(row, "e-mail", "email", "correo"),
        "provider_type": _row_text(row, "tipo", "type"),
        "categories": _row_text(row, "categorias", "categorías", "categories"),
        "city": _row_text(row, "ciudad", "city"),
        "source_sheet": source_sheet,
        "source_row": source_row,
    }


def _find_provider_by_name(db: Session, user, provider_name: str) -> Provider | None:
    normalized = _normalize_provider_name(provider_name)
    if not normalized:
        return None
    return (
        db.query(Provider)
        .filter(
            _scope(Provider, user),
            Provider.normalized_name == normalized,
            Provider.is_active.is_(True),
        )
        .first()
    )


def _mount_sync_remaining_tread(item) -> float:
    for value in (item.lowest_tread_mm, item.remaining_tread_mm, item.effective_tread_mm):
        if value is not None:
            return float(value)
    return 0.0


def _mount_sync_event_date(item) -> date:
    return item.mount_date or item.last_tread_date or date.today()


def _ensure_dismount_sync_event(
    db: Session,
    user,
    tire: Tire,
    vehicle_id: int | None,
    position_code: str,
    reason: str,
) -> bool:
    if vehicle_id is None:
        return False
    existing = (
        db.query(TireEvent)
        .filter(
            _scope(TireEvent, user),
            TireEvent.tire_id == tire.id,
            TireEvent.vehicle_id == vehicle_id,
            TireEvent.position == position_code,
            TireEvent.event_type == "dismount_sync",
            TireEvent.novelty == reason,
        )
        .first()
    )
    if existing:
        return False
    db.add(
        TireEvent(
            tenant_id=user["tenant_id"],
            tire_id=tire.id,
            vehicle_id=vehicle_id,
            event_type="dismount_sync",
            event_date=date.today(),
            position=position_code,
            mileage=tire.mount_mileage,
            min_tread_mm=tire.remaining_tread_mm,
            provider=tire.provider,
            provider_id=tire.provider_id,
            cost=tire.initial_cost,
            novelty=reason,
            guidance="Salida generada por sincronizacion CloudFleet.",
            created_by=user["email"],
            created_role=user.get("role", "viewer"),
        )
    )
    return True


def _sync_mount_event(
    db: Session,
    user,
    vehicle: Vehicle,
    tire: Tire,
    item,
    source: str,
    batch_id: str,
) -> str:
    event_date = _mount_sync_event_date(item)
    novelty = f"Sincronizado desde {source}."
    existing = (
        db.query(TireEvent)
        .filter(
            _scope(TireEvent, user),
            TireEvent.tire_id == tire.id,
            TireEvent.vehicle_id == vehicle.id,
            TireEvent.position == item.position,
            TireEvent.event_type == "mount_sync",
            TireEvent.event_date == event_date,
            TireEvent.mileage == item.mount_mileage,
        )
        .first()
    )
    if existing:
        existing.min_tread_mm = tire.remaining_tread_mm
        existing.tread_outer_mm = tire.remaining_tread_mm
        existing.tread_center_mm = tire.remaining_tread_mm
        existing.tread_inner_mm = tire.remaining_tread_mm
        existing.provider = tire.provider
        existing.provider_id = tire.provider_id
        existing.cost = tire.initial_cost
        existing.novelty = f"{novelty} Batch {batch_id}." if batch_id else novelty
        return "updated"
    db.add(
        TireEvent(
            tenant_id=user["tenant_id"],
            tire_id=tire.id,
            vehicle_id=vehicle.id,
            event_type="mount_sync",
            event_date=event_date,
            position=item.position,
            mileage=item.mount_mileage,
            min_tread_mm=tire.remaining_tread_mm,
            tread_outer_mm=tire.remaining_tread_mm,
            tread_center_mm=tire.remaining_tread_mm,
            tread_inner_mm=tire.remaining_tread_mm,
            provider=tire.provider,
            provider_id=tire.provider_id,
            cost=tire.initial_cost,
            novelty=f"{novelty} Batch {batch_id}." if batch_id else novelty,
            guidance=f"Montaje actual confirmado en {vehicle.plate} posicion {item.position}.",
            created_by=user["email"],
            created_role=user.get("role", "viewer"),
        )
    )
    return "created"


@router.post("/vehicle-tire-mounts/sync", response_model=VehicleTireMountSyncOut)
def sync_vehicle_tire_mounts(
    payload: VehicleTireMountSyncRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "update")
    if not payload.plate:
        raise HTTPException(status_code=400, detail="La placa es obligatoria.")
    vehicle = (
        db.query(Vehicle)
        .filter(_scope(Vehicle, user), func.upper(Vehicle.plate) == payload.plate.upper())
        .first()
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehiculo {payload.plate} no existe.")

    result = VehicleTireMountSyncOut(plate=vehicle.plate, vehicle_id=vehicle.id)
    batch_id = payload.sync_batch_id or f"cloudfleet-{uuid4().hex[:10]}"
    incoming_positions: set[str] = set()

    for item in payload.mounted:
        serial = _normalize_serial(item.code)
        position_code = item.position.strip().upper()
        if not serial or not position_code:
            result.errors.append(f"Fila omitida: codigo/posicion incompleta para {payload.plate}.")
            continue
        incoming_positions.add(position_code)

        parsed = _parse_tire_label(item.tire_label)
        provider = _find_provider_by_name(db, user, item.provider)
        if provider:
            result.linked_providers += 1

        tire = _find_tire_by_serial(db, user, serial)
        if tire and tire.vehicle_id and tire.vehicle_id != vehicle.id:
            old_position = tire.position or ""
            old_position_row = (
                db.query(VehicleTirePosition)
                .filter(
                    _scope(VehicleTirePosition, user),
                    VehicleTirePosition.vehicle_id == tire.vehicle_id,
                    VehicleTirePosition.tire_id == tire.id,
                )
                .first()
            )
            if old_position_row:
                old_position = old_position_row.position_code
                old_position_row.tire_id = None
            if _ensure_dismount_sync_event(
                db,
                user,
                tire,
                tire.vehicle_id,
                old_position,
                f"Salida por reasignacion CloudFleet hacia {vehicle.plate} posicion {position_code}.",
            ):
                result.created_events += 1
            result.moved_tires += 1

        existing_position = (
            db.query(VehicleTirePosition)
            .filter(
                _scope(VehicleTirePosition, user),
                VehicleTirePosition.vehicle_id == vehicle.id,
                VehicleTirePosition.position_code == position_code,
            )
            .first()
        )
        if existing_position and existing_position.tire_id and (not tire or existing_position.tire_id != tire.id):
            previous_tire = (
                db.query(Tire)
                .filter(_scope(Tire, user), Tire.id == existing_position.tire_id)
                .first()
            )
            if previous_tire:
                if _ensure_dismount_sync_event(
                    db,
                    user,
                    previous_tire,
                    vehicle.id,
                    position_code,
                    f"Salida por reemplazo CloudFleet en {vehicle.plate} posicion {position_code}.",
                ):
                    result.created_events += 1
                previous_tire.vehicle_id = None
                previous_tire.position = "N/A"
                previous_tire.status = "warehouse"

        values = {
            "brand": parsed["brand"],
            "design": parsed["design"],
            "dimension": parsed["dimension"],
            "life_cycle": item.life_code or "VN",
            "position": position_code,
            "remaining_tread_mm": _mount_sync_remaining_tread(item),
            "vehicle_id": vehicle.id,
            "status": "mounted",
            "location": f"Montada\nVehiculo: {vehicle.plate}\nPosicion: {position_code}",
            "provider": item.provider,
            "provider_id": provider.id if provider else None,
            "original_tread_mm": item.original_tread_mm or _default_original_tread(parsed["dimension"]),
            "min_tread_mm": item.lowest_tread_mm,
            "initial_cost": item.tire_cost,
            "mount_mileage": item.mount_mileage,
            "tread_at_mount_mm": item.effective_tread_mm or item.original_tread_mm,
            "total_km_all_lives": item.km_total,
            "source_sheet": payload.source,
            "import_batch_id": batch_id,
        }
        if tire:
            tire.serial_number = serial
            for key, value in values.items():
                if value is not None or key in {"provider_id", "vehicle_id"}:
                    setattr(tire, key, value)
            result.updated_tires += 1
        else:
            tire = Tire(tenant_id=user["tenant_id"], serial_number=serial, **values)
            db.add(tire)
            db.flush()
            result.created_tires += 1

        if existing_position:
            if existing_position.tire_id != tire.id:
                result.updated_positions += 1
            existing_position.tire_id = tire.id
            existing_position.min_tread_mm = existing_position.min_tread_mm or tire.min_tread_mm
        else:
            db.add(
                VehicleTirePosition(
                    tenant_id=user["tenant_id"],
                    vehicle_id=vehicle.id,
                    position_code=position_code,
                    tire_id=tire.id,
                    min_tread_mm=tire.min_tread_mm,
                )
            )
            result.created_positions += 1

        event_state = _sync_mount_event(db, user, vehicle, tire, item, payload.source, batch_id)
        if event_state == "created":
            result.created_events += 1
        else:
            result.updated_events += 1

    if payload.clear_missing:
        current_positions = (
            db.query(VehicleTirePosition)
            .filter(_scope(VehicleTirePosition, user), VehicleTirePosition.vehicle_id == vehicle.id)
            .all()
        )
        for position in current_positions:
            if position.position_code in incoming_positions or not position.tire_id:
                continue
            tire = db.query(Tire).filter(_scope(Tire, user), Tire.id == position.tire_id).first()
            if tire:
                if _ensure_dismount_sync_event(
                    db,
                    user,
                    tire,
                    vehicle.id,
                    position.position_code,
                    f"Salida porque CloudFleet no reporta montaje activo en {vehicle.plate} posicion {position.position_code}.",
                ):
                    result.created_events += 1
                if tire.vehicle_id == vehicle.id:
                    tire.vehicle_id = None
                    tire.position = "N/A"
                    tire.status = "warehouse"
            position.tire_id = None
            result.cleared_positions += 1

    db.commit()
    _write_audit_log(
        db,
        user,
        "tires",
        "cloudfleet-sync",
        vehicle.id,
        f"{vehicle.plate}: {len(payload.mounted)} montajes, {result.created_tires} creadas, {result.updated_tires} actualizadas",
    )
    return result


@router.post("/vehicle-tire-mounts/reconcile", response_model=RelationshipReconcileOut)
def reconcile_tire_relationships(
    payload: RelationshipReconcileRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "update" if payload.apply else "read")
    result = RelationshipReconcileOut(apply=payload.apply)
    providers_by_name = {
        provider.normalized_name: provider
        for provider in db.query(Provider)
        .filter(_scope(Provider, user), Provider.is_active.is_(True))
        .all()
    }
    positions_by_vehicle_code = {
        (position.vehicle_id, position.position_code): position
        for position in db.query(VehicleTirePosition)
        .filter(_scope(VehicleTirePosition, user))
        .all()
    }
    mounted_tires = (
        db.query(Tire)
        .filter(_scope(Tire, user), Tire.status == "mounted")
        .all()
    )
    for tire in mounted_tires:
        clean_position = (tire.position or "").strip().upper()
        has_vehicle_position = tire.vehicle_id is not None and clean_position not in {"", "N/A", "NA", "-", "--"}
        if not has_vehicle_position:
            result.mounted_without_vehicle_or_position += 1
            result.warnings.append(f"Llanta {tire.serial_number} montada sin vehiculo/posicion.")
            continue
        position = positions_by_vehicle_code.get((tire.vehicle_id, tire.position))
        if not position or position.tire_id != tire.id:
            result.position_mismatches += 1
            if payload.apply:
                if position:
                    position.tire_id = tire.id
                else:
                    db.add(
                        VehicleTirePosition(
                            tenant_id=user["tenant_id"],
                            vehicle_id=tire.vehicle_id,
                            position_code=tire.position,
                            tire_id=tire.id,
                            min_tread_mm=tire.min_tread_mm,
                        )
                    )
                result.fixed_positions += 1
        provider = providers_by_name.get(_normalize_provider_name(tire.provider))
        if tire.provider and not tire.provider_id and provider:
            result.provider_text_without_provider_id += 1
            if payload.apply:
                tire.provider_id = provider.id
                result.fixed_provider_links += 1

    if payload.apply:
        db.commit()
        _write_audit_log(
            db,
            user,
            "tires",
            "relationship-reconcile",
            None,
            f"{result.fixed_positions} posiciones, {result.fixed_provider_links} proveedores",
        )
    return result


@router.get("/vehicle-tire-mounts/diagnostics", response_model=RelationshipReconcileOut)
def diagnose_tire_relationships(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return reconcile_tire_relationships(RelationshipReconcileRequest(apply=False), db, user)


# =====================================================
# Providers
# =====================================================
@router.get("/providers", response_model=list[ProviderOut])
def list_providers(
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    q: Optional[str] = Query(None),
    provider_type: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    require_module_action(user, "integrations", "read")
    query = db.query(Provider).filter(_scope(Provider, user), Provider.is_active.is_(True))
    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Provider.name).like(pattern)
            | func.lower(Provider.contact).like(pattern)
            | func.lower(Provider.email).like(pattern)
        )
    if provider_type:
        query = query.filter(func.lower(Provider.provider_type).like(f"%{provider_type.lower()}%"))
    if city:
        query = query.filter(func.lower(Provider.city).like(f"%{city.lower()}%"))
    response.headers["X-Total-Count"] = str(query.count())
    return query.order_by(Provider.name.asc()).offset(offset).limit(limit).all()


@router.post("/providers", response_model=ProviderOut, status_code=201)
def create_provider(
    payload: ProviderCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "integrations", "create")
    normalized = _normalize_provider_name(payload.name)
    existing = (
        db.query(Provider)
        .filter(_scope(Provider, user), Provider.normalized_name == normalized)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Proveedor '{payload.name}' ya existe")
    item = Provider(tenant_id=user["tenant_id"], normalized_name=normalized, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "providers", "create", item.id, item.name)
    return item


@router.put("/providers/{item_id}", response_model=ProviderOut)
def update_provider(
    item_id: int,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "integrations", "update")
    item = _get_or_404(db, Provider, item_id, user)
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(item, field, value)
    if "name" in values and values["name"]:
        item.normalized_name = _normalize_provider_name(str(values["name"]))
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "providers", "update", item.id, item.name)
    return item


@router.post("/providers/import-csv", response_model=ProviderImportResultOut)
def import_providers_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "integrations", "import")
    raw = file.file.read()
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    lines = text.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        if "Nombre" in line and "Contacto" in line and "Tipo" in line:
            header_index = index
            break
    if header_index is None:
        raise HTTPException(status_code=400, detail="No se encontro encabezado de proveedores.")

    rows = list(csv.DictReader(io.StringIO("\n".join(lines[header_index:]))))
    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    filename = getattr(file, "filename", "") or "Lista_Proveedores.csv"
    source_sheet = filename.rsplit(".", 1)[0]

    for offset, row in enumerate(rows, start=header_index + 2):
        data = _provider_from_row(row, source_sheet, offset)
        name = str(data["name"] or "").strip()
        if not name:
            skipped += 1
            continue
        normalized = _normalize_provider_name(name)
        try:
            existing = (
                db.query(Provider)
                .filter(_scope(Provider, user), Provider.normalized_name == normalized)
                .first()
            )
            if existing:
                for key, value in data.items():
                    setattr(existing, key, value)
                existing.normalized_name = normalized
                existing.is_active = True
                updated += 1
            else:
                db.add(
                    Provider(
                        tenant_id=user["tenant_id"],
                        normalized_name=normalized,
                        **data,
                    )
                )
                created += 1
        except Exception as exc:
            errors.append(f"Fila {offset}: {name}: {exc}")
            db.rollback()

    db.commit()
    _write_audit_log(db, user, "providers", "import-csv", None, f"{created} creados, {updated} actualizados")
    return ProviderImportResultOut(
        total_rows=len(rows),
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


# =====================================================
# Vehicles
# =====================================================
@router.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    q: Optional[str] = Query(None),
    status_f: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    require_module_action(user, "vehicles", "read")
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
    response.headers["X-Total-Count"] = str(query.count())
    return query.order_by(Vehicle.id.desc()).offset(offset).limit(limit).all()



@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(
    payload: VehicleCreate, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "vehicles", "create")
    # Unicidad de placa por tenant
    existing = db.query(Vehicle).filter(
        Vehicle.tenant_id == user["tenant_id"],
        Vehicle.plate == payload.plate.strip().upper(),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Vehiculo con placa '{payload.plate}' ya existe")
    item = Vehicle(tenant_id=user["tenant_id"], **payload.model_dump())
    item.plate = item.plate.strip().upper()
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "vehicles", "create", item.id, item.plate)
    return item


@router.post("/vehicles/admin/purge", status_code=200)
def purge_all_vehicles(
    db: Session = Depends(get_db), user=Depends(get_current_user)
):
    """Admin-only: borra TODOS los vehiculos con cascade (eventos + llantas)."""
    require_module_action(user, "vehicles", "delete")
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Solo administradores")
    tenant_id = user["tenant_id"]
    vids = [v.id for v in db.query(Vehicle.id).filter(Vehicle.tenant_id == tenant_id).all()]
    if not vids:
        return {"deleted": 0, "message": "No hay vehiculos"}
    db.query(TireEvent).filter(TireEvent.vehicle_id.in_(vids)).delete(synchronize_session=False)
    db.query(Tire).filter(Tire.vehicle_id.in_(vids)).delete(synchronize_session=False)
    db.query(Vehicle).filter(Vehicle.id.in_(vids)).delete(synchronize_session=False)
    db.commit()
    return {"deleted": len(vids), "message": f"{len(vids)} vehiculos eliminados"}


@router.get("/vehicles/search", response_model=list[VehicleOut])
def search_vehicles_by_plate(
    q: str = Query(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Autocomplete de vehiculo por placa para VehicleTireView."""
    require_module_action(user, "vehicles", "read")
    query = db.query(Vehicle).filter(_scope(Vehicle, user))
    if q and len(q) >= 1:
        pattern = f"%{q.upper()}%"
        query = query.filter(func.upper(Vehicle.plate).like(pattern))
    return query.order_by(Vehicle.plate).limit(20).all()


@router.get("/vehicles/{item_id}", response_model=VehicleOut)
def get_vehicle(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "vehicles", "read")
    return _get_or_404(db, Vehicle, item_id, user)


@router.put("/vehicles/{item_id}", response_model=VehicleOut)
def update_vehicle(
    item_id: int,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "vehicles", "update")
    item = _get_or_404(db, Vehicle, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "vehicles", "update", item.id, item.plate)
    return item


@router.delete("/vehicles/{item_id}", status_code=204)
def delete_vehicle(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "vehicles", "delete")
    item = _get_or_404(db, Vehicle, item_id, user)
    details = item.plate
    # â”€â”€ Full cascade delete (6 FK tables) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # 1. VehicleTirePosition
    db.query(VehicleTirePosition).filter(VehicleTirePosition.vehicle_id == item_id).delete(synchronize_session=False)
    # 2. TireEvent â€” direct vehicle_id reference
    db.query(TireEvent).filter(TireEvent.vehicle_id == item_id).delete(synchronize_session=False)
    # 3. TireEvent â€” via tire (tire_id of tires belonging to this vehicle)
    tire_ids = [t.id for t in db.query(Tire.id).filter(Tire.vehicle_id == item_id).all()]
    if tire_ids:
        db.query(TireEvent).filter(TireEvent.tire_id.in_(tire_ids)).delete(synchronize_session=False)
    # 4. Tire
    db.query(Tire).filter(Tire.vehicle_id == item_id).delete(synchronize_session=False)
    # 5. FuelLog
    db.query(FuelLog).filter(FuelLog.vehicle_id == item_id).delete(synchronize_session=False)
    # 6. Document
    db.query(Document).filter(Document.vehicle_id == item_id).delete(synchronize_session=False)
    # 7. MaintenanceOrder
    db.query(MaintenanceOrder).filter(MaintenanceOrder.vehicle_id == item_id).delete(synchronize_session=False)
    # 8. Delete vehicle
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "vehicles", "delete", item_id, details)
    return None





# â”€â”€ Vehicle CSV import â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import io as _io
import csv as _csv
import unicodedata as _unicodedata
from fastapi import UploadFile, File
from pydantic import BaseModel as _BaseModel

class VehicleImportResult(_BaseModel):
    created: int
    updated: int = 0
    skipped: int
    errors: list[str]


@router.post("/vehicles/import-csv", response_model=VehicleImportResult)
def import_vehicles_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Importa vehÃ­culos desde un CSV con columnas:
    VehÃ­culo, Tipo, Marca/LÃ­nea, Conductor, Capacidad, Ciudad,
    Centro de Costos, Grupo primario, Grupo secundario, Tolerancia
    """
    require_module_action(user, "vehicles", "create")
    tenant_id = user["tenant_id"]

    raw = file.file.read().decode("utf-8-sig", errors="replace")
    lines = raw.splitlines()

    # Skip metadata header rows until the data header is found
    data_lines: list[str] = []
    header_found = False
    for line in lines:
        if not header_found:
            if "Tipo" in line and ("culo" in line or "cula" in line):
                header_found = True
                data_lines.append(line)
        else:
            if line.strip():
                data_lines.append(line)

    if not data_lines:
        raise HTTPException(status_code=400, detail="No se encontrÃ³ la fila de encabezado en el CSV")

    reader = _csv.DictReader(data_lines)
    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    def parse_current_km(value: str) -> float:
        digits = "".join(ch for ch in value if ch.isdigit())
        return float(digits) if digits else 0.0

    def normalize_key(value: str) -> str:
        ascii_value = _unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return ascii_value.strip().lower()

    def row_value(row: dict[str, str], *names: str) -> str:
        wanted = {normalize_key(name) for name in names}
        for key, value in row.items():
            if normalize_key(key) in wanted:
                return value.strip()
        return ""

    def row_value_containing(row: dict[str, str], *needles: str) -> str:
        wanted = [normalize_key(needle) for needle in needles]
        for key, value in row.items():
            key_norm = normalize_key(key)
            if all(needle in key_norm for needle in wanted):
                return value.strip()
        return ""

    def merge_notes(existing_notes: str, incoming_notes: str) -> str:
        order: list[str] = []
        values: dict[str, str] = {}
        for source in (existing_notes, incoming_notes):
            for item in source.split(";"):
                clean = item.strip()
                if not clean:
                    continue
                key = clean.split(":", 1)[0].strip().lower() if ":" in clean else clean.lower()
                if key not in values:
                    order.append(key)
                values[key] = clean
        return "; ".join(values[key] for key in order)

    for row in reader:
        row = {k.strip().rstrip(","): (v or "").strip() for k, v in row.items() if k}

        # Plate â€” handle encoding variants
        plate = row_value_containing(row, "vehiculo").upper()
        if not plate:
            continue

        tipo = row_value(row, "Tipo") or row_value_containing(row, "tipo", "vehiculo")

        # Marca/LÃ­nea â€” handle encoding variants
        marca_raw = row_value(row, "Marca/Linea", "Marca/LÃ­nea")

        if marca_raw:
            parts = marca_raw.split(" ", 1)
            brand = parts[0] if parts else ""
            model = parts[1] if len(parts) > 1 else tipo
        else:
            brand = row_value(row, "Marca")
            model = row_value(row, "Linea", "LÃ­nea") or tipo

        conductor = row_value(row, "Conductor", "Conductor Actual")
        ciudad    = row_value(row, "Ciudad")
        cdc       = row_value(row, "Centro de Costos")
        grupo_p   = row_value(row, "Grupo primario")
        grupo_s   = row_value(row, "Grupo secundario")
        km_actual: float | None = None
        for key, value in row.items():
            key_norm = normalize_key(key)
            if "km" in key_norm and "actual" in key_norm and value.strip():
                km_actual = parse_current_km(value)
                break

        notes = "; ".join(
            item
            for item in (
                f"Tipo: {tipo}" if tipo else "",
                f"Ciudad: {ciudad}" if ciudad else "",
                f"Grupo primario: {grupo_p}" if grupo_p else "",
                f"Grupo secundario: {grupo_s}" if grupo_s else "",
            )
            if item
        )

        try:
            existing = db.query(Vehicle).filter(
                Vehicle.plate == plate,
                Vehicle.tenant_id == tenant_id
            ).first()
            if existing:
                existing.brand = brand or existing.brand
                existing.model = model or existing.model
                if km_actual is not None:
                    existing.mileage = km_actual
                if notes:
                    existing.notes = merge_notes(existing.notes or "", notes)
                if cdc:
                    existing.cost_center = cdc
                existing.line = model or existing.line
                if conductor:
                    existing.current_driver = conductor
                updated += 1
            else:
                v = Vehicle(
                    tenant_id=tenant_id,
                    plate=plate,
                    brand=brand,
                    model=model,
                    year=2020,
                    mileage=km_actual or 0.0,
                    status="active",
                    notes=notes,
                    cost_center=cdc,
                    line=model,
                    current_driver=conductor,
                    owner="",
                )
                db.add(v)
                db.flush()
                created += 1
        except Exception as exc:
            errors.append(f"{plate}: {exc}")
            db.rollback()

    db.commit()
    return VehicleImportResult(created=created, updated=updated, skipped=skipped, errors=errors)




# =====================================================
# Tires
# =====================================================
@router.get("/tires", response_model=list[TireOut])
def list_tires(
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    vehicle_id: Optional[int] = None,
    q: Optional[str] = None,
    brand: Optional[str] = None,
    status_f: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_module_action(user, "tires", "read")
    query = db.query(Tire).filter(_scope(Tire, user))
    if vehicle_id is not None:
        query = query.filter(Tire.vehicle_id == vehicle_id)
    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Tire.serial_number).like(pattern)
            | func.lower(Tire.brand).like(pattern)
            | func.lower(Tire.design).like(pattern)
            | func.lower(Tire.dimension).like(pattern)
            | func.lower(Tire.position).like(pattern)
        )
    if brand:
        query = query.filter(func.lower(Tire.brand).like(f"%{brand.lower()}%"))
    if status_f:
        query = query.filter(Tire.status == status_f)
    response.headers["X-Total-Count"] = str(query.count())
    rows = query.order_by(Tire.id.desc()).offset(offset).limit(limit).all()
    return _attach_tire_vehicle_plates(db, user, rows)


@router.post("/tires", response_model=TireOut, status_code=201)
def create_tire(
    payload: TireCreate, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "tires", "create")
    # Check for existing serial_number within the same tenant to return 409 not 500
    existing = db.query(Tire).filter(
        Tire.tenant_id == user["tenant_id"],
        Tire.serial_number == payload.serial_number,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Tire serial '{payload.serial_number}' already exists")
    try:
        item = Tire(tenant_id=user["tenant_id"], **payload.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        _write_audit_log(db, user, "tires", "create", item.id, item.serial_number)
        return _attach_tire_vehicle_plate(db, user, item)
    except Exception as exc:
        db.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"Tire serial '{payload.serial_number}' already exists")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tires/catalogs", response_model=list[TireCatalogEntryOut])
def list_tire_catalog_entries(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    catalog_type: Optional[str] = None,
):
    require_module_action(user, "tires", "read")
    query = db.query(TireCatalogEntry).filter(_scope(TireCatalogEntry, user))
    if catalog_type:
        query = query.filter(TireCatalogEntry.catalog_type == catalog_type)
    return query.order_by(TireCatalogEntry.catalog_type.asc(), TireCatalogEntry.value.asc()).all()


@router.post("/tires/catalogs", response_model=TireCatalogEntryOut, status_code=201)
def create_tire_catalog_entry(
    payload: TireCatalogEntryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "create")
    normalized = _normalize_catalog_value(payload.value)
    existing = (
        db.query(TireCatalogEntry)
        .filter(
            _scope(TireCatalogEntry, user),
            TireCatalogEntry.catalog_type == payload.catalog_type,
            TireCatalogEntry.normalized_value == normalized,
        )
        .first()
    )
    if existing:
        return existing
    item = TireCatalogEntry(
        tenant_id=user["tenant_id"],
        catalog_type=payload.catalog_type,
        value=payload.value.strip(),
        normalized_value=normalized,
        description=payload.description,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "tires", "catalog-create", item.id, f"{payload.catalog_type}:{payload.value}")
    return item


@router.post("/tires/master/preview", response_model=TireMasterPreviewOut)
def preview_tire_master_import(
    payload: TireMasterPreviewRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "import")
    serial_counts: dict[str, int] = {}
    incomplete_count = 0
    missing_catalogs: dict[str, set[str]] = {"brand": set(), "design": set(), "dimension": set(), "site": set(), "status": set()}
    existing_catalogs: dict[str, set[str]] = {}
    for catalog_type in missing_catalogs:
        existing_catalogs[catalog_type] = {
            item.normalized_value
            for item in db.query(TireCatalogEntry)
            .filter(
                _scope(TireCatalogEntry, user),
                TireCatalogEntry.catalog_type == catalog_type,
                TireCatalogEntry.is_active.is_(True),
            )
            .all()
        }
    for row in payload.rows:
        normalized = _tire_master_values(row)
        if not all([
            normalized["serial"],
            normalized["brand"],
            normalized["design"],
            normalized["dimension"],
            normalized["plate"],
            normalized["position"],
            normalized["original_tread"],
            normalized["remaining_tread"],
        ]):
            incomplete_count += 1
            continue
        serial = str(normalized["serial"])
        serial_counts[serial] = serial_counts.get(serial, 0) + 1
        for catalog_type, raw in {
            "brand": str(normalized["brand"] or ""),
            "design": str(normalized["design"] or ""),
            "dimension": str(normalized["dimension"] or ""),
            "site": _row_text(row, "sede", "site", "zona", "tipo posicion", "tipo posicion"),
            "status": str(normalized["status_source"] or ""),
        }.items():
            if not raw:
                continue
            value = _normalize_catalog_value(raw)
            if value and value not in existing_catalogs[catalog_type]:
                missing_catalogs[catalog_type].add(value)
        original_tread = normalized["original_tread"]
        remaining_tread = normalized["remaining_tread"]
        if original_tread is not None and remaining_tread is not None and remaining_tread > original_tread:
            incomplete_count += 1
    duplicate_serials = sorted(serial for serial, count in serial_counts.items() if count > 1)
    valid_count = len(payload.rows) - incomplete_count
    clean_missing = {
        key: sorted(values)
        for key, values in missing_catalogs.items()
        if values
    }
    guidance = (
        "Carga lista para revision: crea o confirma catalogos faltantes antes de importar."
        if clean_missing or duplicate_serials or incomplete_count
        else "Carga lista para importar sin alertas."
    )
    return TireMasterPreviewOut(
        total_rows=len(payload.rows),
        valid_count=valid_count,
        incomplete_count=incomplete_count,
        duplicate_serials=duplicate_serials,
        missing_catalogs=clean_missing,
        guidance=guidance,
    )


@router.post("/tires/master/import", response_model=TireMasterImportOut)
def import_tire_master_rows(
    payload: TireMasterImportRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "import")
    batch_id = payload.import_batch_id or f"llantas-{uuid4().hex[:10]}"
    created_tires = 0
    updated_tires = 0
    created_vehicles = 0
    created_positions = 0
    created_events = 0
    skipped_rows = 0
    errors: list[str] = []
    seen_serials: set[str] = set()
    duplicate_serials: list[str] = []

    source_row_start = max(1, payload.source_row_start)
    for index, row in enumerate(payload.rows, start=source_row_start):
        normalized = _tire_master_values(row)
        serial = str(normalized["serial"] or "")
        if not serial:
            skipped_rows += 1
            errors.append(f"Fila {index}: serial obligatorio.")
            continue
        if serial in seen_serials:
            skipped_rows += 1
            duplicate_serials.append(serial)
            continue
        seen_serials.add(serial)

        brand = str(normalized["brand"] or "")
        design = str(normalized["design"] or "")
        dimension = str(normalized["dimension"] or "")
        plate = str(normalized["plate"] or "")
        position_code = str(normalized["position"] or "")
        original_tread = normalized["original_tread"]
        remaining_tread = normalized["remaining_tread"]
        if not all([brand, design, dimension, plate, position_code]) or original_tread is None or remaining_tread is None:
            skipped_rows += 1
            errors.append(f"Fila {index}: faltan campos obligatorios para LLANTAS.")
            continue
        if remaining_tread > original_tread:
            skipped_rows += 1
            errors.append(f"Fila {index}: profundidad actual mayor que profundidad original.")
            continue

        if payload.create_missing_catalogs:
            for catalog_type, value in {
                "brand": brand,
                "design": design,
                "dimension": dimension,
                "site": _row_text(row, "sede", "site", "zona", "tipo posicion", "tipo posicion"),
                "status": str(normalized["status_source"] or ""),
            }.items():
                _ensure_tire_catalog(db, user, catalog_type, value)

        vehicle = (
            db.query(Vehicle)
            .filter(_scope(Vehicle, user), Vehicle.plate == plate)
            .first()
        )
        if not vehicle:
            if not payload.create_missing_vehicles:
                skipped_rows += 1
                errors.append(f"Fila {index}: placa {plate} no existe.")
                continue
            vehicle = Vehicle(
                tenant_id=user["tenant_id"],
                plate=plate,
                brand="Pendiente",
                model="Importado maestro llantas",
                year=date.today().year,
                mileage=0,
                status="active",
                notes=f"Creado automaticamente desde {payload.source_sheet}",
            )
            db.add(vehicle)
            db.flush()
            created_vehicles += 1

        tire = _find_tire_by_serial(db, user, serial)
        event_novelty = f"Importado desde {payload.source_sheet} fila {index}. Batch {batch_id}."
        if tire:
            existing_import_event = (
                db.query(TireEvent)
                .filter(
                    _scope(TireEvent, user),
                    TireEvent.tire_id == tire.id,
                    TireEvent.event_type == "master_import",
                    TireEvent.novelty == event_novelty,
                )
                .first()
            )
            if existing_import_event:
                skipped_rows += 1
                continue
        tire_data = {
            "dot": _row_text(row, "dot", "DOT"),
            "brand": brand,
            "design": design,
            "dimension": dimension,
            "life_cycle": str(normalized["life_cycle"] or "VN"),
            "position": position_code,
            "remaining_tread_mm": remaining_tread,
            "vehicle_id": vehicle.id,
            "status": _status_from_sheet(str(normalized["status_source"] or "")),
            "location": str(normalized["location"] or ""),
            "site": _row_text(row, "sede", "site", "zona", "tipo posicion", "tipo posicion"),
            "provider": _row_text(row, "proveedor", "provider"),
            "original_tread_mm": original_tread,
            "initial_cost": _row_money(row, "valor compra", "valor de compra", "initial_cost", "costo"),
            "mount_mileage": _row_float(row, "medicion montaje", "medición montaje", "km desde montaje", "km desde", "km_desde_montaje"),
            "tread_at_mount_mm": original_tread,
            "purchase_date": _row_date(row, "fecha compra", "purchase_date"),
            "source_sheet": payload.source_sheet,
            "source_row": index,
            "import_batch_id": batch_id,
        }
        if tire:
            if not payload.update_existing:
                skipped_rows += 1
                errors.append(f"Fila {index}: serial {serial} ya existe.")
                continue
            canonical_tire = (
                db.query(Tire)
                .filter(_scope(Tire, user), Tire.serial_number == serial)
                .first()
            )
            if canonical_tire and canonical_tire.id != tire.id:
                tire = canonical_tire
            else:
                tire.serial_number = serial
            for key, value in tire_data.items():
                setattr(tire, key, value)
            updated_tires += 1
        else:
            tire = Tire(tenant_id=user["tenant_id"], serial_number=serial, **tire_data)
            db.add(tire)
            db.flush()
            created_tires += 1

        position = (
            db.query(VehicleTirePosition)
            .filter(
                _scope(VehicleTirePosition, user),
                VehicleTirePosition.vehicle_id == vehicle.id,
                VehicleTirePosition.position_code == position_code,
            )
            .first()
        )
        if position:
            position.tire_id = tire.id
            position.min_tread_mm = position.min_tread_mm or tire.min_tread_mm
        else:
            db.add(
                VehicleTirePosition(
                    tenant_id=user["tenant_id"],
                    vehicle_id=vehicle.id,
                    position_code=position_code,
                    tire_id=tire.id,
                    min_tread_mm=tire.min_tread_mm,
                )
            )
            created_positions += 1

        existing_event = (
            db.query(TireEvent)
            .filter(
                _scope(TireEvent, user),
                TireEvent.tire_id == tire.id,
                TireEvent.event_type == "master_import",
                TireEvent.novelty == event_novelty,
            )
            .first()
        )
        if not existing_event:
            db.add(
                TireEvent(
                    tenant_id=user["tenant_id"],
                    tire_id=tire.id,
                    vehicle_id=vehicle.id,
                    event_type="master_import",
                    event_date=tire.purchase_date or date.today(),
                    position=position_code,
                    mileage=_row_float(row, "medicion montaje", "medición montaje", "km desde montaje", "km desde", "km_desde_montaje"),
                    min_tread_mm=remaining_tread,
                    tread_outer_mm=remaining_tread,
                    tread_center_mm=remaining_tread,
                    tread_inner_mm=remaining_tread,
                    cost=tire.initial_cost,
                    novelty=event_novelty,
                    guidance="Registro inicial creado desde maestro de llantas.",
                    created_by=user["email"],
                    created_role=user.get("role", "viewer"),
                )
            )
            created_events += 1

    db.commit()
    _write_audit_log(db, user, "tires", "master-import", None, f"{batch_id}: {created_tires} creadas, {updated_tires} actualizadas")
    return TireMasterImportOut(
        total_rows=len(payload.rows),
        created_tires=created_tires,
        updated_tires=updated_tires,
        created_vehicles=created_vehicles,
        created_positions=created_positions,
        created_events=created_events,
        skipped_rows=skipped_rows,
        duplicate_serials=sorted(set(duplicate_serials)),
        errors=errors,
        import_batch_id=batch_id,
        guidance="Importacion aplicada. Revisa reportes, costos y hoja de vida 360 para validar resultados.",
    )


@router.post("/tires/positions", response_model=VehicleTirePositionOut, status_code=201)
def configure_vehicle_tire_position(
    payload: VehicleTirePositionCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "create")
    _get_or_404(db, Vehicle, payload.vehicle_id, user)
    tire = None
    if payload.tire_id is not None:
        tire = _get_or_404(db, Tire, payload.tire_id, user)
    existing = (
        db.query(VehicleTirePosition)
        .filter(
            _scope(VehicleTirePosition, user),
            VehicleTirePosition.vehicle_id == payload.vehicle_id,
            VehicleTirePosition.position_code == payload.position_code,
        )
        .first()
    )
    if existing:
        _apply_update(existing, payload)
        item = existing
    else:
        item = VehicleTirePosition(tenant_id=user["tenant_id"], **payload.model_dump())
        db.add(item)
    if tire:
        tire.vehicle_id = payload.vehicle_id
        tire.position = payload.position_code
    db.commit()
    db.refresh(item)
    return VehicleTirePositionOut(
        id=item.id,
        vehicle_id=item.vehicle_id,
        position_code=item.position_code,
        axle=item.axle,
        side=item.side,
        tire_id=item.tire_id,
        target_pressure_psi=item.target_pressure_psi,
        min_tread_mm=item.min_tread_mm,
        tire_serial=tire.serial_number if tire else "",
        tire_brand=tire.brand if tire else "",
        remaining_tread_mm=tire.remaining_tread_mm if tire else None,
        status=_position_status(tire, item),
    )


@router.get("/tires/vehicle-map", response_model=VehicleTireMapOut)
def get_vehicle_tire_map(
    vehicle_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "read")
    vehicle = _get_or_404(db, Vehicle, vehicle_id, user)
    positions = (
        db.query(VehicleTirePosition)
        .filter(_scope(VehicleTirePosition, user), VehicleTirePosition.vehicle_id == vehicle_id)
        .order_by(VehicleTirePosition.position_code.asc())
        .all()
    )
    tire_ids = [position.tire_id for position in positions if position.tire_id]
    tires_by_id = {
        tire.id: tire
        for tire in db.query(Tire).filter(_scope(Tire, user), Tire.id.in_(tire_ids)).all()
    } if tire_ids else {}
    tires_by_position = {
        tire.position: tire
        for tire in db.query(Tire)
        .filter(_scope(Tire, user), Tire.vehicle_id == vehicle_id)
        .all()
    }
    output = []
    for position in positions:
        tire = tires_by_id.get(position.tire_id) or tires_by_position.get(position.position_code)
        output.append(
            VehicleTirePositionOut(
                id=position.id,
                vehicle_id=position.vehicle_id,
                position_code=position.position_code,
                axle=position.axle,
                side=position.side,
                tire_id=position.tire_id,
                target_pressure_psi=position.target_pressure_psi,
                min_tread_mm=position.min_tread_mm,
                tire_serial=tire.serial_number if tire else "",
                tire_brand=tire.brand if tire else "",
                remaining_tread_mm=tire.remaining_tread_mm if tire else None,
                status=_position_status(tire, position),
            )
        )
    return VehicleTireMapOut(
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        has_missing_positions=any(item.status == "missing" for item in output),
        positions=output,
    )


@router.post("/tires/events/inspection", response_model=TireEventOut, status_code=201)
def create_tire_inspection(
    payload: TireInspectionCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "create")
    if payload.pressure_psi is not None and payload.pressure_psi <= 0:
        raise HTTPException(status_code=400, detail="La presion y las profundidades deben ser mayores que cero.")
    if payload.tread_outer_mm <= 0 or payload.tread_center_mm <= 0 or payload.tread_inner_mm <= 0:
        raise HTTPException(status_code=400, detail="La presion y las profundidades deben ser mayores que cero.")
    tire = _get_or_404(db, Tire, payload.tire_id, user)
    _get_or_404(db, Vehicle, payload.vehicle_id, user)
    min_tread = _inspection_min_tread(payload)
    previous = _latest_tire_event(db, user["tenant_id"], payload.tire_id)
    if previous and previous.min_tread_mm is not None and min_tread > previous.min_tread_mm + 0.1 and not payload.justification:
        raise HTTPException(
            status_code=400,
            detail="La profundidad no puede subir frente a la inspeccion anterior sin justificacion.",
        )
    if previous and previous.mileage is not None and payload.mileage is not None and payload.mileage < previous.mileage and not payload.justification:
        raise HTTPException(
            status_code=400,
            detail="El kilometraje no puede bajar frente al evento anterior sin justificacion.",
        )
    position = (
        db.query(VehicleTirePosition)
        .filter(
            _scope(VehicleTirePosition, user),
            VehicleTirePosition.vehicle_id == payload.vehicle_id,
            VehicleTirePosition.position_code == payload.position,
        )
        .first()
    )
    guidance = _inspection_guidance(tire, position, min_tread, payload.pressure_psi)
    event = TireEvent(
        tenant_id=user["tenant_id"],
        tire_id=payload.tire_id,
        vehicle_id=payload.vehicle_id,
        event_type="inspection",
        event_date=payload.event_date,
        position=payload.position,
        mileage=payload.mileage,
        pressure_psi=payload.pressure_psi,
        tread_outer_mm=payload.tread_outer_mm,
        tread_center_mm=payload.tread_center_mm,
        tread_inner_mm=payload.tread_inner_mm,
        min_tread_mm=min_tread,
        damage=payload.damage,
        novelty=payload.novelty,
        evidence_url=payload.evidence_url,
        justification=payload.justification,
        guidance=guidance,
        created_by=user["email"],
        created_role=user.get("role", "viewer"),
    )
    tire.remaining_tread_mm = min_tread
    tire.vehicle_id = payload.vehicle_id
    tire.position = payload.position
    db.add(event)
    db.commit()
    db.refresh(event)
    _write_audit_log(db, user, "tires", "inspection", event.id, f"{tire.serial_number}:{guidance}")
    return event


@router.post("/tires/events/movement", response_model=TireEventOut, status_code=201)
def create_tire_movement(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "create")
    tire = _get_or_404(db, Tire, payload.tire_id, user) if payload.tire_id is not None else None
    if payload.vehicle_id is not None:
        _get_or_404(db, Vehicle, payload.vehicle_id, user)
    event = TireEvent(
        tenant_id=user["tenant_id"],
        tire_id=payload.tire_id,
        vehicle_id=payload.vehicle_id,
        event_type=payload.event_type,
        event_date=payload.event_date,
        position=payload.position,
        mileage=payload.mileage,
        origin=payload.origin,
        destination=payload.destination,
        provider=payload.provider,
        cost=payload.cost,
        novelty=payload.novelty,
        evidence_url=payload.evidence_url,
        justification=payload.justification,
        guidance=f"Movimiento registrado hacia {payload.destination or 'destino no especificado'}.",
        created_by=user["email"],
        created_role=user.get("role", "viewer"),
    )
    if tire:
        if payload.vehicle_id is not None:
            tire.vehicle_id = payload.vehicle_id
        if payload.position:
            tire.position = payload.position
        if payload.destination:
            tire.location = payload.destination
            tire.status = payload.event_type
    db.add(event)
    db.commit()
    db.refresh(event)
    _write_audit_log(db, user, "tires", payload.event_type, event.id, payload.destination)
    return event


@router.post("/tires/events/mount", response_model=TireEventOut, status_code=201)
def create_tire_mount_event(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_tire_named_event(payload, db, user, "mount", "mounted", False)


@router.post("/tires/events/dismount", response_model=TireEventOut, status_code=201)
def create_tire_dismount_event(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_tire_named_event(payload, db, user, "dismount", "warehouse", False)


@router.post("/tires/events/rotation", response_model=TireEventOut, status_code=201)
def create_tire_rotation_event(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_tire_named_event(payload, db, user, "rotation", "mounted", False)


@router.post("/tires/events/retread", response_model=TireEventOut, status_code=201)
def create_tire_retread_event(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_tire_named_event(payload, db, user, "retread", "retread")


@router.post("/tires/events/warranty", response_model=TireEventOut, status_code=201)
def create_tire_warranty_event(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_tire_named_event(payload, db, user, "warranty", "warranty")


@router.post("/tires/events/disposal", response_model=TireEventOut, status_code=201)
def create_tire_disposal_event(
    payload: TireMovementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_tire_named_event(payload, db, user, "disposal", "disposal")


@router.post("/tires/events/{event_id}/approve", response_model=TireEventOut)
def approve_tire_event(
    event_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "update")
    event = _get_or_404(db, TireEvent, event_id, user)
    event.requires_approval = False
    event.approved_by = user["email"]
    db.commit()
    db.refresh(event)
    _write_audit_log(db, user, "tires", "approve-event", event.id, event.event_type)
    return event


@router.get("/tires/events", response_model=list[TireEventOut])
def list_tire_events(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    tire_id: Optional[int] = None,
    vehicle_id: Optional[int] = None,
):
    require_module_action(user, "tires", "read")
    query = db.query(TireEvent).filter(_scope(TireEvent, user))
    if tire_id is not None:
        query = query.filter(TireEvent.tire_id == tire_id)
    if vehicle_id is not None:
        query = query.filter(TireEvent.vehicle_id == vehicle_id)
    return query.order_by(TireEvent.event_date.desc(), TireEvent.id.desc()).all()


@router.get("/tires/recommendations", response_model=list[TireRecommendationOut])
def get_tire_recommendations(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    vehicle_id: Optional[int] = None,
    tire_id: Optional[int] = None,
):
    require_module_action(user, "tires", "read")
    recommendations: list[TireRecommendationOut] = []
    tire_query = db.query(Tire).filter(_scope(Tire, user))
    if vehicle_id is not None:
        tire_query = tire_query.filter(Tire.vehicle_id == vehicle_id)
    if tire_id is not None:
        tire_query = tire_query.filter(Tire.id == tire_id)
    tires = tire_query.all()
    for tire in tires:
        latest = _latest_tire_event(db, user["tenant_id"], tire.id)
        threshold = tire.min_tread_mm or 3.5
        if tire.remaining_tread_mm <= threshold or (latest and latest.damage):
            recommendations.append(TireRecommendationOut(
                action="retirar",
                severity="high",
                title="Retirar o revisar llanta",
                reason="La profundidad esta en rango critico o existe dano reportado.",
                tire_id=tire.id,
                vehicle_id=tire.vehicle_id,
                position=tire.position,
            ))
        position = (
            db.query(VehicleTirePosition)
            .filter(
                _scope(VehicleTirePosition, user),
                VehicleTirePosition.vehicle_id == tire.vehicle_id,
                VehicleTirePosition.position_code == tire.position,
            )
            .first()
        )
        target = position.target_pressure_psi if position and position.target_pressure_psi is not None else tire.target_pressure_psi
        if latest and latest.pressure_psi is not None and target is not None and latest.pressure_psi < target:
            recommendations.append(TireRecommendationOut(
                action="calibrar",
                severity="medium",
                title="Calibrar presion",
                reason="La presion registrada esta por debajo del objetivo configurado.",
                tire_id=tire.id,
                vehicle_id=tire.vehicle_id,
                position=tire.position,
            ))
    if vehicle_id is not None:
        vehicle_map = get_vehicle_tire_map(vehicle_id, db, user)
        if vehicle_map.has_missing_positions:
            recommendations.append(TireRecommendationOut(
                action="completar_mapa",
                severity="medium",
                title="Completar posiciones del vehiculo",
                reason="Hay posiciones configuradas sin llanta montada.",
                vehicle_id=vehicle_id,
            ))
    return recommendations


@router.get("/tires/costs", response_model=TireCostSummaryOut)
def get_tire_cost_summary(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "read")
    tires = db.query(Tire).filter(_scope(Tire, user)).all()
    events = db.query(TireEvent).filter(_scope(TireEvent, user)).all()
    by_tire: dict[str, dict[str, str | int | float | None]] = {}
    by_vehicle: dict[str, dict[str, str | int | float | None]] = {}
    by_provider: dict[str, dict[str, str | int | float | None]] = {}
    by_brand: dict[str, dict[str, str | int | float | None]] = {}
    by_design: dict[str, dict[str, str | int | float | None]] = {}
    by_life: dict[str, dict[str, str | int | float | None]] = {}
    tire_by_id = {tire.id: tire for tire in tires}
    total_cost = 0.0
    total_km = 0.0
    for tire in tires:
        cost = tire.initial_cost or 0
        total_cost += cost
        _group_add(by_tire, tire.serial_number, cost)
        _group_add(by_vehicle, str(tire.vehicle_id), cost)
        _group_add(by_provider, tire.provider, cost)
        _group_add(by_brand, tire.brand, cost)
        _group_add(by_design, tire.design, cost)
        _group_add(by_life, tire.life_cycle, cost)
    for event in events:
        cost = event.cost or 0
        if not cost:
            continue
        tire = tire_by_id.get(event.tire_id or 0)
        km = event.mileage or 0
        total_cost += cost
        total_km = max(total_km, km)
        _group_add(by_tire, tire.serial_number if tire else f"Evento {event.id}", cost, km)
        _group_add(by_vehicle, str(event.vehicle_id or ""), cost, km)
        _group_add(by_provider, event.provider or (tire.provider if tire else ""), cost, km)
        _group_add(by_brand, tire.brand if tire else "", cost, km)
        _group_add(by_design, tire.design if tire else "", cost, km)
        _group_add(by_life, tire.life_cycle if tire else "", cost, km)
    latest_mileage = max((event.mileage or 0 for event in events), default=0)
    total_km = max(total_km, latest_mileage)
    return TireCostSummaryOut(
        total_cost=total_cost,
        total_km=total_km,
        cost_per_km=total_cost / total_km if total_cost and total_km else None,
        by_tire=_group_values(by_tire),
        by_vehicle=_group_values(by_vehicle),
        by_provider=_group_values(by_provider),
        by_brand=_group_values(by_brand),
        by_design=_group_values(by_design),
        by_life=_group_values(by_life),
    )


@router.get("/tires/reports", response_model=TireOperationalReportsOut)
def get_tire_operational_reports(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "read")
    events = (
        db.query(TireEvent)
        .filter(_scope(TireEvent, user))
        .order_by(TireEvent.event_date.desc(), TireEvent.id.desc())
        .all()
    )
    sections = {
        "inspections": [_event_payload(event) for event in events if event.event_type == "inspection"],
        "movements": [_event_payload(event) for event in events if event.event_type in {"mount", "dismount", "rotation", "movement"}],
        "retread": [_event_payload(event) for event in events if event.event_type == "retread"],
        "warranties": [_event_payload(event) for event in events if event.event_type == "warranty"],
        "disposals": [_event_payload(event) for event in events if event.event_type == "disposal"],
        "evidence": [item for item in (_event_evidence(event) for event in events) if item is not None],
    }
    return TireOperationalReportsOut(sections=sections)


@router.get("/tires/decision-motor", response_model=TireDecisionMotorOut)
def get_tire_decision_motor(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    vehicle_id: Optional[int] = None,
):
    require_module_action(user, "tires", "read")
    recommendations = get_tire_recommendations(db, user, vehicle_id=vehicle_id)
    query = db.query(Tire).filter(_scope(Tire, user))
    if vehicle_id is not None:
        query = query.filter(Tire.vehicle_id == vehicle_id)
    tires = query.all()
    brand_rank: dict[str, dict[str, str | int | float | None]] = {}
    design_rank: dict[str, dict[str, str | int | float | None]] = {}
    provider_rank: dict[str, dict[str, str | int | float | None]] = {}
    for tire in tires:
        latest = _latest_tire_event(db, user["tenant_id"], tire.id)
        min_allowed = tire.min_tread_mm or 3.5
        _group_add(brand_rank, tire.brand, tire.initial_cost or 0, latest.mileage if latest and latest.mileage else 0)
        _group_add(design_rank, tire.design, tire.initial_cost or 0, latest.mileage if latest and latest.mileage else 0)
        _group_add(provider_rank, tire.provider, tire.initial_cost or 0, latest.mileage if latest and latest.mileage else 0)
        if tire.life_cycle != "retread" and tire.remaining_tread_mm <= min_allowed + 2 and tire.status != "disposal":
            recommendations.append(TireRecommendationOut(
                action="reencauchar",
                severity="medium",
                title="Evaluar reencauche",
                reason="La carcasa esta entrando a zona de retiro; validar daÃ±o, vida y proveedor antes de baja.",
                tire_id=tire.id,
                vehicle_id=tire.vehicle_id,
                position=tire.position,
            ))
        if latest and latest.tread_outer_mm is not None and latest.tread_center_mm is not None and latest.tread_inner_mm is not None:
            depths = [latest.tread_outer_mm, latest.tread_center_mm, latest.tread_inner_mm]
            spread = max(depths) - min(depths)
            if spread >= 2.5:
                recommendations.append(TireRecommendationOut(
                    action="rotar",
                    severity="medium",
                    title="Rotar por desgaste desigual",
                    reason="Las tres mediciones muestran diferencia alta entre hombros y centro.",
                    tire_id=tire.id,
                    vehicle_id=tire.vehicle_id,
                    position=tire.position,
                ))
                recommendations.append(TireRecommendationOut(
                    action="desgaste_anormal",
                    severity="high",
                    title="Revisar desgaste anormal",
                    reason="El patrÃ³n sugiere problema mecÃ¡nico, presiÃ³n o alineaciÃ³n.",
                    tire_id=tire.id,
                    vehicle_id=tire.vehicle_id,
                    position=tire.position,
                ))
        if latest and latest.min_tread_mm is not None:
            recommendations.append(TireRecommendationOut(
                action="prediccion_vida_util",
                severity="low",
                title="Estimar vida util",
                reason=f"Profundidad actual {latest.min_tread_mm} mm; usar tendencia de inspecciones para compra y retiro.",
                tire_id=tire.id,
                vehicle_id=tire.vehicle_id,
                position=tire.position,
            ))
        if latest and ((latest.damage and latest.damage.strip()) or (latest.pressure_psi is not None and tire.target_pressure_psi is not None and latest.pressure_psi < tire.target_pressure_psi)):
            recommendations.append(TireRecommendationOut(
                action="prediccion_falla",
                severity="high",
                title="Riesgo de falla",
                reason="DaÃ±o o presiÃ³n fuera de objetivo elevan el riesgo operativo.",
                tire_id=tire.id,
                vehicle_id=tire.vehicle_id,
                position=tire.position,
            ))
    return TireDecisionMotorOut(
        recommendations=recommendations,
        rankings={
            "brands": _group_values(brand_rank),
            "designs": _group_values(design_rank),
            "providers": _group_values(provider_rank),
        },
    )


@router.get("/tires/{item_id}/life-360", response_model=TireLife360Out)
def get_tire_life_360(
    item_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "read")
    tire = _get_or_404(db, Tire, item_id, user)
    vehicle = db.query(Vehicle).filter(_scope(Vehicle, user), Vehicle.id == tire.vehicle_id).first()
    position = (
        db.query(VehicleTirePosition)
        .filter(
            _scope(VehicleTirePosition, user),
            VehicleTirePosition.vehicle_id == tire.vehicle_id,
            VehicleTirePosition.position_code == tire.position,
        )
        .first()
    )
    events = (
        db.query(TireEvent)
        .filter(_scope(TireEvent, user), TireEvent.tire_id == tire.id)
        .order_by(TireEvent.event_date.desc(), TireEvent.id.desc())
        .all()
    )
    inspections = [_event_payload(event) for event in events if event.event_type == "inspection"]
    mounting_types = {"mount", "mounting", "montaje", "dismount", "desmontaje", "rotation", "rotacion", "movement"}
    maintenance_types = {"maintenance", "mantenimiento", "calibration", "calibracion", "repair", "reparacion", "rotation", "rotacion"}
    retread_types = {"retread", "reencauche", "renovacion", "renewal"}
    warranty_types = {"warranty", "garantia"}
    mounting_history = [_event_payload(event) for event in events if event.event_type in mounting_types]
    maintenance = [_event_payload(event) for event in events if event.event_type in maintenance_types]
    retread = [_event_payload(event) for event in events if event.event_type in retread_types]
    warranties = [_event_payload(event) for event in events if event.event_type in warranty_types]
    accumulated_cost = sum(event.cost or 0 for event in events) + (tire.initial_cost or 0)
    last_mileage = next((event.mileage for event in events if event.mileage is not None), None)
    cost_per_km = accumulated_cost / last_mileage if accumulated_cost and last_mileage else None
    risks = [
        recommendation.model_dump()
        for recommendation in get_tire_recommendations(db, user, tire_id=tire.id)
    ]
    evidence = [item for item in (_event_evidence(event) for event in events) if item is not None]
    status = _position_status(tire, position) if position else ("critical" if tire.remaining_tread_mm <= (tire.min_tread_mm or 3.5) else "ok")
    return TireLife360Out(
        tire_id=tire.id,
        identification={
            "serial_number": tire.serial_number,
            "dot": tire.dot,
            "brand": tire.brand,
            "design": tire.design,
            "dimension": tire.dimension,
            "life_cycle": tire.life_cycle,
            "retread_band": tire.retread_band,
            "qr": tire.serial_number,
        },
        current_state={
            "status": tire.status,
            "location": tire.location,
            "site": tire.site,
            "vehicle_id": tire.vehicle_id,
            "vehicle_plate": vehicle.plate if vehicle else "",
            "position": tire.position,
            "visual_status": status,
            "remaining_tread_mm": tire.remaining_tread_mm,
            "target_pressure_psi": position.target_pressure_psi if position and position.target_pressure_psi is not None else tire.target_pressure_psi,
            "min_tread_mm": position.min_tread_mm if position and position.min_tread_mm is not None else tire.min_tread_mm,
            "is_fit": status in {"ok", "alert"},
        },
        mounting_history=mounting_history,
        inspections=inspections,
        maintenance=maintenance,
        retread=retread,
        warranties=warranties,
        costs={
            "purchase_cost": tire.initial_cost,
            "accumulated_cost": accumulated_cost,
            "cost_per_km": cost_per_km,
            "last_mileage": last_mileage,
        },
        risks=risks,
        evidence=evidence,
    )


@router.get("/tires/{item_id}", response_model=TireOut)
def get_tire(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "tires", "read")
    return _attach_tire_vehicle_plate(db, user, _get_or_404(db, Tire, item_id, user))


@router.put("/tires/{item_id}", response_model=TireOut)
def update_tire(
    item_id: int,
    payload: TireUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "tires", "update")
    item = _get_or_404(db, Tire, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "tires", "update", item.id, item.serial_number)
    return _attach_tire_vehicle_plate(db, user, item)


@router.delete("/tires/{item_id}", status_code=204)
def delete_tire(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "tires", "delete")
    item = _get_or_404(db, Tire, item_id, user)
    details = item.serial_number
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "tires", "delete", item_id, details)
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
    require_module_action(user, "retired-tires", "import")
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
    require_module_action(user, "retired-tires", "read")
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
    require_module_action(user, "retired-tires", "read")
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
    require_module_action(user, "retired-tire-conditions", "read")
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
    require_module_action(user, "tire-brand-designs", "read")
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
    require_module_action(user, "operation-companies", "read")
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
    require_module_action(user, "fuel-logs", "read")
    query = db.query(FuelLog).filter(_scope(FuelLog, user))
    if vehicle_id is not None:
        query = query.filter(FuelLog.vehicle_id == vehicle_id)
    return query.order_by(FuelLog.id.desc()).all()


@router.post("/fuel-logs", response_model=FuelLogOut, status_code=201)
def create_fuel_log(
    payload: FuelLogCreate, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "fuel-logs", "create")
    item = FuelLog(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "fuel-logs", "create", item.id, f"vehicle {item.vehicle_id}")
    return item


@router.get("/fuel-logs/{item_id}", response_model=FuelLogOut)
def get_fuel_log(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "fuel-logs", "read")
    return _get_or_404(db, FuelLog, item_id, user)


@router.put("/fuel-logs/{item_id}", response_model=FuelLogOut)
def update_fuel_log(
    item_id: int,
    payload: FuelLogUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "fuel-logs", "update")
    item = _get_or_404(db, FuelLog, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "fuel-logs", "update", item.id, f"vehicle {item.vehicle_id}")
    return item


@router.delete("/fuel-logs/{item_id}", status_code=204)
def delete_fuel_log(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "fuel-logs", "delete")
    item = _get_or_404(db, FuelLog, item_id, user)
    details = f"vehicle {item.vehicle_id}"
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "fuel-logs", "delete", item_id, details)
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
    require_module_action(user, "inventory", "read")
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
    require_module_action(user, "inventory", "create")
    item = InventoryItem(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "inventory", "create", item.id, item.sku)
    return item


@router.get("/inventory/{item_id}", response_model=InventoryItemOut)
def get_inventory(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "inventory", "read")
    return _get_or_404(db, InventoryItem, item_id, user)


@router.put("/inventory/{item_id}", response_model=InventoryItemOut)
def update_inventory(
    item_id: int,
    payload: InventoryItemUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "inventory", "update")
    item = _get_or_404(db, InventoryItem, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "inventory", "update", item.id, item.sku)
    return item


@router.delete("/inventory/{item_id}", status_code=204)
def delete_inventory(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "inventory", "delete")
    item = _get_or_404(db, InventoryItem, item_id, user)
    details = item.sku
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "inventory", "delete", item_id, details)
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
    require_module_action(user, "documents", "read")
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
    require_module_action(user, "documents", "create")
    item = Document(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "documents", "create", item.id, item.doc_type)
    return item


@router.get("/documents/{item_id}", response_model=DocumentOut)
def get_document(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "documents", "read")
    return _get_or_404(db, Document, item_id, user)


@router.put("/documents/{item_id}", response_model=DocumentOut)
def update_document(
    item_id: int,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "documents", "update")
    item = _get_or_404(db, Document, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "documents", "update", item.id, item.doc_type)
    return item


@router.delete("/documents/{item_id}", status_code=204)
def delete_document(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "documents", "delete")
    item = _get_or_404(db, Document, item_id, user)
    details = item.doc_type
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "documents", "delete", item_id, details)
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
    require_module_action(user, "maintenance", "read")
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
    require_module_action(user, "maintenance", "create")
    item = MaintenanceOrder(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "maintenance", "create", item.id, item.title)
    return item


@router.get("/maintenance/{item_id}", response_model=MaintenanceOrderOut)
def get_maintenance(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "maintenance", "read")
    return _get_or_404(db, MaintenanceOrder, item_id, user)


@router.put("/maintenance/{item_id}", response_model=MaintenanceOrderOut)
def update_maintenance(
    item_id: int,
    payload: MaintenanceOrderUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "maintenance", "update")
    item = _get_or_404(db, MaintenanceOrder, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "maintenance", "update", item.id, item.title)
    return item


@router.delete("/maintenance/{item_id}", status_code=204)
def delete_maintenance(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "maintenance", "delete")
    item = _get_or_404(db, MaintenanceOrder, item_id, user)
    details = item.title
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "maintenance", "delete", item_id, details)
    return None


# =====================================================
# Client portal
# =====================================================
@router.get("/portal", response_model=list[ClientPortalRecordOut])
def list_portal(
    db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "portal", "read")
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
    require_module_action(user, "portal", "create")
    item = ClientPortalRecord(tenant_id=user["tenant_id"], **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "portal", "create", item.id, item.title)
    return item


@router.get("/portal/{item_id}", response_model=ClientPortalRecordOut)
def get_portal(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "portal", "read")
    return _get_or_404(db, ClientPortalRecord, item_id, user)


@router.put("/portal/{item_id}", response_model=ClientPortalRecordOut)
def update_portal(
    item_id: int,
    payload: ClientPortalRecordUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "portal", "update")
    item = _get_or_404(db, ClientPortalRecord, item_id, user)
    _apply_update(item, payload)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "portal", "update", item.id, item.title)
    return item


@router.delete("/portal/{item_id}", status_code=204)
def delete_portal(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "portal", "delete")
    item = _get_or_404(db, ClientPortalRecord, item_id, user)
    details = item.title
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "portal", "delete", item_id, details)
    return None


# =====================================================
# Requirements
# =====================================================
@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "requirements", "read")
    query = db.query(Requirement).filter(_scope(Requirement, user))
    if status_filter:
        query = query.filter(Requirement.status == status_filter)
    return query.order_by(Requirement.created_at.desc(), Requirement.id.desc()).all()


@router.post("/requirements", response_model=RequirementOut, status_code=201)
def create_requirement(
    payload: RequirementCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "requirements", "create")
    item = Requirement(
        tenant_id=user["tenant_id"],
        title=payload.title.strip(),
        description=payload.description,
        requester=payload.requester,
        images=payload.images,
        created_by=user.get("email", ""),
        updated_by=user.get("email", ""),
    )
    _normalize_requirement_state(item)
    db.add(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "requirements", "create", item.id, item.title)
    db.commit()
    db.refresh(item)
    return item


@router.get("/requirements/{item_id}", response_model=RequirementOut)
def get_requirement(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "requirements", "read")
    return _get_or_404(db, Requirement, item_id, user)


@router.put("/requirements/{item_id}", response_model=RequirementOut)
def update_requirement(
    item_id: int,
    payload: RequirementUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "requirements", "update")
    item = _get_or_404(db, Requirement, item_id, user)
    updates = payload.model_dump(exclude_unset=True)
    status_value = updates.pop("status", None)
    for field, value in updates.items():
        if field == "title" and isinstance(value, str):
            value = value.strip()
        setattr(item, field, value)
    if status_value:
        if status_value == "approved":
            item.team_done = True
            item.client_ok = True
        elif status_value == "completed":
            item.team_done = True
            item.client_ok = False
        elif status_value == "pending":
            item.team_done = False
            item.client_ok = False
    item.updated_by = user.get("email", "")
    _normalize_requirement_state(item)
    db.commit()
    db.refresh(item)
    _write_audit_log(db, user, "requirements", "update", item.id, item.title)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/requirements/{item_id}", status_code=204)
def delete_requirement(
    item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    require_module_action(user, "requirements", "delete")
    item = _get_or_404(db, Requirement, item_id, user)
    details = item.title
    db.delete(item)
    db.commit()
    _write_audit_log(db, user, "requirements", "delete", item_id, details)
    db.commit()
    return None


# =====================================================
# Dashboard + alerts
# =====================================================
TIRE_CRITICAL_MM = 3.0
DOC_EXPIRING_WINDOW_DAYS = 30


@router.get("/dashboard", response_model=DashboardKpiOut)
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_module_action(user, "dashboard", "read")
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
    require_module_action(user, "alerts", "read")
    return get_fleet_alerts(db, user["tenant_id"], role=user.get("role", "viewer"))


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    require_module_action(user, "audit-logs", "read")
    return (
        db.query(AuditLog)
        .filter(_scope(AuditLog, user))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )


# =====================================================
# VehicleTireView â€” endpoints
# =====================================================
import csv
import io


def _life_code(life_cycle: str) -> str:
    mapping = {"new": "VN", "retread": "R1", "retread2": "R2", "retread3": "R3"}
    return mapping.get(life_cycle, "VN")


def _calc_status_color(tire: Tire, min_tread_global: float = 3.5) -> str:
    min_t = tire.min_tread_mm or min_tread_global
    if tire.remaining_tread_mm <= min_t:
        return "critical"
    if tire.remaining_tread_mm <= min_t * 1.5:
        return "alert"
    return "ok"


def _calc_pressure_status(tire: Tire, last_pressure: float | None) -> str:
    if not tire.target_pressure_psi or last_pressure is None:
        return "unknown"
    diff_pct = abs(last_pressure - tire.target_pressure_psi) / tire.target_pressure_psi
    if diff_pct > 0.10:
        return "low" if last_pressure < tire.target_pressure_psi else "high"
    return "ok"


def _build_tire_row(db: Session, user, vehicle: Vehicle, tire: Tire) -> dict:
    tenant_id = user["tenant_id"]
    today = date.today()

    mount_event = (
        db.query(TireEvent)
        .filter(
            TireEvent.tenant_id == tenant_id,
            TireEvent.tire_id == tire.id,
            TireEvent.event_type == "mount",
        )
        .order_by(TireEvent.event_date.desc(), TireEvent.id.desc())
        .first()
    )
    if not mount_event:
        mount_event = (
            db.query(TireEvent)
            .filter(
                TireEvent.tenant_id == tenant_id,
                TireEvent.tire_id == tire.id,
                TireEvent.event_type == "master_import",
                TireEvent.mileage.isnot(None),
            )
            .order_by(TireEvent.event_date.asc(), TireEvent.id.asc())
            .first()
        )

    last_inspection = (
        db.query(TireEvent)
        .filter(
            TireEvent.tenant_id == tenant_id,
            TireEvent.tire_id == tire.id,
            TireEvent.min_tread_mm.isnot(None),
        )
        .order_by(TireEvent.event_date.desc(), TireEvent.id.desc())
        .first()
    )

    mount_km = tire.mount_mileage or (mount_event.mileage if mount_event else None)
    km_in_vehicle = None
    if mount_km is not None and vehicle.mileage:
        km_in_vehicle = max(0.0, vehicle.mileage - mount_km)

    days_since = None
    if last_inspection and last_inspection.event_date:
        days_since = (today - last_inspection.event_date).days

    tread_at_mount = tire.tread_at_mount_mm or tire.original_tread_mm
    tread_worn = None
    tread_wear_pct = None
    if tread_at_mount is not None:
        tread_worn = round(tread_at_mount - tire.remaining_tread_mm, 2)
        if tread_at_mount > 0:
            tread_wear_pct = round((tread_worn / tread_at_mount) * 100, 1)

    last_pressure = last_inspection.pressure_psi if last_inspection else None
    status_color = _calc_status_color(tire)
    pressure_status = _calc_pressure_status(tire, last_pressure)
    last_tread_date = last_inspection.event_date if last_inspection else None
    last_tread_km = last_inspection.mileage if last_inspection else None

    mount_date = None
    if mount_event:
        mount_date = mount_event.event_date
    elif tire.purchase_date:
        mount_date = tire.purchase_date

    label = " ".join(filter(None, [tire.brand, tire.design, tire.dimension]))

    return {
        "id": tire.id,
        "position": tire.position,
        "code": tire.serial_number,
        "tire_label": label,
        "brand": tire.brand,
        "design": tire.design,
        "dimension": tire.dimension,
        "life_code": _life_code(tire.life_cycle),
        "mount_date": mount_date,
        "mount_mileage": mount_km,
        "last_tread_date": last_tread_date,
        "last_tread_km": last_tread_km,
        "km_total": tire.total_km_all_lives,
        "km_in_vehicle": km_in_vehicle,
        "tire_cost": tire.initial_cost,
        "remaining_tread_mm": tire.remaining_tread_mm,
        "original_tread_mm": tire.original_tread_mm,
        "tread_at_mount_mm": tire.tread_at_mount_mm,
        "tread_worn_mm": tread_worn,
        "tread_wear_pct": tread_wear_pct,
        "target_pressure_psi": tire.target_pressure_psi,
        "last_pressure_psi": last_pressure,
        "pressure_status": pressure_status,
        "status_color": status_color,
        "serial_number": tire.serial_number,
        "dot": tire.dot,
        "retread_band": tire.retread_band,
        "provider": tire.provider,
        "status": tire.status,
        "location": tire.location,
        "days_since_inspection": days_since,
        "life_cycle": tire.life_cycle,
    }


@router.get("/vehicles/{vehicle_id}/info", response_model=VehicleInfoOut)
def get_vehicle_info(
    vehicle_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Ficha extendida del vehÃ­culo para VehicleTireView."""
    require_module_action(user, "vehicles", "read")
    return _get_or_404(db, Vehicle, vehicle_id, user)


@router.get("/vehicles/{vehicle_id}/tire-detail", response_model=list[VehicleTireRowOut])
def get_vehicle_tire_detail(
    vehicle_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Llantas del vehÃ­culo con 11 columnas enriquecidas + semÃ¡foro."""
    require_module_action(user, "tires", "read")
    vehicle = _get_or_404(db, Vehicle, vehicle_id, user)
    tires = (
        db.query(Tire)
        .filter(_scope(Tire, user), Tire.vehicle_id == vehicle_id, Tire.status == "mounted")
        .order_by(Tire.position)
        .all()
    )
    rows = [_build_tire_row(db, user, vehicle, tire) for tire in tires]
    return [VehicleTireRowOut(**row) for row in rows]


@router.get("/vehicles/{vehicle_id}/tire-events", response_model=list[VehicleEventItemOut])
def get_vehicle_tire_events(
    vehicle_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Timeline de eventos de todas las llantas del vehÃ­culo."""
    require_module_action(user, "tires", "read")
    _get_or_404(db, Vehicle, vehicle_id, user)
    offset = (page - 1) * page_size
    events = (
        db.query(TireEvent)
        .filter(_scope(TireEvent, user), TireEvent.vehicle_id == vehicle_id)
        .order_by(TireEvent.event_date.desc(), TireEvent.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    result = []
    for event in events:
        tire = db.query(Tire).filter(Tire.id == event.tire_id).first() if event.tire_id else None
        tire_serial = tire.serial_number if tire else ""
        result.append(VehicleEventItemOut(
            id=event.id,
            event_type=event.event_type,
            event_date=event.event_date,
            position=event.position or "",
            tire_serial=tire_serial,
            mileage=event.mileage,
            pressure_psi=event.pressure_psi,
            min_tread_mm=event.min_tread_mm,
            tread_outer_mm=event.tread_outer_mm,
            tread_center_mm=event.tread_center_mm,
            tread_center_outer_mm=getattr(event, "tread_center_outer_mm", None),
            tread_inner_mm=event.tread_inner_mm,
            damage=event.damage or "",
            novelty=event.novelty or "",
            guidance=event.guidance or "",
            created_by=event.created_by or "",
            requires_approval=event.requires_approval,
            approved_by=event.approved_by or "",
            destination=event.destination or "",
            provider=event.provider or "",
            cost=event.cost,
            obs_tread=getattr(event, "obs_tread", "") or "",
            obs_pressure=getattr(event, "obs_pressure", "") or "",
        ))
    return result


@router.post("/vehicles/{vehicle_id}/mount-tire", response_model=TireEventOut)
def mount_tire_to_vehicle(
    vehicle_id: int,
    payload: MountTirePayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Montar una llanta en una posiciÃ³n del vehÃ­culo."""
    require_module_action(user, "tires", "update")
    vehicle = _get_or_404(db, Vehicle, vehicle_id, user)
    if not payload.tire_id:
        raise HTTPException(status_code=400, detail="tire_id requerido para montaje.")
    tire = _get_or_404(db, Tire, payload.tire_id, user)
    tire.vehicle_id = vehicle_id
    tire.position = payload.position
    tire.status = "mounted"
    if payload.mount_mileage is not None:
        tire.mount_mileage = payload.mount_mileage
    if payload.tread_at_mount_mm is not None:
        tire.tread_at_mount_mm = payload.tread_at_mount_mm
    position_obj = (
        db.query(VehicleTirePosition)
        .filter(
            _scope(VehicleTirePosition, user),
            VehicleTirePosition.vehicle_id == vehicle_id,
            VehicleTirePosition.position_code == payload.position,
        )
        .first()
    )
    if position_obj:
        position_obj.tire_id = tire.id
    else:
        db.add(VehicleTirePosition(
            tenant_id=user["tenant_id"],
            vehicle_id=vehicle_id,
            position_code=payload.position,
            tire_id=tire.id,
        ))
    event = TireEvent(
        tenant_id=user["tenant_id"],
        tire_id=tire.id,
        vehicle_id=vehicle_id,
        event_type="mount",
        event_date=payload.mount_date,
        position=payload.position,
        mileage=payload.mount_mileage,
        provider=payload.provider,
        cost=payload.cost,
        novelty=payload.observation,
        guidance=f"Montaje en posiciÃ³n {payload.position}.",
        created_by=user["email"],
        created_role=user.get("role", ""),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    _write_audit_log(db, user, "tires", "mount", tire.id, f"{tire.serial_number} -> {vehicle.plate} pos {payload.position}")
    return TireEventOut(**_event_payload(event))


@router.post("/vehicles/{vehicle_id}/dismount-batch", response_model=DismountBatchResult)
def dismount_batch(
    vehicle_id: int,
    payload: DismountBatchPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Desmontaje masivo de N llantas con profundidades y destino."""
    require_module_action(user, "tires", "update")
    vehicle = _get_or_404(db, Vehicle, vehicle_id, user)
    if not payload.tires:
        raise HTTPException(status_code=400, detail="Selecciona al menos una llanta.")
    created = 0
    for item in payload.tires:
        tire = db.query(Tire).filter(_scope(Tire, user), Tire.id == item.tire_id).first()
        if not tire or tire.vehicle_id != vehicle_id:
            continue
        treads = [v for v in [
            item.tread_inner_mm, item.tread_center_mm,
            item.tread_center_outer_mm, item.tread_outer_mm
        ] if v is not None]
        min_tread = min(treads) if treads else tire.remaining_tread_mm
        mount_km = tire.mount_mileage
        if mount_km is not None and payload.dismount_mileage is not None:
            km_this_stint = max(0.0, payload.dismount_mileage - mount_km)
            tire.total_km_all_lives = (tire.total_km_all_lives or 0) + km_this_stint
        dest = item.destination or "warehouse"
        if dest in ("disposal", "FBU", "baja"):
            tire.status = "disposal"
            tire.location = "FBU"
        elif dest in ("retread", "reencauche"):
            tire.status = "retread"
        else:
            tire.status = "warehouse"
        tire.remaining_tread_mm = min_tread
        tire.vehicle_id = None
        position_obj = (
            db.query(VehicleTirePosition)
            .filter(
                _scope(VehicleTirePosition, user),
                VehicleTirePosition.vehicle_id == vehicle_id,
                VehicleTirePosition.tire_id == tire.id,
            )
            .first()
        )
        if position_obj:
            position_obj.tire_id = None
        event = TireEvent(
            tenant_id=user["tenant_id"],
            tire_id=tire.id,
            vehicle_id=vehicle_id,
            event_type="dismount",
            event_date=payload.dismount_date,
            position=tire.position,
            mileage=payload.dismount_mileage,
            tread_outer_mm=item.tread_outer_mm,
            tread_center_mm=item.tread_center_mm,
            tread_inner_mm=item.tread_inner_mm,
            min_tread_mm=min_tread,
            pressure_psi=item.pressure_psi,
            destination=dest,
            created_by=user["email"],
            created_role=user.get("role", ""),
            guidance=f"Desmontaje de {tire.serial_number}. Destino: {dest}.",
        )
        setattr(event, "tread_center_outer_mm", item.tread_center_outer_mm)
        setattr(event, "obs_tread", item.obs_tread)
        setattr(event, "obs_pressure", item.obs_pressure)
        db.add(event)
        created += 1
    db.commit()
    _write_audit_log(db, user, "tires", "dismount-batch", vehicle_id,
                     f"{created} llantas desmontadas de {vehicle.plate}")
    return DismountBatchResult(
        created=created,
        guidance=f"{created} llanta(s) desmontada(s) de {vehicle.plate}.",
    )


@router.get("/tires/search-inventory", response_model=list[TireOut])
def search_inventory_tires(
    location: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Buscar llantas disponibles en inventario para montar."""
    require_module_action(user, "tires", "read")
    query = db.query(Tire).filter(
        _scope(Tire, user),
        Tire.status.in_(["warehouse", "bodega", "inventario", "available"]),
    )
    if location:
        query = query.filter(func.lower(Tire.location).like(f"%{location.lower()}%"))
    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Tire.serial_number).like(pattern)
            | func.lower(Tire.brand).like(pattern)
            | func.lower(Tire.dimension).like(pattern)
        )
    return query.order_by(Tire.brand, Tire.serial_number).limit(50).all()


@router.post("/vehicles/{vehicle_id}/alignment", response_model=TireEventOut)
def create_alignment(
    vehicle_id: int,
    payload: AlignmentPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Registrar alineaciÃ³n del vehÃ­culo."""
    require_module_action(user, "tires", "create")
    _get_or_404(db, Vehicle, vehicle_id, user)
    event = TireEvent(
        tenant_id=user["tenant_id"],
        vehicle_id=vehicle_id,
        event_type="alignment",
        event_date=payload.alignment_date,
        mileage=payload.mileage,
        provider=payload.provider,
        cost=payload.cost,
        novelty=payload.observation,
        created_by=user["email"],
        created_role=user.get("role", ""),
        guidance=f"AlineaciÃ³n {payload.alignment_type} registrada.",
    )
    setattr(event, "alignment_type", payload.alignment_type)
    db.add(event)
    db.commit()
    db.refresh(event)
    _write_audit_log(db, user, "tires", "alignment", vehicle_id,
                     f"AlineaciÃ³n {payload.alignment_type}")
    return TireEventOut(**_event_payload(event))


@router.get("/vehicles/{vehicle_id}/export-tires")
def export_vehicle_tires_csv(
    vehicle_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Exportar CSV con las 11 columnas de llantas del vehÃ­culo."""
    require_module_action(user, "tires", "read")
    vehicle = _get_or_404(db, Vehicle, vehicle_id, user)
    tires = (
        db.query(Tire)
        .filter(_scope(Tire, user), Tire.vehicle_id == vehicle_id, Tire.status == "mounted")
        .order_by(Tire.position)
        .all()
    )
    rows = [_build_tire_row(db, user, vehicle, tire) for tire in tires]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Pos.", "Cod.", "Llanta", "Cod.Vida",
        "Fech.Montaje", "Medicion Montaje km",
        "Fech.Ultima Prof.", "km Ultima Prof.",
        "km Recorridos Total", "km Recorridos Vehiculo",
        "Costo Llanta", "Prof.Original mm", "Prof.Actual mm",
        "mm Gastados", "PSI Objetivo", "PSI Ultima", "Estado Semaforo"
    ])
    for row in rows:
        writer.writerow([
            row["position"], row["code"], row["tire_label"], row["life_code"],
            row["mount_date"] or "", row["mount_mileage"] or "",
            row["last_tread_date"] or "", row["last_tread_km"] or "",
            row["km_total"] or "", row["km_in_vehicle"] or "",
            row["tire_cost"] or "", row["original_tread_mm"] or "",
            row["remaining_tread_mm"], row["tread_worn_mm"] or "",
            row["target_pressure_psi"] or "", row["last_pressure_psi"] or "",
            row["status_color"]
        ])
    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="llantas_{vehicle.plate}_{date.today()}.csv"'
        },
    )
