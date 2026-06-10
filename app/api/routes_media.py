from pathlib import PurePath
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.permissions import require_module_action
from app.db.session import get_db
from app.models.entities import MediaAsset
from app.schemas.media import MediaUploadOut, MediaUploadRequest


router = APIRouter(prefix="/media", tags=["media"])


def _safe_filename(filename: str) -> str:
    name = PurePath(filename.strip() or "evidencia.bin").name
    return name.replace(" ", "_")


@router.post("/upload-url", response_model=MediaUploadOut)
def create_media_upload_url(
    payload: MediaUploadRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require_module_action(user, "media", "create")
    filename = _safe_filename(payload.filename)
    url = f"local://media/{uuid4().hex}-{filename}"
    asset = MediaAsset(
        tenant_id=user["tenant_id"],
        url=url,
        filename=filename,
        content_type=payload.content_type,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        evidence_type=payload.evidence_type,
        uploaded_by=user.get("email", ""),
        status="pending",
        source="media_storage",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return MediaUploadOut(asset_id=asset.id, upload_url=url, public_url=url)
