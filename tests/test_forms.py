import base64
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is optional for the suite
    Image = None


VALID_FORM = {
    "national_id": "32601151234567",
    "lab_number": "L20B-0001",
    "patient_name": "يوسف أحمد محمود",
    "age_months": "18",
    "age_years": "1",
    "illness_date": "2026-09-28",
    "center": "مدينة نصر",
    "governorate": "القاهرة",
    "sample_condition": "جيدة",
    "sample1_collect_date": "2026-09-29",
    "sample1_receive_date": "2026-09-30",
    "sample1_l20b": "سلبي",
    "sample1_prelim_date": "2026-10-05",
    "sample1_final": "سلبي",
    "sample1_final_date": "2026-10-09",
    "sample2_collect_date": "",
    "sample2_receive_date": "",
    "sample2_l20b": "",
    "sample2_prelim_date": "",
    "sample2_final": "",
    "sample2_final_date": "",
    "signatory_name": "ك/ أميرة يحيى زغلول",
    "stamp_position": "left",
    "signature_position": "left",
    "notes": "",
    "show_stamp": True,
    "show_signature": True,
    "stamp_image": "",
    "signature_image": "",
}


def tiny_png():
    buffer = io.BytesIO()
    Image.new("RGBA", (24, 12), (13, 125, 117, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class LabFormTestCase(unittest.TestCase):
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
        self.client.post("/api/login", json={"username": "tester", "password": "secret123"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_form(self, **overrides):
        return self.client.post("/api/forms", json={**VALID_FORM, **overrides})

    def test_form_pages_render(self):
        page = self.client.get("/forms")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<th>المستخدم</th>", page.get_data(as_text=True))
        new_form = self.client.get("/forms/new")
        self.assertEqual(new_form.status_code, 200)
        new_form_html = new_form.get_data(as_text=True)
        self.assertIn('<input name="governorate" type="text"', new_form_html)
        self.assertNotIn('<select name="governorate"', new_form_html)
        self.assertNotIn('name="reviewer_name"', new_form_html)
        self.assertNotIn('name="reviewed_at"', new_form_html)
        self.assertEqual(self.client.get("/forms/9999").status_code, 404)

    def test_final_results_are_free_text_inputs(self):
        created = self.create_form(
            sample1_final="نتيجة مخصصة للعينة الأولى",
            sample2_final="إيجابي WPV3",
        )
        self.assertEqual(created.status_code, 201)
        form_id = created.get_json()["id"]

        page = self.client.get(f"/forms/{form_id}").get_data(as_text=True)
        self.assertIn('<input name="sample1_final" type="text"', page)
        self.assertIn('<input name="sample2_final" type="text"', page)
        self.assertNotIn('<select name="sample1_final"', page)
        self.assertNotIn('<select name="sample2_final"', page)
        self.assertIn("نتيجة مخصصة للعينة الأولى", page)
        self.assertIn("إيجابي WPV3", page)

    def test_create_list_filter_and_summary(self):
        response = self.create_form()
        self.assertEqual(response.status_code, 201)
        created = response.get_json()
        self.assertEqual(created["patient_name"], VALID_FORM["patient_name"])
        self.assertEqual(created["created_by"], "tester")
        self.assertTrue(created["show_stamp"])
        self.assertEqual(created["stamp_position"], "left")

        listing = self.client.get("/api/forms").get_json()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["created_by"], "tester")
        self.assertEqual(listing["summary"]["finalized"], 1)
        self.assertEqual(listing["summary"]["pending"], 0)

        filtered = self.client.get("/api/forms?result=إيجابي").get_json()
        self.assertEqual(filtered["total"], 0)

        searched = self.client.get("/api/forms?search=L20B-0001").get_json()
        self.assertEqual(searched["total"], 1)

        self.assertEqual(self.client.get(f"/forms/{created['id']}").status_code, 200)

    def test_national_id_accepts_variable_numeric_lengths(self):
        for index, national_id in enumerate(("1", "123", "1234567890123")):
            response = self.create_form(
                national_id=national_id,
                lab_number=f"L20B-NID-{index}",
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["national_id"], national_id)

        non_numeric = self.create_form(
            national_id="12A", lab_number="L20B-NID-INVALID"
        )
        self.assertEqual(non_numeric.status_code, 400)
        self.assertIn("national_id", non_numeric.get_json()["fields"])

    def test_validation_and_duplicate_lab_number(self):
        invalid = self.create_form(national_id="12A", lab_number="")
        self.assertEqual(invalid.status_code, 400)
        fields = invalid.get_json()["fields"]
        self.assertIn("national_id", fields)
        self.assertIn("lab_number", fields)

        future = self.create_form(illness_date="2099-01-01")
        self.assertEqual(future.status_code, 400)
        self.assertIn("illness_date", future.get_json()["fields"])

        self.assertEqual(self.create_form().status_code, 201)
        duplicate = self.create_form(patient_name="سجل آخر")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("lab_number", duplicate.get_json()["fields"])

    def test_update_and_delete_form(self):
        form_id = self.create_form().get_json()["id"]
        updated = self.client.put(
            f"/api/forms/{form_id}",
            json={**VALID_FORM, "patient_name": "مريض محدث", "sample1_final": "إيجابي"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["patient_name"], "مريض محدث")
        self.assertEqual(updated.get_json()["sample1_final"], "إيجابي")

        self.assertEqual(self.client.delete(f"/api/forms/{form_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/forms/{form_id}").status_code, 404)
        self.assertEqual(self.client.get("/api/forms").get_json()["total"], 0)

    def test_creator_stays_with_original_user_after_another_user_updates(self):
        form_id = self.create_form().get_json()["id"]
        self.client.post(
            "/users/new",
            data={
                "username": "lab.user",
                "password": "StrongPass9",
                "password_confirm": "StrongPass9",
                "role": "user",
            },
        )
        self.client.post("/logout")
        self.client.post(
            "/api/login", json={"username": "lab.user", "password": "StrongPass9"}
        )

        updated = self.client.put(
            f"/api/forms/{form_id}", json={**VALID_FORM, "patient_name": "مريض محدث"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["created_by"], "tester")
        self.assertEqual(
            self.client.get("/api/forms").get_json()["items"][0]["created_by"],
            "tester",
        )

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_stamp_upload_replacement_and_removal(self):
        png = tiny_png()
        created = self.create_form(stamp_image=png).get_json()
        self.assertTrue(created["stamp_image"].endswith(".png"))
        stored = Path(self.app.config["UPLOAD_DIR"]) / created["stamp_image"]
        self.assertTrue(stored.is_file())

        served = self.client.get(f"/uploads/{created['stamp_image']}")
        self.assertEqual(served.status_code, 200)
        self.assertIn("image/png", served.content_type)
        served.close()

        replaced = self.client.put(
            f"/api/forms/{created['id']}",
            json={**VALID_FORM, "stamp_image": png},
        ).get_json()
        self.assertNotEqual(replaced["stamp_image"], created["stamp_image"])
        self.assertFalse(stored.is_file())
        self.assertTrue((Path(self.app.config["UPLOAD_DIR"]) / replaced["stamp_image"]).is_file())

        cleared = self.client.put(
            f"/api/forms/{created['id']}",
            json={**VALID_FORM, "stamp_image": ""},
        ).get_json()
        self.assertEqual(cleared["stamp_image"], "")
        self.assertFalse((Path(self.app.config["UPLOAD_DIR"]) / replaced["stamp_image"]).is_file())

        deleted = self.client.delete(f"/api/forms/{created['id']}")
        self.assertEqual(deleted.status_code, 204)

    def test_upload_rejects_non_image_and_traversal(self):
        self.assertEqual(self.client.get("/uploads/..%2Fapp.py").status_code, 404)
        rejected = self.create_form(stamp_image="data:text/plain;base64,aGVsbG8=")
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("stamp_image", rejected.get_json()["fields"])

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_fixed_stamp_and_signature_images_are_loaded(self):
        root = Path(self.temp_dir.name)
        fixed_dir = root / "fixed"
        fixed_dir.mkdir()
        image_bytes = base64.b64decode(tiny_png().split(",", 1)[1])
        (fixed_dir / "stamp.png").write_bytes(image_bytes)
        (fixed_dir / "signature.png").write_bytes(image_bytes)

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(root / "fixed.db"),
                "UPLOAD_DIR": str(root / "fixed-uploads"),
                "FIXED_IMAGES_DIR": str(fixed_dir),
                "AUTH_USERNAME": "tester",
                "AUTH_PASSWORD": "secret123",
                "SEED_DEMO": False,
            }
        )
        client = app.test_client()
        client.post("/api/login", json={"username": "tester", "password": "secret123"})
        page = client.get("/forms/new").get_data(as_text=True)
        self.assertIn("/fixed/stamp.png", page)
        self.assertIn("/fixed/signature.png", page)
        self.assertEqual(client.get("/fixed/stamp.png").status_code, 200)

    def test_batch_pdf_page_merges_selected_forms(self):
        first = self.create_form().get_json()
        second = self.create_form(lab_number="L20B-0002", patient_name="مريض ثانٍ").get_json()
        third = self.create_form(lab_number="L20B-0003", patient_name="مريض ثالث").get_json()

        response = self.client.get(f"/forms/batch?ids={first['id']},{second['id']}")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertEqual(page.count('class="form-sheet"'), 2)
        self.assertIn(VALID_FORM["patient_name"], page)
        self.assertIn("مريض ثانٍ", page)
        self.assertNotIn("مريض ثالث", page)

        self.assertEqual(self.client.get("/forms/batch?ids=").status_code, 404)
        self.assertEqual(self.client.get("/forms/batch?ids=9999").status_code, 404)


class LabFormMetadataMigrationTestCase(unittest.TestCase):
    def test_existing_forms_get_blank_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "legacy.db"
            schema = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(
                encoding="utf-8"
            )
            legacy_schema = schema.replace(
                "    created_by TEXT NOT NULL DEFAULT '',\n", ""
            )

            connection = sqlite3.connect(database)
            connection.executescript(legacy_schema)
            connection.execute(
                "INSERT INTO lab_forms (lab_number, patient_name) VALUES (?, ?)",
                ("L20B-LEGACY", "استمارة قديمة"),
            )
            connection.commit()
            connection.close()

            app = create_app(
                {
                    "TESTING": True,
                    "DATABASE": str(database),
                    "UPLOAD_DIR": str(root / "uploads"),
                    "AUTH_USERNAME": "tester",
                    "AUTH_PASSWORD": "secret123",
                    "SEED_DEMO": False,
                }
            )
            client = app.test_client()
            client.post(
                "/api/login", json={"username": "tester", "password": "secret123"}
            )

            items = client.get("/api/forms").get_json()["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["lab_number"], "L20B-LEGACY")
            self.assertEqual(items[0]["created_by"], "")


if __name__ == "__main__":
    unittest.main()
