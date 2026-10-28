import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from werkzeug.security import generate_password_hash

from app import create_app

FORM_DATA = {
    "national_id": "32601151234567",
    "lab_number": "L20B-MOH-001",
    "patient_name": "مريض وزارة الصحة",
    "age_months": "24",
    "illness_date": "2026-10-10",
    "center": "مدينة نصر",
    "governorate": "القاهرة",
    "sample_condition": "جيدة",
    "sample1_collect_date": "2026-10-11",
    "sample1_receive_date": "2026-10-12",
    "sample1_l20b": "سلبي",
    "sample1_prelim_date": "2026-10-18",
    "sample1_final": "سلبي",
    "sample1_final_date": "2026-10-21",
}


class MinistryPageTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database = root / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database),
                "UPLOAD_DIR": str(root / "uploads"),
                "REVIEWS_DIR": str(root / "reviews"),
                "DELIVERY_PDF_DIR": str(root / "deliveries"),
                "AUTH_USERNAME": "tester",
                "AUTH_PASSWORD": "secret123",
                "SEED_DEMO": False,
            }
        )
        self.client = self.app.test_client()
        self.client.post(
            "/api/login", json={"username": "tester", "password": "secret123"}
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_reviewed_form(self, **overrides):
        response = self.client.post("/api/forms", json={**FORM_DATA, **overrides})
        self.assertEqual(response.status_code, 201)
        form_id = response.get_json()["id"]
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                INSERT INTO form_reviews (
                    lab_form_id, first_reviewer_name, first_reviewed_at,
                    second_reviewer_name, second_reviewed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (form_id, "د. منى حسن", "2026-10-20T09:30", "د. محمد علي", "2026-10-21T11:15"),
            )
            connection.commit()
        return form_id

    def test_admin_sees_sidebar_link_and_page(self):
        sidebar = self.client.get("/forms").get_data(as_text=True)
        self.assertIn("وزارة الصحة", sidebar)
        self.assertIn('href="/ministry-of-health"', sidebar)

        page = self.client.get("/ministry-of-health")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("وزارة الصحة", html)
        self.assertIn("البيانات المستلمة من المدير", html)
        self.assertIn("لا توجد بيانات بعد", html)

    def test_page_shows_received_handover_details_and_afb_label(self):
        form_id = self.create_reviewed_form()

        before = self.client.get("/ministry-of-health").get_data(as_text=True)
        self.assertNotIn(f"#{form_id}", before)
        self.assertIn("لا توجد بيانات بعد", before)

        self.client.post(
            "/deliveries",
            data={"form_ids": [str(form_id)], "notes": "تسليم إلى الوزارة"},
        )

        html = self.client.get("/ministry-of-health").get_data(as_text=True)
        self.assertIn(f"#{form_id}", html)
        self.assertIn("L20B-MOH-001", html)
        self.assertIn("مريض وزارة الصحة", html)
        self.assertIn("د. منى حسن", html)
        self.assertIn("د. محمد علي", html)
        self.assertIn("تسليم إلى الوزارة", html)
        self.assertIn("وزارة الصحة", html)
        self.assertIn("AFB", html)
        self.assertNotIn("الحالات العادية", html)

    def test_page_has_pdf_download_button(self):
        html = self.client.get("/ministry-of-health").get_data(as_text=True)
        self.assertIn('href="/ministry-of-health/pdf"', html)
        self.assertIn("تحميل تقرير PDF", html)
        self.assertIn("#icon-pdf", html)

    def test_pdf_download_returns_report(self):
        form_id = self.create_reviewed_form()
        self.client.post(
            "/deliveries",
            data={"form_ids": [str(form_id)], "notes": "تسليم للتقرير"},
        )

        def fake_render(html, output_path):
            Path(output_path).write_bytes(
                b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF\n"
            )
            return "chromium"

        with mock.patch("app.render_html_to_pdf", side_effect=fake_render):
            response = self.client.get("/ministry-of-health/pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertGreater(len(response.data), 1000)
        disposition = response.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn(".pdf", disposition)

    def test_pdf_html_contains_received_details(self):
        form_id = self.create_reviewed_form()
        self.client.post(
            "/deliveries",
            data={"form_ids": [str(form_id)], "notes": "ملاحظة التقرير"},
        )

        from app import (
            fetch_handover_eligible_forms,
            fetch_handover_history,
            fetch_ministry_received_forms,
            get_db,
            ministry_stats,
            render_ministry_pdf_html,
        )

        with self.app.test_request_context("/ministry-of-health/pdf"):
            db = get_db()
            received = fetch_ministry_received_forms(db)
            html = render_ministry_pdf_html(
                received,
                fetch_handover_history(db),
                ministry_stats(db, received, fetch_handover_eligible_forms(db)),
            )

        self.assertIn("تقرير البيانات المستلمة — وزارة الصحة", html)
        self.assertIn(f"#{form_id}", html)
        self.assertIn("L20B-MOH-001", html)
        self.assertIn("مريض وزارة الصحة", html)
        self.assertIn("القاهرة", html)
        self.assertIn("د. منى حسن", html)
        self.assertIn("د. محمد علي", html)
        self.assertIn("ملاحظة التقرير", html)
        self.assertIn("ملخص الاستلام", html)
        self.assertIn("AFB", html)

    def test_ministry_user_can_download_pdf(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'moh')",
                ("ministry", generate_password_hash("StrongPass9")),
            )
            connection.commit()

        self.client.post("/logout")
        login = self.client.post(
            "/api/login",
            json={"username": "ministry", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.get_json()["redirect"], "/ministry-of-health")

        def fake_render(html, output_path):
            Path(output_path).write_bytes(
                b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF\n"
            )
            return "chromium"

        with mock.patch("app.render_html_to_pdf", side_effect=fake_render):
            response = self.client.get("/ministry-of-health/pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))

    def test_ministry_page_is_admin_only(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'user')",
                ("regular", generate_password_hash("StrongPass9")),
            )
            connection.commit()

        self.client.post("/logout")
        self.client.post(
            "/api/login", json={"username": "regular", "password": "StrongPass9"}
        )
        self.assertEqual(self.client.get("/ministry-of-health").status_code, 403)
        self.assertEqual(self.client.get("/ministry-of-health/pdf").status_code, 403)
        sidebar = self.client.get("/forms").get_data(as_text=True)
        self.assertNotIn("وزارة الصحة", sidebar)


if __name__ == "__main__":
    unittest.main()
