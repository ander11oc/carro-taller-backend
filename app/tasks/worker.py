from datetime import date, timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import Document, InventoryItem, Tire


celery_app = Celery("fleet_tasks", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.timezone = "UTC"

celery_app.conf.beat_schedule = {
    "scan-alerts-hourly": {
        "task": "app.tasks.worker.scan_alerts",
        "schedule": crontab(minute=0),
    },
}


@celery_app.task
def scan_alerts() -> dict:
    soon = date.today() + timedelta(days=30)
    db = SessionLocal()
    try:
        expiring = db.query(Document).filter(Document.expires_on <= soon).count()
        low_stock = (
            db.query(InventoryItem)
            .filter(InventoryItem.stock <= InventoryItem.min_stock)
            .count()
        )
        critical_tires = db.query(Tire).filter(Tire.remaining_tread_mm <= 3.0).count()
        return {
            "expiring_documents": expiring,
            "low_stock_items": low_stock,
            "critical_tires": critical_tires,
        }
    finally:
        db.close()


@celery_app.task
def send_expiration_alert(document_id: int) -> dict:
    return {"status": "queued", "document_id": document_id}
