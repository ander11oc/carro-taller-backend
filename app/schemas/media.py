from pydantic import BaseModel


class MediaUploadRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    entity_type: str
    entity_id: int | None = None
    evidence_type: str = "evidence"


class MediaUploadOut(BaseModel):
    asset_id: int
    upload_url: str
    public_url: str
    provider: str = "local"
