import unittest

from fastapi import HTTPException

from app.api.permissions import can_access_module, require_module_action


class PermissionMatrixTest(unittest.TestCase):
    def test_admin_can_do_everything(self):
        self.assertTrue(can_access_module("admin", "vehicles", "delete"))
        self.assertTrue(can_access_module("admin", "retired-tires", "import"))

    def test_viewer_is_read_only(self):
        self.assertTrue(can_access_module("viewer", "maintenance", "read"))
        self.assertFalse(can_access_module("viewer", "maintenance", "create"))

    def test_client_is_portal_scoped(self):
        self.assertTrue(can_access_module("client", "portal", "read"))
        self.assertFalse(can_access_module("client", "vehicles", "read"))

    def test_require_module_action_raises_403(self):
        with self.assertRaises(HTTPException) as ctx:
            require_module_action({"role": "viewer"}, "vehicles", "delete")

        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
