import tempfile
import unittest
from pathlib import Path

from app import create_app


class LogosTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        logos = root / "logos"
        logos.mkdir()
        (logos / "vacsera.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
        )
        (logos / "who.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
        )
        self.logos = logos
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(root / "test.db"),
                "UPLOAD_DIR": str(root / "uploads"),
                "LOGOS_DIR": str(logos),
                "AUTH_USERNAME": "tester",
                "AUTH_PASSWORD": "secret123",
                "SEED_DEMO": False,
            }
        )
        self.client = self.app.test_client()
        self.client.post("/api/login", json={"username": "tester", "password": "secret123"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_logos_served_from_folder(self):
        response = self.client.get("/logos/vacsera.svg")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<svg", response.data)

    def test_form_page_renders_logos_from_folder(self):
        html = self.client.get("/forms/new").get_data(as_text=True)
        self.assertIn("/logos/vacsera.svg?v=", html)
        self.assertIn("/logos/who.svg?v=", html)

    def test_logo_replacement_changes_version(self):
        version_one = self.client.get("/forms/new").get_data(as_text=True)
        import os
        os.utime(self.logos / "vacsera.svg", (1, 1))
        version_two = self.client.get("/forms/new").get_data(as_text=True)
        self.assertNotEqual(version_one, version_two)

    def test_removed_logo_disappears_from_page(self):
        (self.logos / "who.svg").unlink()
        html = self.client.get("/forms/new").get_data(as_text=True)
        self.assertNotIn("/logos/who.svg", html)
        self.assertIn("/logos/vacsera.svg?v=", html)

    def test_path_traversal_blocked(self):
        response = self.client.get("/logos/..%2Fapp.py")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
