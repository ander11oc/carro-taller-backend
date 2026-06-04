import unittest

from app.schemas.auth import LoginInput


class AuthSchemaTest(unittest.TestCase):
    def test_login_accepts_local_demo_email_domain(self):
        payload = LoginInput(email="admin@fleet.local", password="admin123")

        self.assertEqual(payload.email, "admin@fleet.local")


if __name__ == "__main__":
    unittest.main()
