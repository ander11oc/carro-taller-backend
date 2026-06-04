import argparse

from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.retired_tire_import import import_retired_tire_workbook


def main() -> None:
    parser = argparse.ArgumentParser(description="Import retired tire workbook data.")
    parser.add_argument("workbook_path", help="Path to the .xlsx workbook")
    parser.add_argument(
        "--tenant-id",
        default=settings.DEFAULT_TENANT_ID,
        help="Tenant that will own the imported data",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = import_retired_tire_workbook(db, args.workbook_path, args.tenant_id)
    finally:
        db.close()

    print(
        "Imported retired_tires={retired_tires}, conditions={conditions}, "
        "brand_designs={brand_designs}, operation_companies={operation_companies}".format(
            **result.__dict__
        )
    )


if __name__ == "__main__":
    main()
