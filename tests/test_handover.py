import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app

FORM_DATA = {
    "national_id": "32601151234567",
    "lab_number": "L20B-HAND-001",
    "patient_name": "مريض التسليم الداخلي",
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


class HandoverTestCase(unittest.TestCase):
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

    def create_form(self, **overrides):
        response = self.client.post("/api/forms", json={**FORM_DATA, **overrides})
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def add_review(self, form_id):
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

    def create_reviewed_form(self, **overrides):
        form_id = self.create_form(**overrides)
        self.add_review(form_id)
        return form_id

    def handover_rows(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            handovers = connection.execute("SELECT * FROM handovers").fetchall()
            forms = connection.execute("SELECT * FROM handover_forms").fetchall()
            return handovers, forms

    def test_page_renders_with_single_sidebar_link(self):
        page = self.client.get("/deliveries")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("التسليم للمدير", html)
        self.assertIn("تسليم الاستمارات للمدير", html)
        self.assertIn('href="/deliveries"', html)
        self.assertNotIn("الدكتورة أميرة", html)
        self.assertNotIn('href="/handover-from-amira-to-yasser"', html)
        self.assertEqual(html.count("تسليم لوزارة الصحة"), 1)
        self.assertNotIn("تسليم المحدد إلى أميرة", html)

        sidebar = self.client.get("/forms").get_data(as_text=True)
        self.assertIn('href="/deliveries"', sidebar)
        self.assertIn("التسليم للمدير", sidebar)
        self.assertNotIn("تسليم من أميرة", sidebar)
        self.assertNotIn("تسليم إلى الدكتورة أميرة", sidebar)

    def test_merged_page_has_single_recipient_field(self):
        page = self.client.get("/deliveries").get_data(as_text=True)
        self.assertEqual(page.count('id="handover-recipient"'), 1)
        self.assertIn('value="وزارة الصحة"', page)
        self.assertNotIn('name="recipient_name"', page)

    def test_old_handover_url_redirects_to_merged_page(self):
        response = self.client.get("/handover-from-amira-to-yasser")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/deliveries"))

    def test_handover_records_selected_forms(self):
        first = self.create_reviewed_form()
        second = self.create_reviewed_form(lab_number="L20B-HAND-002")

        response = self.client.post(
            "/deliveries",
            data={"form_ids": [str(first)], "notes": "تسليم أول"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/deliveries?handover=", response.headers["Location"])

        handovers, forms = self.handover_rows()
        self.assertEqual(len(handovers), 1)
        self.assertEqual(handovers[0]["form_count"], 1)
        self.assertEqual(handovers[0]["recipient_name"], "وزارة الصحة")
        self.assertEqual(handovers[0]["created_by"], "tester")
        self.assertEqual([row[1] for row in forms], [first])

        page = self.client.get("/deliveries").get_data(as_text=True)
        self.assertIn(f'value="{second}"', page)
        self.assertNotIn(f'value="{first}"', page)
        self.assertIn("تسليم أول", page)

    def test_handover_redirects_with_error_when_selection_is_missing(self):
        self.create_reviewed_form()
        response = self.client.post("/deliveries", data={})
        self.assertEqual(response.status_code, 302)
        self.assertIn("handover_error=missing", response.headers["Location"])

        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn(
            "يرجى تحديد استمارة واحدة على الأقل للتسليم إلى وزارة الصحة",
            page,
        )
        handovers, _forms = self.handover_rows()
        self.assertEqual(handovers, [])

    def test_handover_rejects_unknown_form(self):
        self.create_reviewed_form()
        response = self.client.post("/deliveries", data={"form_ids": ["9999"]})
        self.assertEqual(response.status_code, 302)
        self.assertIn("handover_error=unavailable", response.headers["Location"])
        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("لم تعد متاحة للتسليم", page)

    def test_handover_rejects_repeat_handover(self):
        form_id = self.create_reviewed_form()
        self.client.post("/deliveries", data={"form_ids": [str(form_id)]})
        response = self.client.post("/deliveries", data={"form_ids": [str(form_id)]})
        self.assertEqual(response.status_code, 302)
        self.assertIn("handover_error=unavailable", response.headers["Location"])
        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("لم تعد متاحة للتسليم", page)
        handovers, forms = self.handover_rows()
        self.assertEqual(len(handovers), 1)
        self.assertEqual(len(forms), 1)

    def test_ebi_page_no_longer_has_handover_action(self):
        self.create_reviewed_form()
        page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertIn("تسليم المحدد إلى الدكتورة أميرة", page)
        self.assertNotIn("تسليم المحدد إلى أميرة", page)
        self.assertNotIn('name="origin"', page)


if __name__ == "__main__":
    unittest.main()
