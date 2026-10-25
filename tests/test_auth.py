import tempfile
import unittest
from pathlib import Path

from app import create_app


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(root / "test.db"),
                "UPLOAD_DIR": str(root / "uploads"),
                "AUTH_USERNAME": "tester",
                "AUTH_PASSWORD": "secret123",
                "SEED_DEMO": False,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self, **overrides):
        payload = {"username": "tester", "password": "secret123", **overrides}
        return self.client.post("/login", data=payload)

    def test_login_page_renders_fields(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('name="username"', page)
        self.assertIn('name="password"', page)
        self.assertIn("تسجيل الدخول", page)

    def test_authenticated_user_skips_login_page(self):
        self.login()
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forms", response.headers["Location"])

    def test_pages_and_api_require_login(self):
        response = self.client.get("/forms")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

        api = self.client.get("/api/forms")
        self.assertEqual(api.status_code, 401)
        self.assertIn("error", api.get_json())

        root = self.client.get("/")
        self.assertEqual(root.status_code, 302)
        self.assertIn("/login", root.headers["Location"])

    def test_invalid_credentials_are_rejected(self):
        response = self.client.post(
            "/login", data={"username": "tester", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("غير صحيحة", response.get_data(as_text=True))

        api = self.client.post(
            "/api/login", json={"username": "tester", "password": "wrong"}
        )
        self.assertEqual(api.status_code, 401)
        self.assertIn("error", api.get_json())

    def test_login_success_and_logout(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forms", response.headers["Location"])
        self.assertEqual(self.client.get("/forms").status_code, 200)

        logout = self.client.post("/logout")
        self.assertEqual(logout.status_code, 302)
        self.assertIn("/login", logout.headers["Location"])
        self.assertEqual(self.client.get("/forms").status_code, 302)

    def test_api_login_redirects_to_next_and_blocks_open_redirect(self):
        response = self.client.post(
            "/api/login",
            json={
                "username": "tester",
                "password": "secret123",
                "next": "/forms/new",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["redirect"], "/forms/new")
        self.assertEqual(self.client.get("/forms/new").status_code, 200)

        self.client.post("/logout")
        unsafe = self.client.post(
            "/api/login",
            json={
                "username": "tester",
                "password": "secret123",
                "next": "//evil.example/login",
            },
        )
        self.assertEqual(unsafe.get_json()["redirect"], "/forms")

    def test_empty_credentials_are_rejected(self):
        response = self.client.post("/api/login", json={"username": "", "password": ""})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())


if __name__ == "__main__":
    unittest.main()
