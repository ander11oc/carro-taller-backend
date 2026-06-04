from sqlalchemy import String, func
from sqlalchemy.orm import Session

from app.models.entities import RetiredTireRecord

MONTH_ORDER = {
    "Enero": 1,
    "Febrero": 2,
    "Marzo": 3,
    "Abril": 4,
    "Mayo": 5,
    "Junio": 6,
    "Julio": 7,
    "Agosto": 8,
    "Septiembre": 9,
    "Octubre": 10,
    "Noviembre": 11,
    "Diciembre": 12,
}


def get_retired_tire_summary(
    db: Session,
    tenant_id: str,
    q: str | None = None,
    company: str | None = None,
    brand: str | None = None,
    brands: list[str] | None = None,
    year: int | None = None,
    area: str | None = None,
    areas: list[str] | None = None,
    conditions: list[str] | None = None,
    months: list[str] | None = None,
) -> dict:
    query = _retired_tire_query(
        db=db,
        tenant_id=tenant_id,
        q=q,
        company=company,
        brand=brand,
        brands=brands,
        year=year,
        area=area,
        areas=areas,
        conditions=conditions,
        months=months,
    )
    total = query.count()
    retread_count = query.filter(RetiredTireRecord.new_or_retread == "R").count()
    new_count = query.filter(RetiredTireRecord.new_or_retread == "N").count()
    avg_casing_use = _round_float(query.with_entities(func.avg(RetiredTireRecord.casing_use)).scalar())
    avg_cpk = _round_float(query.with_entities(func.avg(RetiredTireRecord.cpk)).scalar())

    return {
        "total": total,
        "retread_count": retread_count,
        "new_count": new_count,
        "avg_casing_use": avg_casing_use,
        "avg_cpk": avg_cpk,
        "by_brand": _group_count(query, RetiredTireRecord.brand, limit=8),
        "by_area": _group_count(query, RetiredTireRecord.tire_area, limit=6),
        "by_condition": _group_count(query, RetiredTireRecord.retirement_condition, limit=8),
        "by_month": _month_count(query),
    }


def _retired_tire_query(
    db: Session,
    tenant_id: str,
    q: str | None = None,
    company: str | None = None,
    brand: str | None = None,
    brands: list[str] | None = None,
    year: int | None = None,
    area: str | None = None,
    areas: list[str] | None = None,
    conditions: list[str] | None = None,
    months: list[str] | None = None,
):
    query = db.query(RetiredTireRecord).filter(RetiredTireRecord.tenant_id == tenant_id)
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
    if brands:
        query = query.filter(RetiredTireRecord.brand.in_(brands))
    if year is not None:
        query = query.filter(RetiredTireRecord.year == year)
    if area:
        query = query.filter(RetiredTireRecord.tire_area == area)
    if areas:
        query = query.filter(RetiredTireRecord.tire_area.in_(areas))
    if conditions:
        query = query.filter(RetiredTireRecord.retirement_condition.in_(conditions))
    if months:
        month_label = func.cast(RetiredTireRecord.year, String) + " " + RetiredTireRecord.month
        query = query.filter(month_label.in_(months))
    return query


def _round_float(value) -> float:
    return round(float(value or 0), 4)


def _group_count(query, column, limit: int) -> list[dict]:
    rows = (
        query.with_entities(column, func.count(RetiredTireRecord.id))
        .filter(column != "")
        .group_by(column)
        .order_by(func.count(RetiredTireRecord.id).desc(), column.asc())
        .limit(limit)
        .all()
    )
    return [{"label": str(label), "value": int(value)} for label, value in rows]


def _month_count(query) -> list[dict]:
    rows = (
        query.with_entities(
            RetiredTireRecord.year,
            RetiredTireRecord.month,
            func.count(RetiredTireRecord.id),
        )
        .filter(
            RetiredTireRecord.year.isnot(None),
            RetiredTireRecord.month != "",
        )
        .group_by(RetiredTireRecord.year, RetiredTireRecord.month)
        .all()
    )
    ordered = sorted(
        rows,
        key=lambda row: (row[0] or 0, MONTH_ORDER.get(row[1], 99), row[1] or ""),
    )
    return [
        {"label": f"{year} {month}", "value": int(value)}
        for year, month, value in ordered
    ]
