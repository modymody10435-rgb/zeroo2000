import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app

FORM_DATA = {
    "national_id": "32601151234567",
    "lab_number": "L20B-REVIEW-1",
    "patient_name": "مريض المراجعة",
    "center": "مدينة نصر",
    "governorate": "القاهرة",
    "sample_condition": "جيدة",
}

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def make_text_pdf(text):
    stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(output)


class ReviewTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.reviews_dir = root / "reviews"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(root / "test.db"),
                "UPLOAD_DIR": str(root / "uploads"),
                "REVIEWS_DIR": str(self.reviews_dir),
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
        response = self.client.post(
            "/api/forms", json={**FORM_DATA, **overrides}
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def review_url(self, form_id):
        return f"/reviews/{form_id}"

    def get_review(self, form_id):
        connection = sqlite3.connect(self.app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        review = connection.execute(
            "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
        ).fetchone()
        connection.close()
        return review

    def test_review_page_and_folder_creation(self):
        form_id = self.create_form()

        listing = self.client.get("/reviews")
        self.assertEqual(listing.status_code, 200)
        page = listing.get_data(as_text=True)
        self.assertIn("سجل المراجعات", page)
        self.assertIn("المراجعة الأولى", page)
        self.assertIn("المراجعة الثانية", page)
        self.assertIn("رفع مراجعة مجمعة بصيغة PDF", page)
        self.assertIn('value="pdf"', page)
        self.assertIn("جميع الاستمارات المطابقة في ملف PDF", page)
        self.assertIn(f"#{form_id}", page)
        self.assertIn("بانتظار المراجعة", page)

        detail = self.client.get(self.review_url(form_id))
        self.assertEqual(detail.status_code, 200)
        detail_html = detail.get_data(as_text=True)
        self.assertIn('name="first_reviewer_name"', detail_html)
        self.assertIn('name="first_reviewed_at"', detail_html)
        self.assertIn('name="second_reviewer_name"', detail_html)
        self.assertIn('name="second_reviewed_at"', detail_html)

        saved = self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "د. سارة محمود",
                "first_reviewed_at": "2020-01-15T09:45",
                "second_reviewer_name": "",
                "second_reviewed_at": "",
            },
        )
        self.assertEqual(saved.status_code, 302)
        self.assertTrue(saved.headers["Location"].endswith("/reviews?saved=1"))

        review = self.get_review(form_id)
        self.assertIsNotNone(review)
        self.assertEqual(review["first_reviewer_name"], "د. سارة محمود")
        self.assertEqual(review["first_reviewed_at"], "2020-01-15T09:45")
        self.assertEqual(review["second_reviewer_name"], "")
        self.assertEqual(review["folder_path"], f"2020-01-15/form-{form_id}")

        folder = self.reviews_dir / "2020-01-15" / f"form-{form_id}"
        self.assertTrue(folder.is_dir())
        metadata = json.loads((folder / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["form_id"], form_id)
        self.assertEqual(metadata["first_reviewer_name"], "د. سارة محمود")
        self.assertEqual(metadata["first_reviewed_at"], "2020-01-15T09:45")
        self.assertEqual(metadata["second_reviewer_name"], "")

        listing = self.client.get("/reviews").get_data(as_text=True)
        self.assertIn("د. سارة محمود", listing)
        self.assertIn("15/01/2020 - 09:45 ص", listing)
        self.assertIn("بانتظار المراجعة الثانية", listing)

    def test_second_review_is_tracked_independently(self):
        form_id = self.create_form()
        self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "المراجع الأول",
                "first_reviewed_at": "2020-01-15T09:45",
                "second_reviewer_name": "المراجع الثاني",
                "second_reviewed_at": "2020-01-20T11:30",
            },
        )

        review = self.get_review(form_id)
        self.assertEqual(review["first_reviewer_name"], "المراجع الأول")
        self.assertEqual(review["first_reviewed_at"], "2020-01-15T09:45")
        self.assertEqual(review["second_reviewer_name"], "المراجع الثاني")
        self.assertEqual(review["second_reviewed_at"], "2020-01-20T11:30")
        self.assertEqual(review["folder_path"], f"2020-01-15/form-{form_id}")

        page = self.client.get("/reviews").get_data(as_text=True)
        self.assertIn("المراجع الأول", page)
        self.assertIn("المراجع الثاني", page)
        self.assertIn("20/01/2020 - 11:30 ص", page)

    def test_review_update_moves_to_new_date_folder(self):
        form_id = self.create_form()
        self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "المراجع الأول",
                "first_reviewed_at": "2020-01-15T09:45",
            },
        )

        same_day = self.client.get("/reviews").get_data(as_text=True)
        self.assertIn("المراجع الأول", same_day)

        updated = self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "المراجع الثاني",
                "first_reviewed_at": "2020-01-16T11:15",
            },
        )
        self.assertEqual(updated.status_code, 302)

        old_folder = self.reviews_dir / "2020-01-15" / f"form-{form_id}"
        new_folder = self.reviews_dir / "2020-01-16" / f"form-{form_id}"
        self.assertTrue(old_folder.is_dir())
        self.assertTrue(new_folder.is_dir())
        metadata = json.loads(
            (new_folder / "review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["first_reviewer_name"], "المراجع الثاني")
        self.assertEqual(metadata["first_reviewed_at"], "2020-01-16T11:15")

        detail = self.client.get(self.review_url(form_id)).get_data(as_text=True)
        self.assertIn("2020-01-16/form-" + str(form_id), detail)

    def test_review_validation(self):
        form_id = self.create_form()

        missing = self.client.post(self.review_url(form_id), data={})
        self.assertEqual(missing.status_code, 200)
        self.assertIn(
            "أدخل بيانات مرحلة مراجعة واحدة على الأقل",
            missing.get_data(as_text=True),
        )

        partial = self.client.post(
            self.review_url(form_id),
            data={"first_reviewer_name": "د. سارة"},
        )
        self.assertEqual(partial.status_code, 200)
        self.assertIn(
            "تاريخ ووقت المراجعة مطلوبان", partial.get_data(as_text=True)
        )

        invalid = self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "د. سارة",
                "first_reviewed_at": "2020-01-15",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(
            "صيغة تاريخ ووقت المراجعة غير صحيحة", invalid.get_data(as_text=True)
        )

        future = self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "د. سارة",
                "first_reviewed_at": "2099-01-15T09:45",
            },
        )
        self.assertEqual(future.status_code, 200)
        self.assertIn(
            "لا يمكن أن يكون وقت المراجعة في المستقبل",
            future.get_data(as_text=True),
        )

        long_name = self.client.post(
            self.review_url(form_id),
            data={
                "first_reviewer_name": "ا" * 121,
                "first_reviewed_at": "2020-01-15T09:45",
            },
        )
        self.assertEqual(long_name.status_code, 200)
        self.assertIn(
            "اسم المراجع أطول من الحد المسموح", long_name.get_data(as_text=True)
        )

        self.assertIsNone(self.get_review(form_id))

    def test_review_missing_form_returns_404(self):
        self.assertEqual(self.client.get("/reviews/9999").status_code, 404)
        self.assertEqual(
            self.client.post(
                "/reviews/9999",
                data={
                    "first_reviewer_name": "د. سارة",
                    "first_reviewed_at": "2020-01-15T09:45",
                },
            ).status_code,
            404,
        )

    def test_batch_pdf_matches_forms_and_serves_file(self):
        first_id = self.create_form()
        second_id = self.create_form(
            lab_number="L20B-REVIEW-2",
            national_id="32601151234568",
            patient_name="مريض ثان",
        )
        first_pdf = make_text_pdf("L20B-REVIEW-1 L20B-REVIEW-2")

        response = self.client.post(
            "/reviews/batch",
            data={
                "stage": "first",
                "reviewer_name": "د. منى حسن",
                "reviewed_at": "2020-02-10T10:15",
                "review_pdf": (io.BytesIO(first_pdf), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith("/reviews?batch_saved=2")
        )

        first_review = self.get_review(first_id)
        second_review = self.get_review(second_id)
        self.assertIsNotNone(first_review)
        self.assertIsNotNone(second_review)
        self.assertEqual(first_review["first_reviewer_name"], "د. منى حسن")
        self.assertEqual(first_review["first_reviewed_at"], "2020-02-10T10:15")
        self.assertEqual(second_review["first_reviewer_name"], "د. منى حسن")
        self.assertTrue(first_review["pdf_path"].startswith("pdfs/2020-02-10/"))
        self.assertEqual(first_review["pdf_path"], second_review["pdf_path"])

        pdf_file = self.reviews_dir / first_review["pdf_path"]
        self.assertTrue(pdf_file.is_file())
        self.assertEqual(pdf_file.read_bytes(), first_pdf)

        folder = self.reviews_dir / "2020-02-10" / f"form-{first_id}"
        metadata = json.loads((folder / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["first_reviewer_name"], "د. منى حسن")
        self.assertEqual(metadata["pdf_path"], first_review["pdf_path"])

        pdf_response = self.client.get(
            f"/reviews/pdf/{first_review['pdf_path']}"
        )
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertEqual(pdf_response.data, first_pdf)

        second_pdf = make_text_pdf("L20B-REVIEW-1")
        second_upload = self.client.post(
            "/reviews/batch",
            data={
                "stage": "second",
                "reviewer_name": "د. محمد علي",
                "reviewed_at": "2020-02-12T12:00",
                "apply_mode": "selected",
                "form_ids": [str(first_id)],
                "review_pdf": (io.BytesIO(second_pdf), "second-pass.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(second_upload.status_code, 302)
        self.assertTrue(
            second_upload.headers["Location"].endswith("/reviews?batch_saved=1")
        )

        updated = self.get_review(first_id)
        self.assertEqual(updated["first_reviewer_name"], "د. منى حسن")
        self.assertEqual(updated["first_reviewed_at"], "2020-02-10T10:15")
        self.assertEqual(updated["second_reviewer_name"], "د. محمد علي")
        self.assertEqual(updated["second_reviewed_at"], "2020-02-12T12:00")
        self.assertNotEqual(updated["pdf_path"], first_review["pdf_path"])

        second_updated = self.get_review(second_id)
        self.assertEqual(second_updated["second_reviewer_name"], "")
        self.assertEqual(second_updated["second_reviewed_at"], "")
        self.assertEqual(second_updated["pdf_path"], first_review["pdf_path"])

    def test_batch_multiple_selection_is_limited_to_pdf_matches(self):
        selected_ids = [
            self.create_form(
                lab_number=f"L20B-MULTI-{index}",
                national_id=f"3260115123457{index}",
                patient_name=f"مريض متعدد {index}",
            )
            for index in (1, 2)
        ]
        other_id = self.create_form(
            lab_number="L20B-MULTI-3",
            national_id="32601151234573",
            patient_name="مريض غير محدد",
        )
        pdf_bytes = make_text_pdf("L20B-MULTI-1 L20B-MULTI-2 L20B-MULTI-3")

        response = self.client.post(
            "/reviews/batch",
            data={
                "stage": "first",
                "reviewer_name": "د. منى حسن",
                "reviewed_at": "2020-02-10T10:15",
                "apply_mode": "selected",
                "form_ids": [str(form_id) for form_id in selected_ids],
                "review_pdf": (io.BytesIO(pdf_bytes), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith("/reviews?batch_saved=2")
        )
        for form_id in selected_ids:
            self.assertIsNotNone(self.get_review(form_id))
        self.assertIsNone(self.get_review(other_id))

    def test_batch_pdf_matches_forms_by_default(self):
        first_id = self.create_form()
        second_id = self.create_form(
            lab_number="L20B-REVIEW-2",
            national_id="32601151234568",
            patient_name="مريض ثان",
        )
        third_id = self.create_form(
            lab_number="L20B-REVIEW-3",
            national_id="32601151234573",
            patient_name="مريض ثالث",
        )
        pdf_bytes = make_text_pdf("L20B-REVIEW-1 32601151234568")

        response = self.client.post(
            "/reviews/batch",
            data={
                "stage": "first",
                "reviewer_name": "د. منى حسن",
                "reviewed_at": "2020-02-10T10:15",
                "form_ids": [str(third_id)],
                "review_pdf": (io.BytesIO(pdf_bytes), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith("/reviews?batch_saved=2")
        )
        self.assertIsNotNone(self.get_review(first_id))
        self.assertIsNotNone(self.get_review(second_id))
        self.assertIsNone(self.get_review(third_id))

    def test_batch_selected_mode_only_updates_pdf_matches(self):
        first_id = self.create_form()
        second_id = self.create_form(
            lab_number="L20B-REVIEW-2",
            national_id="32601151234568",
            patient_name="مريض ثان",
        )
        pdf_bytes = make_text_pdf("L20B-REVIEW-1")

        response = self.client.post(
            "/reviews/batch",
            data={
                "stage": "first",
                "reviewer_name": "د. منى حسن",
                "reviewed_at": "2020-02-10T10:15",
                "apply_mode": "selected",
                "form_ids": [str(second_id)],
                "review_pdf": (io.BytesIO(pdf_bytes), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith("/reviews?batch_saved=1")
        )
        self.assertIsNotNone(self.get_review(first_id))
        self.assertIsNone(self.get_review(second_id))

    def test_batch_selected_mode_requires_matching_selection(self):
        first_id = self.create_form()
        second_id = self.create_form(
            lab_number="L20B-REVIEW-2",
            national_id="32601151234568",
            patient_name="مريض ثان",
        )
        third_id = self.create_form(
            lab_number="L20B-REVIEW-3",
            national_id="32601151234573",
            patient_name="مريض ثالث",
        )
        pdf_bytes = make_text_pdf("L20B-REVIEW-1")

        response = self.client.post(
            "/reviews/batch",
            data={
                "stage": "first",
                "reviewer_name": "د. منى حسن",
                "reviewed_at": "2020-02-10T10:15",
                "apply_mode": "selected",
                "form_ids": [str(second_id), str(third_id)],
                "review_pdf": (io.BytesIO(pdf_bytes), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "لا توجد استمارات محددة ضمن الاستمارات المطابقة",
            response.get_data(as_text=True),
        )
        self.assertIsNone(self.get_review(first_id))
        self.assertIsNone(self.get_review(second_id))
        self.assertIsNone(self.get_review(third_id))
        self.assertFalse(any((self.reviews_dir / "pdfs").glob("**/*.pdf")))

    def test_batch_pdf_requires_matching_forms(self):
        form_id = self.create_form()
        pdf_bytes = make_text_pdf("L20B-UNKNOWN 99999999999999")

        response = self.client.post(
            "/reviews/batch",
            data={
                "stage": "first",
                "reviewer_name": "د. منى حسن",
                "reviewed_at": "2020-02-10T10:15",
                "review_pdf": (io.BytesIO(pdf_bytes), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "لم يتم العثور على استمارات مطابقة",
            response.get_data(as_text=True),
        )
        self.assertIsNone(self.get_review(form_id))

    def test_batch_pdf_validation(self):
        form_id = self.create_form()
        base_data = {
            "stage": "first",
            "reviewer_name": "د. منى حسن",
            "reviewed_at": "2020-02-10T10:15",
        }

        unreadable = self.client.post(
            "/reviews/batch",
            data={
                **base_data,
                "review_pdf": (io.BytesIO(PDF_BYTES), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(unreadable.status_code, 400)
        self.assertIn(
            "تعذر قراءة محتوى ملف PDF",
            unreadable.get_data(as_text=True),
        )

        no_file = self.client.post(
            "/reviews/batch",
            data={**base_data, "form_ids": [str(form_id)]},
            content_type="multipart/form-data",
        )
        self.assertEqual(no_file.status_code, 400)
        self.assertIn("ملف PDF المجمع مطلوب", no_file.get_data(as_text=True))

        empty = self.client.post(
            "/reviews/batch",
            data=base_data,
            content_type="multipart/form-data",
        )
        self.assertEqual(empty.status_code, 400)
        empty_html = empty.get_data(as_text=True)
        self.assertIn("ملف PDF المجمع مطلوب", empty_html)
        self.assertIn('id="review-pdf-error"', empty_html)

        wrong_type = self.client.post(
            "/reviews/batch",
            data={
                **base_data,
                "review_pdf": (io.BytesIO(PDF_BYTES), "combined.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(wrong_type.status_code, 400)
        self.assertIn("يُسمح برفع ملفات PDF فقط", wrong_type.get_data(as_text=True))

        invalid_pdf = self.client.post(
            "/reviews/batch",
            data={
                **base_data,
                "review_pdf": (io.BytesIO(b"not a pdf"), "combined.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid_pdf.status_code, 400)
        self.assertIn(
            "ليس ملف PDF صالحًا", invalid_pdf.get_data(as_text=True)
        )

        self.assertIsNone(self.get_review(form_id))
        self.assertFalse(any((self.reviews_dir / "pdfs").glob("**/*.pdf")))


class ReviewMigrationTestCase(unittest.TestCase):
    def make_app(self, database, reviews_dir, root):
        return create_app(
            {
                "TESTING": True,
                "DATABASE": str(database),
                "UPLOAD_DIR": str(root / "uploads"),
                "REVIEWS_DIR": str(reviews_dir),
                "AUTH_USERNAME": "tester",
                "AUTH_PASSWORD": "secret123",
                "SEED_DEMO": False,
            }
        )

    def test_legacy_review_columns_are_moved_and_folders_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "legacy.db"
            reviews_dir = root / "reviews"
            schema = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(
                encoding="utf-8"
            )
            legacy_schema = schema.replace(
                "    notes TEXT NOT NULL DEFAULT '',\n    created_by TEXT NOT NULL DEFAULT '',",
                "    notes TEXT NOT NULL DEFAULT '',\n"
                "    reviewer_name TEXT NOT NULL DEFAULT '',\n"
                "    reviewed_at TEXT NOT NULL DEFAULT '',\n"
                "    created_by TEXT NOT NULL DEFAULT '',",
            )
            self.assertNotEqual(legacy_schema, schema)

            connection = sqlite3.connect(database)
            connection.executescript(legacy_schema)
            cursor = connection.execute(
                """
                INSERT INTO lab_forms
                    (lab_number, patient_name, reviewer_name, reviewed_at)
                VALUES (?, ?, ?, ?)
                """,
                ("L20B-LEGACY-REVIEW", "استمارة قديمة", "د. مراجع قديم", "2020-01-15T09:45"),
            )
            form_id = cursor.lastrowid
            connection.commit()
            connection.close()

            app = self.make_app(database, reviews_dir, root)

            connection = sqlite3.connect(database)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(lab_forms)")
            }
            self.assertNotIn("reviewer_name", columns)
            self.assertNotIn("reviewed_at", columns)
            review = connection.execute(
                "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
            ).fetchone()
            connection.close()

            self.assertIsNotNone(review)
            self.assertEqual(review[2], "د. مراجع قديم")
            self.assertEqual(review[3], "2020-01-15T09:45")
            self.assertEqual(review[7], f"2020-01-15/form-{form_id}")

            folder = reviews_dir / "2020-01-15" / f"form-{form_id}"
            self.assertTrue(folder.is_dir())
            self.assertTrue((folder / "review.json").is_file())

            client = app.test_client()
            client.post(
                "/api/login", json={"username": "tester", "password": "secret123"}
            )
            page = client.get("/reviews").get_data(as_text=True)
            self.assertIn("د. مراجع قديم", page)
            self.assertIn("L20B-LEGACY-REVIEW", page)

    def test_legacy_form_reviews_columns_are_migrated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "legacy-reviews.db"
            reviews_dir = root / "reviews"
            app = self.make_app(database, reviews_dir, root)

            connection = sqlite3.connect(database)
            cursor = connection.execute(
                "INSERT INTO lab_forms (lab_number, patient_name) VALUES (?, ?)",
                ("L20B-OLD-REVIEWS", "مراجعة قديمة"),
            )
            form_id = cursor.lastrowid
            connection.execute("ALTER TABLE form_reviews RENAME TO form_reviews_new")
            connection.execute(
                """
                CREATE TABLE form_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lab_form_id INTEGER NOT NULL UNIQUE,
                    reviewer_name TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    folder_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (lab_form_id) REFERENCES lab_forms (id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                INSERT INTO form_reviews
                    (lab_form_id, reviewer_name, reviewed_at, folder_path)
                VALUES (?, ?, ?, ?)
                """,
                (form_id, "د. قديم", "2020-03-01T08:30", f"2020-03-01/form-{form_id}"),
            )
            connection.execute(
                "CREATE INDEX idx_form_reviews_reviewed_at ON form_reviews (reviewed_at)"
            )
            connection.execute("DROP TABLE form_reviews_new")
            connection.commit()
            connection.close()

            self.make_app(database, reviews_dir, root)

            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(form_reviews)")
            }
            review = connection.execute(
                "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
            ).fetchone()
            indexes = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
            connection.close()

            self.assertNotIn("reviewer_name", columns)
            self.assertNotIn("reviewed_at", columns)
            self.assertIn("first_reviewer_name", columns)
            self.assertIn("second_reviewer_name", columns)
            self.assertIn("pdf_path", columns)
            self.assertEqual(review["first_reviewer_name"], "د. قديم")
            self.assertEqual(review["first_reviewed_at"], "2020-03-01T08:30")
            self.assertIn("idx_form_reviews_first_reviewed_at", indexes)
            self.assertNotIn("idx_form_reviews_reviewed_at", indexes)


if __name__ == "__main__":
    unittest.main()
