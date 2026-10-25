import tempfile
import unittest
from pathlib import Path

from app import create_app


class FormsOnlyApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.db"
        uploads = Path(self.temp_dir.name) / "uploads"
        uploads.mkdir()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(database),
                "UPLOAD_DIR": str(uploads),
                "AUTH_USERNAME": "tester",
                "AUTH_PASSWORD": "secret123",
                "SEED_DEMO": False,
            }
        )
        self.client = self.app.test_client()
        self.client.post("/api/login", json={"username": "tester", "password": "secret123"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_ok(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_root_redirects_to_forms(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forms", response.headers["Location"])

    def test_removed_children_endpoints_are_404(self):
        for path in (
            "/api/children",
            "/api/children/1",
            "/api/children/export",
            "/api/stats",
            "/api/meta",
            "/registry",
            "/dashboard",
        ):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_forms_page_renders(self):
        response = self.client.get("/forms")
        self.assertEqual(response.status_code, 200)
        self.assertIn("الاستمارات المعملية", response.get_data(as_text=True))

    def test_new_form_page_renders(self):
        response = self.client.get("/forms/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn("L20B", response.get_data(as_text=True))

    def test_empty_forms_list(self):
        response = self.client.get("/api/forms")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["summary"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
