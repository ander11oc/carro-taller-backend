import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.schema_sync import ensure_model_columns
from app.models.entities import Tire


class SchemaSyncTest(unittest.TestCase):
    def test_adds_new_tire_columns_to_existing_table_without_dropping_rows(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE tires (
                        id INTEGER PRIMARY KEY,
                        tenant_id VARCHAR(80),
                        serial_number VARCHAR(120),
                        position VARCHAR(40),
                        remaining_tread_mm FLOAT,
                        brand VARCHAR(80),
                        vehicle_id INTEGER,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO tires (
                        id, tenant_id, serial_number, position, remaining_tread_mm, brand, vehicle_id
                    ) VALUES (
                        1, 'tenant_local', 'TR-OLD', 'FL', 5.5, 'Michelin', 1
                    )
                    """
                )
            )

        ensure_model_columns(engine)

        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            tire = db.query(Tire).filter(Tire.serial_number == "TR-OLD").one()
        finally:
            db.close()

        self.assertEqual(tire.dot, "")
        self.assertEqual(tire.design, "")
        self.assertEqual(tire.dimension, "")
        self.assertEqual(tire.status, "mounted")
        self.assertEqual(tire.import_batch_id, "")


if __name__ == "__main__":
    unittest.main()
