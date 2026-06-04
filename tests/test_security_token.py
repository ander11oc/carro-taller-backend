import unittest

from app.api.deps import decode_access_token_payload
from app.core.security import create_access_token


class SecurityTokenTest(unittest.TestCase):
    def test_decodes_token_for_local_demo_email(self):
        token = create_access_token("admin@fleet.local", "tenant_local", "admin")

        payload = decode_access_token_payload(token)

        self.assertEqual(payload["sub"], "admin@fleet.local")
        self.assertEqual(payload["tenant_id"], "tenant_local")
        self.assertEqual(payload["role"], "admin")


if __name__ == "__main__":
    unittest.main()
