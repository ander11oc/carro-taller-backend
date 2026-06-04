from datetime import date, timedelta
from hashlib import sha1

from sqlalchemy.orm import Session

from app.models.entities import Document, InventoryItem, MaintenanceOrder, Tire

TIRE_CRITICAL_MM = 3.0
DOC_EXPIRING_WINDOW_DAYS = 30


def build_alert_id(kind: str, entity_type: str, entity_id: int | None) -> str:
    raw = f"{kind}:{entity_type}:{entity_id or 'none'}"
    return sha1(raw.encode("utf-8")).hexdigest()[:16]


def make_alert(
    *,
    severity: str,
    kind: str,
    title: str,
    message: str,
    entity_type: str,
    entity_id: int | None = None,
    action_url: str = "",
) -> dict:
    return {
        "id": build_alert_id(kind, entity_type, entity_id),
        "severity": severity,
        "kind": kind,
        "title": title,
        "message": message,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "action_url": action_url,
        "created_at": date.today(),
        "channels": ["web"],
        "whatsapp_ready": severity == "high",
    }


def get_fleet_alerts(db: Session, tenant_id: str) -> list[dict]:
    out: list[dict] = []

    critical_tires = (
        db.query(Tire)
        .filter(Tire.tenant_id == tenant_id, Tire.remaining_tread_mm <= TIRE_CRITICAL_MM)
        .all()
    )
    for tire in critical_tires:
        out.append(
            make_alert(
                severity="high",
                kind="tire_tread",
                title="Llanta critica",
                message=f"Llanta {tire.serial_number} ({tire.position}) con {tire.remaining_tread_mm} mm - reemplazo urgente.",
                entity_id=tire.id,
                entity_type="tire",
                action_url="/fleet/tires",
            )
        )

    low_items = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.stock <= InventoryItem.min_stock,
        )
        .all()
    )
    for item in low_items:
        out.append(
            make_alert(
                severity="medium",
                kind="inventory_low",
                title="Stock bajo",
                message=f"Stock bajo en {item.sku} ({item.name}): {item.stock}/{item.min_stock}.",
                entity_id=item.id,
                entity_type="inventory",
                action_url="/fleet/inventory",
            )
        )

    soon = date.today() + timedelta(days=DOC_EXPIRING_WINDOW_DAYS)
    expiring_docs = (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id, Document.expires_on <= soon)
        .all()
    )
    for doc in expiring_docs:
        days_left = (doc.expires_on - date.today()).days
        sev = "high" if days_left <= 7 else "medium"
        out.append(
            make_alert(
                severity=sev,
                kind="document_expiring",
                title="Documento por vencer",
                message=f"Documento {doc.doc_type} del vehiculo #{doc.vehicle_id} vence en {days_left} dias.",
                entity_id=doc.id,
                entity_type="document",
                action_url="/fleet/documents",
            )
        )

    open_orders = (
        db.query(MaintenanceOrder)
        .filter(
            MaintenanceOrder.tenant_id == tenant_id,
            MaintenanceOrder.status.in_(["open", "in_progress"]),
            MaintenanceOrder.priority == "high",
        )
        .all()
    )
    for order in open_orders:
        out.append(
            make_alert(
                severity="high",
                kind="maintenance_high",
                title="Mantenimiento prioritario",
                message=f"Orden de mantenimiento prioritaria #{order.id}: {order.title}.",
                entity_id=order.id,
                entity_type="maintenance",
                action_url="/fleet/maintenance",
            )
        )

    return out
