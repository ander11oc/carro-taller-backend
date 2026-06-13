from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base


STRING_DEFAULTS = {
    "brand": "",
    "dot": "",
    "design": "",
    "dimension": "",
    "life_cycle": "new",
    "retread_band": "",
    "status": "mounted",
    "location": "",
    "site": "",
    "provider": "",
    "source_sheet": "",
    "import_batch_id": "",
    # Vehicle — VehicleTireView fields
    "owner": "",
    "line": "",
    "current_driver": "",
    "cost_center": "",
    # TireEvent — 4-zone tread & pressure obs
    "obs_tread": "",
    "obs_pressure": "",
    "alignment_type": "",
}

RELAX_NULLABLE_COLUMNS = {
    "tires": {"vehicle_id"},
}



def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _column_sql(engine: Engine, table_name: str, column_name: str) -> str:
    table = Base.metadata.tables[table_name]
    column = table.columns[column_name]
    compiled_type = column.type.compile(dialect=engine.dialect)
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {compiled_type}"
    if column_name in STRING_DEFAULTS:
        sql += f" DEFAULT {_sql_literal(STRING_DEFAULTS[column_name])}"
    return sql


def _backfill_sql(table_name: str, column_name: str, value: str) -> str:
    literal = _sql_literal(value)
    return f"UPDATE {table_name} SET {column_name} = {literal} WHERE {column_name} IS NULL"


def ensure_model_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                connection.execute(text(_column_sql(engine, table_name, column.name)))
                if column.name in STRING_DEFAULTS:
                    connection.execute(
                        text(_backfill_sql(table_name, column.name, STRING_DEFAULTS[column.name]))
                    )
            if engine.dialect.name == "postgresql":
                for column_name in RELAX_NULLABLE_COLUMNS.get(table_name, set()):
                    if column_name in existing_columns:
                        connection.execute(
                            text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP NOT NULL")
                        )
