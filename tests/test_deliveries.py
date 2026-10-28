import contextlib
import io
import json
import re
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from werkzeug.security import generate_password_hash

from app import create_app

FORM_DATA = {
    "national_id": "32601151234567",
    "lab_number": "L20B-EBI-001",
    "patient_name": "مريض التسليم",
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


class FakeEbiResponse:
    def __init__(self, status=200, body=b'{"ok": true}'):
        self.status = status
        self.body = body

    def getcode(self):
        return self.status

    def read(self, _limit=None):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class EbiDeliveryTestCase(unittest.TestCase):
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
                "EBI_API_URL": "http://ebi.test/api/forms",
                "EBI_API_TOKEN": "secret-token",
                "EBI_API_TIMEOUT": "5",
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
        response = self.client.post(
            "/api/forms", json={**FORM_DATA, **overrides}
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def add_review(
        self,
        form_id,
        first_reviewer="د. منى حسن",
        second_reviewer="د. محمد علي",
    ):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                INSERT INTO form_reviews (
                    lab_form_id, first_reviewer_name, first_reviewed_at,
                    second_reviewer_name, second_reviewed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    form_id,
                    first_reviewer,
                    "2026-10-20T09:30",
                    second_reviewer,
                    "2026-10-21T11:15",
                ),
            )
            connection.commit()

    def create_reviewed_form(self, **overrides):
        form_id = self.create_form(**overrides)
        self.add_review(form_id)
        return form_id

    def delivery_payload(self, form_ids, **overrides):
        payload = {
            "recipient_name": "د. هالة سمير",
            "recipient_entity": "إدارة EBI",
            "recipient_contact": "ebi@example.test",
            "recipient_notes": "قسم الترصد",
            "delivery_date": date.today().isoformat(),
            "delivered_by": "أحمد مندوب المعمل",
            "notes": "تسليم دوري",
            "form_ids": [str(form_id) for form_id in form_ids],
        }
        payload.update(overrides)
        return payload

    def get_delivery(self, delivery_id=1):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM ebi_deliveries WHERE id = ?", (delivery_id,)
        ).fetchone()
        connection.close()
        return row

    def test_admin_sees_delivery_link_and_page(self):
        page = self.client.get("/forms").get_data(as_text=True)
        self.assertIn("التسليم للمدير", page)
        self.assertIn('href="/deliveries"', page)

        merged = self.client.get("/deliveries")
        self.assertEqual(merged.status_code, 200)
        merged_page = merged.get_data(as_text=True)
        self.assertIn("تسليم الاستمارات للمدير", merged_page)
        self.assertIn('value="وزارة الصحة"', merged_page)
        self.assertNotIn("الدكتورة أميرة", merged_page)

        response = self.client.get("/deliveries/ebi")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("تسليم الاستمارات المراجعة", page)
        self.assertIn('name="recipient_name"', page)
        self.assertIn('name="delivery_date"', page)
        self.assertIn('name="delivered_by"', page)
        self.assertIn("سيتم توثيق تاريخ ووقت العملية تلقائيًا", page)

    def test_delivery_is_admin_only(self):
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
        self.assertEqual(self.client.get("/deliveries/ebi").status_code, 403)
        self.assertEqual(self.client.get("/deliveries").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/deliveries/ebi", data=self.delivery_payload([1])
            ).status_code,
            403,
        )
        page = self.client.get("/forms").get_data(as_text=True)
        self.assertNotIn("التسليم للمدير", page)

    def test_delivery_page_shows_eligible_category_cards(self):
        self.create_reviewed_form(
            lab_number="L20B-CAT-A", national_id="42601151234567", contact_number="نقص مناعة"
        )
        self.create_reviewed_form(
            lab_number="L20B-CAT-B", national_id="42601151234568", contact_number="1"
        )
        self.create_reviewed_form(
            lab_number="L20B-CAT-C", national_id="42601151234569", contact_number="3"
        )
        self.create_reviewed_form(
            lab_number="L20B-CAT-D", national_id="42601151234570", contact_number=""
        )
        self.create_form(
            lab_number="L20B-CAT-E", national_id="42601151234571", contact_number="نقص مناعة"
        )

        page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertNotIn("عمليات فاشلة", page)
        self.assertIn("نقص المناعة", page)
        self.assertIn("المخالطين", page)
        self.assertIn("AFB", page)

        counts = {}
        for name in ("نقص المناعة", "المخالطين", "AFB"):
            match = re.search(
                rf"<strong>(\d+)</strong><small>{name}</small>", page
            )
            self.assertIsNotNone(match, f"لم يتم العثور على بطاقة {name}")
            counts[name] = int(match.group(1))
        self.assertEqual(counts["نقص المناعة"], 1)
        self.assertEqual(counts["المخالطين"], 2)
        self.assertEqual(counts["AFB"], 1)

    def test_only_fully_reviewed_forms_are_listed(self):
        reviewed_id = self.create_reviewed_form()
        unreviewed_id = self.create_form(
            lab_number="L20B-EBI-002", national_id="32601151234568"
        )
        first_only_id = self.create_form(
            lab_number="L20B-EBI-003", national_id="32601151234569"
        )
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                INSERT INTO form_reviews (
                    lab_form_id, first_reviewer_name, first_reviewed_at
                ) VALUES (?, 'د. أول', '2026-10-20T09:30')
                """,
                (first_only_id,),
            )
            connection.commit()

        page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertIn(f'value="{reviewed_id}"', page)
        self.assertNotIn(f'value="{unreviewed_id}"', page)
        self.assertNotIn(f'value="{first_only_id}"', page)

    def test_successful_delivery_posts_payload_and_records_audit(self):
        form_id = self.create_reviewed_form()
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeEbiResponse(status=201, body=b'{"delivery_id":"EBI-OK"}')

        with mock.patch("app.urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/deliveries/ebi", data=self.delivery_payload([form_id])
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/deliveries/ebi?sent=1"))
        delivery = self.get_delivery()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery["status"], "delivered")
        self.assertEqual(delivery["form_count"], 1)
        self.assertEqual(delivery["response_status"], 201)
        self.assertIn("EBI-OK", delivery["response_body"])
        self.assertTrue(delivery["created_at"])
        self.assertEqual(delivery["created_by"], "tester")

        self.assertEqual(captured["url"], "http://ebi.test/api/forms")
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer secret-token")
        self.assertEqual(captured["timeout"], 5.0)
        payload = captured["payload"]
        self.assertEqual(payload["source"], "PolioLab")
        self.assertEqual(payload["delivery"]["recipient"]["name"], "د. هالة سمير")
        self.assertEqual(payload["delivery"]["delivered_by"], "أحمد مندوب المعمل")
        self.assertEqual(payload["delivery"]["recorded_at"], delivery["created_at"].replace(" ", "T"))
        self.assertEqual(len(payload["forms"]), 1)
        self.assertEqual(payload["forms"][0]["lab_number"], "L20B-EBI-001")
        self.assertEqual(
            payload["forms"][0]["review"]["second"]["reviewer_name"],
            "د. محمد علي",
        )

        page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertIn("تم تسليم", page)
        self.assertIn(delivery["reference"], page)
        self.assertNotIn(f'value="{form_id}"', page)

    def test_api_key_header_is_supported(self):
        form_id = self.create_reviewed_form()
        self.app.config["EBI_API_TOKEN"] = ""
        self.app.config["EBI_API_KEY"] = "key-123"
        captured = {}

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            return FakeEbiResponse(status=200)

        with mock.patch("app.urlopen", side_effect=fake_urlopen):
            response = self.client.post(
                "/deliveries/ebi", data=self.delivery_payload([form_id])
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(captured["headers"].get("X-api-key"), "key-123")
        self.assertNotIn("Authorization", captured["headers"])

    def test_failed_delivery_is_recorded_and_can_be_retried(self):
        form_id = self.create_reviewed_form()

        with mock.patch("app.urlopen", side_effect=URLError("offline")):
            response = self.client.post(
                "/deliveries/ebi", data=self.delivery_payload([form_id])
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/deliveries/ebi?failed=1"))
        delivery = self.get_delivery()
        self.assertEqual(delivery["status"], "failed")
        self.assertIn("تعذر الاتصال", delivery["error_message"])
        page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertIn(f'value="{form_id}"', page)

        with mock.patch("app.urlopen", return_value=FakeEbiResponse(status=200)):
            retry = self.client.post(
                "/deliveries/ebi", data=self.delivery_payload([form_id])
            )
        self.assertEqual(retry.status_code, 302)
        self.assertTrue(retry.headers["Location"].endswith("/deliveries/ebi?sent=2"))
        self.assertEqual(self.get_delivery(2)["status"], "delivered")

    def test_http_error_records_response_body(self):
        form_id = self.create_reviewed_form()
        response_body = b'{"error":"invalid payload"}'

        def fake_urlopen(request, timeout):
            raise HTTPError(
                request.full_url,
                422,
                "Unprocessable Entity",
                None,
                io.BytesIO(response_body),
            )

        with mock.patch("app.urlopen", side_effect=fake_urlopen):
            self.client.post("/deliveries/ebi", data=self.delivery_payload([form_id]))

        delivery = self.get_delivery()
        self.assertEqual(delivery["status"], "failed")
        self.assertEqual(delivery["response_status"], 422)
        self.assertEqual(delivery["response_body"], response_body.decode())
        self.assertIn("HTTP 422", delivery["error_message"])

    def test_delivery_validation(self):
        reviewed_id = self.create_reviewed_form()
        unreviewed_id = self.create_form(
            lab_number="L20B-EBI-004", national_id="32601151234570"
        )

        missing_recipient = self.client.post(
            "/deliveries/ebi", data=self.delivery_payload([reviewed_id], recipient_name="")
        )
        self.assertEqual(missing_recipient.status_code, 400)
        self.assertIn("اسم المستلم مطلوب", missing_recipient.get_data(as_text=True))

        future_date = (date.today() + timedelta(days=1)).isoformat()
        future = self.client.post(
            "/deliveries/ebi",
            data=self.delivery_payload([reviewed_id], delivery_date=future_date),
        )
        self.assertEqual(future.status_code, 400)
        self.assertIn(
            "لا يمكن أن يكون تاريخ التسليم في المستقبل",
            future.get_data(as_text=True),
        )

        unreviewed = self.client.post(
            "/deliveries/ebi", data=self.delivery_payload([unreviewed_id])
        )
        self.assertEqual(unreviewed.status_code, 400)
        self.assertIn("غير مؤهلة", unreviewed.get_data(as_text=True))

        no_selection = self.client.post(
            "/deliveries/ebi", data=self.delivery_payload([])
        )
        self.assertEqual(no_selection.status_code, 400)
        self.assertIn(
            "حدد استمارة مراجعة واحدة على الأقل",
            no_selection.get_data(as_text=True),
        )

    def test_missing_api_configuration_blocks_delivery(self):
        form_id = self.create_reviewed_form()
        self.app.config["EBI_API_URL"] = ""
        response = self.client.post(
            "/deliveries/ebi", data=self.delivery_payload([form_id])
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("خدمة التسليم إلى الدكتورة أميرة غير مهيأة", response.get_data(as_text=True))
        self.assertIsNone(self.get_delivery())

        page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertNotIn("EBI_API_URL", page)
        self.assertNotIn("الإرسال إلى الدكتورة أميرة غير مفعّل", page)
        self.assertNotIn("خدمة التسليم إلى الدكتورة أميرة غير مهيأة", page)

    def test_delivered_form_cannot_be_delivered_again(self):
        form_id = self.create_reviewed_form()
        with mock.patch("app.urlopen", return_value=FakeEbiResponse(status=200)):
            self.client.post("/deliveries/ebi", data=self.delivery_payload([form_id]))

        with mock.patch("app.urlopen", return_value=FakeEbiResponse(status=200)):
            duplicate = self.client.post(
                "/deliveries/ebi", data=self.delivery_payload([form_id])
            )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("غير مؤهلة", duplicate.get_data(as_text=True))
        connection = sqlite3.connect(self.database)
        count = connection.execute(
            "SELECT COUNT(*) FROM ebi_deliveries"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(count, 1)

    def review_payload(self, **overrides):
        now = datetime.now().replace(second=0, microsecond=0)
        payload = {
            "first_reviewer_name": "د. المراجعة الأولى",
            "first_reviewed_at": (now - timedelta(days=2)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "second_reviewer_name": "د. المراجعة الثانية",
            "second_reviewed_at": (now - timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
        }
        payload.update(overrides)
        return payload

    def enable_pdf_generation(self):
        self.app.config["DELIVERY_PDF_ENABLED"] = True
        return Path(self.app.config["DELIVERY_PDF_DIR"])

    def test_second_review_automatically_queues_form_and_builds_pdf(self):
        pdf_dir = self.enable_pdf_generation()
        form_id = self.create_form()
        captured = {}

        def fake_render(html, output_path):
            captured["html"] = html
            Path(output_path).write_bytes(
                b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF\n"
            )
            return "C:/browser/msedge.exe"

        with mock.patch("app.render_html_to_pdf", side_effect=fake_render) as renderer:
            response = self.client.post(
                f"/reviews/{form_id}", data=self.review_payload()
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/reviews?saved=1"))
        self.assertEqual(renderer.call_count, 1)
        self.assertIn("L20B-EBI-001", captured["html"])

        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            queued_at = connection.execute(
                "SELECT delivery_queued_at FROM form_reviews WHERE lab_form_id = ?",
                (form_id,),
            ).fetchone()[0]
        self.assertTrue(queued_at)

        metadata_path = pdf_dir / "current.json"
        self.assertTrue(metadata_path.is_file())
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["form_count"], 1)
        self.assertEqual(metadata["form_ids"], [form_id])
        self.assertTrue((pdf_dir / metadata["filename"]).is_file())

        page = self.client.get("/reviews").get_data(as_text=True)
        self.assertIn("تم تحويل", page)
        self.assertIn("ملف PDF المجمع", page)

        delivery_page = self.client.get("/deliveries/ebi").get_data(as_text=True)
        self.assertIn("ملف الاستمارات الجاهزة للتسليم", delivery_page)
        self.assertIn("عرض PDF", delivery_page)
        self.assertIn(f'value="{form_id}"', delivery_page)
        self.assertEqual(renderer.call_count, 1)

        pdf_response = self.client.get("/deliveries/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF-"))

        download = self.client.get("/deliveries/pdf?download=1")
        self.assertIn(
            "attachment", download.headers.get("Content-Disposition", "")
        )

    def test_pdf_is_regenerated_when_another_form_is_queued(self):
        self.enable_pdf_generation()
        first_id = self.create_form()
        second_id = self.create_form(
            lab_number="L20B-EBI-002", national_id="32601151234568"
        )
        calls = []

        def fake_render(html, output_path):
            calls.append(html)
            Path(output_path).write_bytes(
                b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF\n"
            )
            return "C:/browser/msedge.exe"

        with mock.patch("app.render_html_to_pdf", side_effect=fake_render):
            self.client.post(f"/reviews/{first_id}", data=self.review_payload())
            self.assertEqual(len(calls), 1)
            self.client.post(f"/reviews/{second_id}", data=self.review_payload())

        self.assertEqual(len(calls), 2)
        self.assertIn("L20B-EBI-001", calls[1])
        self.assertIn("L20B-EBI-002", calls[1])
        metadata_path = Path(self.app.config["DELIVERY_PDF_DIR"]) / "current.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["form_count"], 2)

    def test_removing_second_review_clears_queue_and_pdf(self):
        pdf_dir = self.enable_pdf_generation()
        form_id = self.create_form()

        def fake_render(html, output_path):
            Path(output_path).write_bytes(
                b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF\n"
            )
            return "C:/browser/msedge.exe"

        with mock.patch("app.render_html_to_pdf", side_effect=fake_render):
            self.client.post(f"/reviews/{form_id}", data=self.review_payload())

        self.assertTrue((pdf_dir / "current.json").is_file())
        self.assertEqual(self.client.get("/deliveries/pdf").status_code, 200)

        self.client.post(
            f"/reviews/{form_id}",
            data=self.review_payload(
                second_reviewer_name="", second_reviewed_at=""
            ),
        )

        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            queued_at = connection.execute(
                "SELECT delivery_queued_at FROM form_reviews WHERE lab_form_id = ?",
                (form_id,),
            ).fetchone()[0]
        self.assertEqual(queued_at, "")
        self.assertFalse((pdf_dir / "current.json").exists())
        self.assertEqual(self.client.get("/deliveries/pdf").status_code, 404)

    def test_pdf_failure_does_not_block_review_or_queue(self):
        pdf_dir = self.enable_pdf_generation()
        form_id = self.create_form()

        with mock.patch(
            "app.render_html_to_pdf",
            side_effect=RuntimeError("browser failed"),
        ):
            response = self.client.post(
                f"/reviews/{form_id}", data=self.review_payload()
            )
            page = self.client.get("/reviews").get_data(as_text=True)
            delivery_page = self.client.get("/deliveries/ebi").get_data(
                as_text=True
            )

        self.assertEqual(response.status_code, 302)
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            queued_at = connection.execute(
                "SELECT delivery_queued_at FROM form_reviews WHERE lab_form_id = ?",
                (form_id,),
            ).fetchone()[0]
        self.assertTrue(queued_at)
        self.assertFalse((pdf_dir / "current.json").exists())

        self.assertIn("تعذر إنشاء ملف PDF المجمع", page)
        self.assertIn("تعذر إنشاء الملف تلقائياً", delivery_page)

    def test_delivery_detail_is_admin_only_and_shows_audit(self):
        form_id = self.create_reviewed_form()
        with mock.patch("app.urlopen", return_value=FakeEbiResponse(status=200)):
            self.client.post("/deliveries/ebi", data=self.delivery_payload([form_id]))

        detail = self.client.get("/deliveries/1")
        self.assertEqual(detail.status_code, 200)
        page = detail.get_data(as_text=True)
        self.assertIn("تفاصيل عملية التسليم", page)
        self.assertIn("د. هالة سمير", page)
        self.assertIn("أحمد مندوب المعمل", page)
        self.assertIn("L20B-EBI-001", page)
        self.assertIn("Payload", page)
        self.assertIn("استجابة الدكتورة أميرة", page)

        self.client.post("/logout")
        self.assertEqual(self.client.get("/deliveries/1").status_code, 302)


if __name__ == "__main__":
    unittest.main()
