import base64
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unicodedata
import uuid
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent

GOVERNORATES = [
    "القاهرة",
    "الجيزة",
    "الإسكندرية",
    "الدقهلية",
    "الشرقية",
    "القليوبية",
    "المنوفية",
    "الغربية",
    "البحيرة",
    "كفر الشيخ",
    "دمياط",
    "بورسعيد",
    "الإسماعيلية",
    "السويس",
    "شمال سيناء",
    "جنوب سيناء",
    "الفيوم",
    "بني سويف",
    "المنيا",
    "أسيوط",
    "سوهاج",
    "قنا",
    "الأقصر",
    "أسوان",
    "البحر الأحمر",
    "الوادي الجديد",
    "مطروح",
]

FORM_RESULTS = ["سلبي", "إيجابي", "قيد الإنجاز", "لم يتم الفحص"]
FORM_CONDITIONS = ["جيدة"]
FORM_POSITIONS = {"left": "يسار", "center": "وسط", "right": "يمين"}
REVIEW_STAGES = {
    "first": {
        "label": "المراجعة الأولى",
        "reviewer": "first_reviewer_name",
        "reviewed_at": "first_reviewed_at",
    },
    "second": {
        "label": "المراجعة الثانية",
        "reviewer": "second_reviewer_name",
        "reviewed_at": "second_reviewed_at",
    },
}
REVIEW_PDF_MAX_BYTES = 30 * 1024 * 1024
DELIVERY_PDF_VERSION = "1"
DELIVERY_PDF_LOCK = threading.Lock()

LAB_FORM_FIELDS = [
    "national_id",
    "lab_number",
    "patient_name",
    "age_months",
    "age_years",
    "illness_date",
    "center",
    "governorate",
    "sample_condition",
    "sample1_collect_date",
    "sample1_receive_date",
    "sample1_l20b",
    "sample1_prelim_date",
    "sample1_final",
    "sample1_final_date",
    "sample2_collect_date",
    "sample2_receive_date",
    "sample2_l20b",
    "sample2_prelim_date",
    "sample2_final",
    "sample2_final_date",
    "signatory_name",
    "stamp_position",
    "signature_position",
    "notes",
]

LAB_FORM_DATE_FIELDS = [
    "illness_date",
    "sample1_collect_date",
    "sample1_receive_date",
    "sample1_prelim_date",
    "sample1_final_date",
    "sample2_collect_date",
    "sample2_receive_date",
    "sample2_prelim_date",
    "sample2_final_date",
]

LAB_FORM_RESULT_FIELDS = [
    "sample1_l20b",
    "sample1_final",
    "sample2_l20b",
    "sample2_final",
]

DEMO_FORMS = [
    {
        "national_id": "32601151234567",
        "lab_number": "L20B-0012",
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
        "sample1_final_date": "2026-10-12",
        "sample2_collect_date": "2026-10-01",
        "sample2_receive_date": "2026-10-02",
        "sample2_l20b": "سلبي",
        "sample2_prelim_date": "2026-10-07",
        "sample2_final": "سلبي",
        "sample2_final_date": "",
        "signatory_name": "ك/ أميرة يحيى زغلول",
        "notes": "",
    },
    {
        "national_id": "32603051234567",
        "lab_number": "L20B-0013",
        "patient_name": "ملك محمد السيد",
        "age_months": "6",
        "age_years": "0",
        "illness_date": "2026-10-03",
        "center": "العجوزة",
        "governorate": "الجيزة",
        "sample_condition": "جيدة",
        "sample1_collect_date": "2026-10-04",
        "sample1_receive_date": "2026-10-05",
        "sample1_l20b": "قيد الإنجاز",
        "sample1_prelim_date": "",
        "sample1_final": "",
        "sample1_final_date": "",
        "sample2_collect_date": "",
        "sample2_receive_date": "",
        "sample2_l20b": "",
        "sample2_prelim_date": "",
        "sample2_final": "",
        "sample2_final_date": "",
        "signatory_name": "ك/ أميرة يحيى زغلول",
        "notes": "عينة أولى فقط",
    },
]

bp = Blueprint("main", __name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    db.executescript(schema)
    migrate_review_columns(db)
    user_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "role" not in user_columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
        )

    form_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(lab_forms)").fetchall()
    }
    if "created_by" not in form_columns:
        db.execute(
            "ALTER TABLE lab_forms ADD COLUMN created_by TEXT NOT NULL DEFAULT ''"
        )
    migrate_legacy_reviews(db, form_columns)
    sync_review_metadata(db)
    db.commit()


def seed_db():
    db = get_db()
    total_forms = db.execute("SELECT COUNT(*) AS count FROM lab_forms").fetchone()["count"]
    if total_forms:
        return
    columns = [
        "national_id",
        "lab_number",
        "patient_name",
        "age_months",
        "age_years",
        "illness_date",
        "center",
        "governorate",
        "sample_condition",
        "sample1_collect_date",
        "sample1_receive_date",
        "sample1_l20b",
        "sample1_prelim_date",
        "sample1_final",
        "sample1_final_date",
        "sample2_collect_date",
        "sample2_receive_date",
        "sample2_l20b",
        "sample2_prelim_date",
        "sample2_final",
        "sample2_final_date",
        "signatory_name",
        "notes",
    ]
    db.executemany(
        f"INSERT INTO lab_forms ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [[form[column] for column in columns] for form in DEMO_FORMS],
    )
    db.commit()


def seed_admin_user():
    username = clean_text(current_app.config.get("AUTH_USERNAME"))
    password_hash = str(current_app.config.get("AUTH_PASSWORD_HASH") or "")
    if not username or not password_hash:
        return

    db = get_db()
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    if existing is not None:
        db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (existing["id"],))
        db.commit()
        return

    if db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]:
        return
    db.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
        (username, password_hash),
    )
    db.commit()


def clean_text(value):
    return str(value or "").strip()


def format_datetime_ar(value):
    text = clean_text(value)
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    period = "م" if parsed.hour >= 12 else "ص"
    hour = parsed.hour % 12 or 12
    return (
        f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year} - "
        f"{hour:02d}:{parsed.minute:02d} {period}"
    )


def reviews_dir():
    path = Path(current_app.config["REVIEWS_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def review_pdf_dir(day=None):
    day = clean_text(day)
    try:
        date.fromisoformat(day)
    except ValueError:
        day = date.today().isoformat()
    path = reviews_dir() / "pdfs" / day
    path.mkdir(parents=True, exist_ok=True)
    return day, path


def review_folder_path(form_id, reviewed_at):
    day = clean_text(reviewed_at)[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        day = date.today().isoformat()
    relative = f"{day}/form-{int(form_id)}"
    (reviews_dir() / day / f"form-{int(form_id)}").mkdir(
        parents=True, exist_ok=True
    )
    return relative


def review_metadata(form_row, review_row, folder_path):
    payload = {
        "form_id": form_row["id"],
        "lab_number": form_row["lab_number"],
        "patient_name": form_row["patient_name"],
        "created_by": form_row["created_by"],
        "pdf_path": review_row["pdf_path"] if review_row else "",
        "folder_path": folder_path,
        "delivery_queued_at": (
            review_row["delivery_queued_at"] if review_row else ""
        ),
    }
    for stage in REVIEW_STAGES.values():
        payload[stage["reviewer"]] = (
            review_row[stage["reviewer"]] if review_row else ""
        )
        payload[stage["reviewed_at"]] = (
            review_row[stage["reviewed_at"]] if review_row else ""
        )
    return payload


def write_review_metadata(folder_path, form_row, review_row):
    if not folder_path:
        return
    folder = reviews_dir() / folder_path
    folder.mkdir(parents=True, exist_ok=True)
    payload = review_metadata(form_row, review_row, folder_path)
    (folder / "review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sync_review_metadata(db):
    reviews = db.execute(
        "SELECT * FROM form_reviews WHERE folder_path <> ''"
    ).fetchall()
    for review in reviews:
        form_row = db.execute(
            "SELECT * FROM lab_forms WHERE id = ?", (review["lab_form_id"],)
        ).fetchone()
        if form_row is not None:
            write_review_metadata(review["folder_path"], form_row, review)


def sync_delivery_queued_at(db, form_id=None):
    where = ""
    params = []
    if form_id is not None:
        where = " WHERE lab_form_id = ?"
        params.append(form_id)
    db.execute(
        f"""
        UPDATE form_reviews
        SET delivery_queued_at = CASE
            WHEN TRIM(first_reviewer_name) <> ''
             AND TRIM(first_reviewed_at) <> ''
             AND TRIM(second_reviewer_name) <> ''
             AND TRIM(second_reviewed_at) <> ''
            THEN CASE
                WHEN TRIM(delivery_queued_at) = ''
                THEN CURRENT_TIMESTAMP
                ELSE delivery_queued_at
            END
            ELSE ''
        END
        {where}
        """,
        params,
    )


def validate_review_details(reviewer_name, reviewed_at):
    values = {
        "reviewer_name": clean_text(reviewer_name),
        "reviewed_at": clean_text(reviewed_at),
    }
    errors = {}

    if not values["reviewer_name"]:
        errors["reviewer_name"] = "اسم المراجع مطلوب"
    elif len(values["reviewer_name"]) > 120:
        errors["reviewer_name"] = "اسم المراجع أطول من الحد المسموح"

    if not values["reviewed_at"]:
        errors["reviewed_at"] = "تاريخ ووقت المراجعة مطلوبان"
    else:
        try:
            if not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?",
                values["reviewed_at"],
            ):
                raise ValueError
            reviewed = datetime.fromisoformat(values["reviewed_at"])
        except ValueError:
            errors["reviewed_at"] = "صيغة تاريخ ووقت المراجعة غير صحيحة"
        else:
            if reviewed > datetime.now():
                errors["reviewed_at"] = "لا يمكن أن يكون وقت المراجعة في المستقبل"
            else:
                values["reviewed_at"] = reviewed.isoformat(timespec="minutes")

    return values, errors


def validate_review_stage(payload, stage, required=False):
    stage_fields = REVIEW_STAGES[stage]
    reviewer_key = stage_fields["reviewer"]
    reviewed_key = stage_fields["reviewed_at"]
    reviewer_name = clean_text(payload.get(reviewer_key))
    reviewed_at = clean_text(payload.get(reviewed_key))

    if not required and not reviewer_name and not reviewed_at:
        return {
            "reviewer_name": "",
            "reviewed_at": "",
        }, {}

    values, errors = validate_review_details(reviewer_name, reviewed_at)
    stage_errors = {}
    if "reviewer_name" in errors:
        stage_errors[reviewer_key] = errors["reviewer_name"]
    if "reviewed_at" in errors:
        stage_errors[reviewed_key] = errors["reviewed_at"]
    return values, stage_errors


def save_review_record(
    form_id,
    first_reviewer_name="",
    first_reviewed_at="",
    second_reviewer_name="",
    second_reviewed_at="",
    pdf_path=None,
):
    db = get_db()
    form_row = db.execute(
        "SELECT * FROM lab_forms WHERE id = ?", (form_id,)
    ).fetchone()
    if form_row is None:
        return None

    existing = db.execute(
        "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
    ).fetchone()
    if pdf_path is None:
        pdf_path = existing["pdf_path"] if existing else ""

    folder_path = review_folder_path(
        form_id, first_reviewed_at or second_reviewed_at
    )
    db.execute(
        """
        INSERT INTO form_reviews
            (lab_form_id, first_reviewer_name, first_reviewed_at,
             second_reviewer_name, second_reviewed_at, pdf_path, folder_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(lab_form_id) DO UPDATE SET
            first_reviewer_name = excluded.first_reviewer_name,
            first_reviewed_at = excluded.first_reviewed_at,
            second_reviewer_name = excluded.second_reviewer_name,
            second_reviewed_at = excluded.second_reviewed_at,
            pdf_path = excluded.pdf_path,
            folder_path = excluded.folder_path,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            form_id,
            first_reviewer_name,
            first_reviewed_at,
            second_reviewer_name,
            second_reviewed_at,
            pdf_path,
            folder_path,
        ),
    )
    sync_delivery_queued_at(db, form_id)
    db.commit()
    review_row = db.execute(
        "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
    ).fetchone()
    write_review_metadata(folder_path, form_row, review_row)
    return folder_path


def store_review_pdf(file_storage, reviewed_at):
    filename = clean_text(getattr(file_storage, "filename", ""))
    if not filename:
        raise ValueError("ملف PDF المجمع مطلوب")
    if Path(filename).suffix.lower() != ".pdf":
        raise ValueError("يُسمح برفع ملفات PDF فقط")
    header = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    if header != b"%PDF-":
        raise ValueError("الملف المرفوع ليس ملف PDF صالحًا")

    day, folder = review_pdf_dir(clean_text(reviewed_at)[:10])
    target_name = f"{datetime.now():%H%M%S}-{uuid.uuid4().hex[:12]}.pdf"
    destination = folder / target_name
    file_storage.save(destination)
    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise ValueError("ملف PDF المرفوع فارغ")
    if destination.stat().st_size > REVIEW_PDF_MAX_BYTES:
        destination.unlink(missing_ok=True)
        raise ValueError("حجم ملف PDF أكبر من الحد المسموح")
    return f"pdfs/{day}/{target_name}"


def discard_review_pdf(pdf_path):
    text = clean_text(pdf_path)
    if not text:
        return
    base = reviews_dir().resolve()
    target = (base / text).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return
    if target.suffix.lower() == ".pdf":
        try:
            target.unlink()
        except OSError:
            pass


def normalize_pdf_match_text(text):
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(
        str.maketrans(
            "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
            "01234567890123456789",
        )
    )
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return text


def extract_review_pdf_text(pdf_path):
    try:
        from pdfminer.high_level import extract_text
    except ImportError as error:
        raise ValueError(
            "مكتبة قراءة ملفات PDF غير متوفرة على الخادم"
        ) from error

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    target = (reviews_dir() / pdf_path).resolve()
    try:
        text = extract_text(str(target))
    except Exception as error:
        raise ValueError("تعذر قراءة محتوى ملف PDF") from error
    if not clean_text(text):
        raise ValueError(
            "ملف PDF لا يحتوي على نص قابل للقراءة. استخدم ملف PDF نصيًا غير مصور."
        )
    return text


def find_pdf_form_ids(pdf_path, db):
    pdf_text = normalize_pdf_match_text(extract_review_pdf_text(pdf_path))
    compact_text = re.sub(r"\s+", "", pdf_text)
    matched_ids = []
    rows = db.execute(
        "SELECT id, lab_number, national_id FROM lab_forms"
    ).fetchall()
    for row in rows:
        lab_number = re.sub(
            r"\s+", "", normalize_pdf_match_text(row["lab_number"])
        ).upper()
        national_id = re.sub(
            r"\s+", "", normalize_pdf_match_text(row["national_id"])
        )
        matched = False
        if len(lab_number) >= 4:
            matched = (
                re.search(
                    rf"(?<![A-Z0-9-]){re.escape(lab_number)}(?![A-Z0-9-])",
                    pdf_text,
                    flags=re.IGNORECASE,
                )
                is not None
            )
        if not matched and len(national_id) >= 4:
            matched = (
                re.search(
                    rf"(?<!\d){re.escape(national_id)}(?!\d)",
                    pdf_text,
                )
                is not None
            )
            if not matched:
                matched = national_id in compact_text
        if matched:
            matched_ids.append(row["id"])
    return matched_ids


EBI_DELIVERY_STATUSES = {
    "pending": "قيد الإرسال",
    "delivered": "تم التسليم",
    "failed": "فشل التسليم",
}


class EbiApiError(Exception):
    def __init__(self, message, status=None, body=""):
        super().__init__(message)
        self.status = status
        self.body = body


def ebi_api_settings():
    url = clean_text(current_app.config.get("EBI_API_URL"))
    try:
        timeout = float(current_app.config.get("EBI_API_TIMEOUT", 20))
    except (TypeError, ValueError):
        timeout = 20.0
    timeout = min(max(timeout, 3.0), 120.0)
    return {
        "url": url,
        "token": clean_text(current_app.config.get("EBI_API_TOKEN")),
        "api_key": clean_text(current_app.config.get("EBI_API_KEY")),
        "timeout": timeout,
        "configured": bool(url),
        "host": urlparse(url).netloc if url else "",
    }


def new_ebi_reference():
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"EBI-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def fetch_ebi_eligible_forms(db):
    return db.execute(
        """
        SELECT f.*,
               r.first_reviewer_name, r.first_reviewed_at,
               r.second_reviewer_name, r.second_reviewed_at,
               r.delivery_queued_at,
               r.pdf_path AS review_pdf_path
        FROM lab_forms f
        JOIN form_reviews r ON r.lab_form_id = f.id
        WHERE TRIM(r.first_reviewer_name) <> ''
          AND TRIM(r.first_reviewed_at) <> ''
          AND TRIM(r.second_reviewer_name) <> ''
          AND TRIM(r.second_reviewed_at) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM ebi_delivery_forms ef
              JOIN ebi_deliveries d ON d.id = ef.delivery_id
              WHERE ef.lab_form_id = f.id AND d.status = 'delivered'
          )
        ORDER BY r.second_reviewed_at DESC, f.id DESC
        """
    ).fetchall()


class DeliveryPdfError(Exception):
    pass


def delivery_pdf_dir():
    path = Path(current_app.config["DELIVERY_PDF_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def delivery_pdf_metadata_path():
    return delivery_pdf_dir() / "current.json"


def image_data_uri(path):
    path = Path(path)
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower(), "application/octet-stream")
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:{mime};base64,{encoded}"


def fixed_image_path(kind):
    directory = Path(current_app.config["FIXED_IMAGES_DIR"])
    for extension in FIXED_IMAGE_EXTENSIONS:
        candidate = directory / f"{kind}{extension}"
        if candidate.is_file():
            return candidate
    return None


def delivery_pdf_assets(forms):
    right, left = logo_paths()

    def logo_items(paths):
        items = []
        for path in paths:
            url = image_data_uri(path)
            if url:
                items.append({"url": url, "version": ""})
        return items

    images = {}
    for form in forms:
        for field in ("stamp_image", "signature_image"):
            filename = clean_text(form[field])
            if not filename or Path(filename).name != filename:
                continue
            path = upload_dir() / filename
            if path.is_file():
                images[filename] = image_data_uri(path)

    fixed = {}
    for kind in ("stamp", "signature"):
        path = fixed_image_path(kind)
        fixed[kind] = (
            {"url": image_data_uri(path), "version": ""} if path else None
        )

    return {
        "logos_right": logo_items(right),
        "logos_left": logo_items(left),
        "fixed_stamp": fixed["stamp"],
        "fixed_signature": fixed["signature"],
        "pdf_images": images,
    }


def render_delivery_pdf_html(forms):
    styles_css = (BASE_DIR / "static" / "css" / "styles.css").read_text(
        encoding="utf-8"
    )
    form_css = (BASE_DIR / "static" / "css" / "form.css").read_text(
        encoding="utf-8"
    )
    return render_template(
        "delivery_pdf.html",
        forms=forms,
        styles_css=styles_css,
        form_css=form_css,
        pdf_generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        **delivery_pdf_assets(forms),
    )


def find_pdf_browser():
    configured = clean_text(current_app.config.get("DELIVERY_PDF_BROWSER"))
    candidates = []
    if configured:
        candidates.append(configured)

    program_files = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    for base in program_files:
        if not base:
            continue
        candidates.extend(
            [
                str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            ]
        )
    candidates.extend(
        [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    )

    for command in (
        "msedge",
        "microsoft-edge",
        "chrome",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(command)
        if path:
            candidates.append(path)

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    raise DeliveryPdfError(
        "لم يتم العثور على متصفح Chromium/Edge لإنشاء ملف PDF. "
        "اضبط DELIVERY_PDF_BROWSER على مسار المتصفح."
    )


def render_html_to_pdf(html, output_path):
    browser = find_pdf_browser()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        timeout = float(current_app.config.get("DELIVERY_PDF_TIMEOUT", 60))
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = min(max(timeout, 10.0), 180.0)

    with tempfile.TemporaryDirectory(
        prefix="polio-pdf-", dir=str(output_path.parent)
    ) as temp_dir:
        temp = Path(temp_dir)
        html_path = temp / "combined.html"
        html_path.write_text(html, encoding="utf-8")
        profile = temp / "profile"
        profile.mkdir()
        command = [
            browser,
            "--headless=new",
            f"--user-data-dir={profile}",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=5000",
            f"--print-to-pdf={output_path.resolve()}",
            html_path.as_uri(),
        ]
        if os.name != "nt":
            command.insert(2, "--no-sandbox")
            command.insert(3, "--disable-dev-shm-usage")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                creationflags=creationflags,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DeliveryPdfError(
                f"تعذر تشغيل متصفح PDF: {error}"
            ) from error

    if completed.returncode != 0 or not output_path.is_file():
        details = completed.stderr.decode("utf-8", "replace").strip()
        details = details[-800:] if details else "بدون تفاصيل"
        raise DeliveryPdfError(f"فشل إنشاء ملف PDF: {details}")
    if output_path.stat().st_size < 1000:
        raise DeliveryPdfError("ملف PDF الناتج فارغ أو غير صالح.")
    with output_path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise DeliveryPdfError("ملف PDF الناتج غير صالح.")
    return browser


def delivery_pdf_signature(forms):
    assets = [
        BASE_DIR / "static" / "css" / "styles.css",
        BASE_DIR / "static" / "css" / "form.css",
        BASE_DIR / "templates" / "delivery_pdf.html",
        BASE_DIR / "templates" / "_sheet.html",
        BASE_DIR / "templates" / "_macros.html",
    ]
    asset_state = []
    for path in assets:
        try:
            stat = path.stat()
            asset_state.append([path.name, stat.st_mtime_ns, stat.st_size])
        except OSError:
            asset_state.append([path.name, 0, 0])
    form_state = [
        [
            row["id"],
            row["updated_at"],
            row["delivery_queued_at"],
            row["first_reviewed_at"],
            row["second_reviewed_at"],
            row["lab_number"],
        ]
        for row in forms
    ]
    payload = [DELIVERY_PDF_VERSION, asset_state, form_state]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def read_delivery_pdf_info():
    metadata = delivery_pdf_metadata_path()
    try:
        info = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(info, dict):
        return None
    filename = clean_text(info.get("filename"))
    if not filename or Path(filename).name != filename:
        return None
    if Path(filename).suffix.lower() != ".pdf":
        return None
    target = delivery_pdf_dir() / filename
    if not target.is_file() or target.stat().st_size < 1000:
        return None
    info["available"] = True
    info["enabled"] = True
    info["error"] = ""
    return info


def clear_delivery_pdf():
    metadata = delivery_pdf_metadata_path()
    current = read_delivery_pdf_info()
    if current:
        try:
            (delivery_pdf_dir() / current["filename"]).unlink()
        except OSError:
            pass
    try:
        metadata.unlink()
    except OSError:
        pass


def ensure_delivery_pdf(db, force=False):
    enabled = bool(current_app.config.get("DELIVERY_PDF_ENABLED", True))
    if not enabled:
        return {
            "enabled": False,
            "available": False,
            "error": "",
            "form_count": 0,
            "form_ids": [],
        }

    forms = fetch_ebi_eligible_forms(db)
    if not forms:
        with DELIVERY_PDF_LOCK:
            clear_delivery_pdf()
        return {
            "enabled": True,
            "available": False,
            "error": "",
            "form_count": 0,
            "form_ids": [],
        }

    signature = delivery_pdf_signature(forms)
    with DELIVERY_PDF_LOCK:
        current = read_delivery_pdf_info()
        if (
            not force
            and current
            and current.get("signature") == signature
        ):
            return current

        try:
            html = render_delivery_pdf_html(forms)
            filename = (
                f"reviewed-forms-{datetime.now():%Y%m%d-%H%M%S}-"
                f"{uuid.uuid4().hex[:8]}.pdf"
            )
            destination = delivery_pdf_dir() / filename
            browser = render_html_to_pdf(html, destination)
            info = {
                "filename": filename,
                "signature": signature,
                "form_ids": [row["id"] for row in forms],
                "form_count": len(forms),
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "browser": Path(browser).name,
            }
            metadata = delivery_pdf_metadata_path()
            temporary = metadata.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, metadata)
            if current and current.get("filename") != filename:
                try:
                    (delivery_pdf_dir() / current["filename"]).unlink()
                except OSError:
                    pass
            info.update({"available": True, "enabled": True, "error": ""})
            return info
        except Exception as error:
            logging.getLogger(__name__).exception("Delivery PDF generation failed")
            return {
                "enabled": True,
                "available": False,
                "error": str(error) or "تعذر إنشاء ملف PDF المجمع.",
                "form_count": len(forms),
                "form_ids": [row["id"] for row in forms],
            }


def set_delivery_notice(db, form_ids, pdf_result):
    queued_ids = {row["id"] for row in fetch_ebi_eligible_forms(db)}
    queued_count = sum(1 for form_id in form_ids if form_id in queued_ids)
    if queued_count <= 0:
        return
    session["delivery_notice"] = {
        "queued": queued_count,
        "pdf_enabled": bool(pdf_result.get("enabled", True)),
        "pdf_available": bool(pdf_result.get("available")),
        "pdf_error": clean_text(pdf_result.get("error")),
    }


def fetch_ebi_delivery_history(db, limit=50):
    return db.execute(
        """
        SELECT d.*,
               (SELECT COUNT(*) FROM ebi_delivery_forms ef
                WHERE ef.delivery_id = d.id) AS linked_form_count
        FROM ebi_deliveries d
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def fetch_ebi_delivery(db, delivery_id):
    return db.execute(
        "SELECT * FROM ebi_deliveries WHERE id = ?", (delivery_id,)
    ).fetchone()


def fetch_ebi_delivery_forms(db, delivery_id):
    return db.execute(
        """
        SELECT ef.*, f.id AS current_form_id, f.governorate,
               r.first_reviewer_name, r.first_reviewed_at,
               r.second_reviewer_name, r.second_reviewed_at
        FROM ebi_delivery_forms ef
        LEFT JOIN lab_forms f ON f.id = ef.lab_form_id
        LEFT JOIN form_reviews r ON r.lab_form_id = ef.lab_form_id
        WHERE ef.delivery_id = ?
        ORDER BY ef.id
        """,
        (delivery_id,),
    ).fetchall()


def build_ebi_payload(delivery, forms):
    created_at = clean_text(delivery["created_at"]).replace(" ", "T")
    payload = {
        "schema_version": 1,
        "source": "PolioLab",
        "delivery": {
            "reference": delivery["reference"],
            "recipient": {
                "name": delivery["recipient_name"],
                "entity": delivery["recipient_entity"],
                "contact": delivery["recipient_contact"],
                "notes": delivery["recipient_notes"],
            },
            "delivery_date": delivery["delivery_date"],
            "delivered_by": delivery["delivered_by"],
            "notes": delivery["notes"],
            "recorded_at": created_at,
        },
        "forms": [],
    }
    for row in forms:
        samples = []
        for number in (1, 2):
            prefix = f"sample{number}"
            samples.append(
                {
                    "sample_number": number,
                    "collection_date": row[f"{prefix}_collect_date"],
                    "received_date": row[f"{prefix}_receive_date"],
                    "l20b_result": row[f"{prefix}_l20b"],
                    "preliminary_date": row[f"{prefix}_prelim_date"],
                    "final_result": row[f"{prefix}_final"],
                    "final_date": row[f"{prefix}_final_date"],
                }
            )
        payload["forms"].append(
            {
                "id": row["id"],
                "lab_number": row["lab_number"],
                "national_id": row["national_id"],
                "patient_name": row["patient_name"],
                "age_months": row["age_months"],
                "age_years": row["age_years"],
                "illness_date": row["illness_date"],
                "center": row["center"],
                "governorate": row["governorate"],
                "sample_condition": row["sample_condition"],
                "samples": samples,
                "notes": row["notes"],
                "created_by": row["created_by"],
                "created_at": clean_text(row["created_at"]).replace(" ", "T"),
                "review": {
                    "first": {
                        "reviewer_name": row["first_reviewer_name"],
                        "reviewed_at": row["first_reviewed_at"],
                    },
                    "second": {
                        "reviewer_name": row["second_reviewer_name"],
                        "reviewed_at": row["second_reviewed_at"],
                    },
                },
            }
        )
    return payload


def send_ebi_payload(payload, settings):
    if not settings["configured"]:
        raise EbiApiError(
            "خدمة EBI غير مهيأة. اضبط EBI_API_URL وبيانات الاعتماد على الخادم."
        )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "PolioLab-EBI/1.0",
        "X-PolioLab-Reference": payload["delivery"]["reference"],
    }
    token = settings["token"]
    if token:
        headers["Authorization"] = (
            token if token.lower().startswith("bearer ") else f"Bearer {token}"
        )
    if settings["api_key"]:
        headers["X-API-Key"] = settings["api_key"]

    request = Request(
        settings["url"],
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings["timeout"]) as response:
            status = int(getattr(response, "status", response.getcode()))
            body = response.read(1024 * 1024).decode("utf-8", "replace")
    except HTTPError as error:
        body = ""
        try:
            body = error.read(1024 * 1024).decode("utf-8", "replace")
        except Exception:
            pass
        raise EbiApiError(
            f"رفض نظام EBI الطلب (HTTP {error.code})",
            status=error.code,
            body=body,
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None) or str(error)
        raise EbiApiError(f"تعذر الاتصال بنظام EBI: {reason}") from error

    if status < 200 or status >= 300:
        raise EbiApiError(
            f"رفض نظام EBI الطلب (HTTP {status})", status=status, body=body
        )
    return status, body


def validate_ebi_delivery(values, selected_ids, eligible_ids):
    errors = {}

    if not values["recipient_name"]:
        errors["recipient_name"] = "اسم المستلم مطلوب"
    elif len(values["recipient_name"]) > 160:
        errors["recipient_name"] = "اسم المستلم أطول من الحد المسموح"

    if len(values["recipient_entity"]) > 160:
        errors["recipient_entity"] = "جهة المستلم أطول من الحد المسموح"
    if len(values["recipient_contact"]) > 200:
        errors["recipient_contact"] = "بيانات اتصال المستلم أطول من الحد المسموح"
    if len(values["recipient_notes"]) > 2000:
        errors["recipient_notes"] = "تفاصيل المستلم أطول من الحد المسموح"

    if not values["delivery_date"]:
        errors["delivery_date"] = "تاريخ التسليم مطلوب"
    else:
        try:
            parsed_date = date.fromisoformat(values["delivery_date"])
        except ValueError:
            errors["delivery_date"] = "صيغة تاريخ التسليم غير صحيحة"
        else:
            if parsed_date > date.today():
                errors["delivery_date"] = "لا يمكن أن يكون تاريخ التسليم في المستقبل"

    if not values["delivered_by"]:
        errors["delivered_by"] = "اسم الشخص الذي سلّم الاستمارات مطلوب"
    elif len(values["delivered_by"]) > 160:
        errors["delivered_by"] = "اسم الشخص الذي سلّم الاستمارات أطول من الحد المسموح"

    if len(values["notes"]) > 2000:
        errors["notes"] = "ملاحظات التسليم أطول من الحد المسموح"

    if not selected_ids:
        errors["form_ids"] = "حدد استمارة مراجعة واحدة على الأقل للتسليم"
    else:
        invalid_ids = [form_id for form_id in selected_ids if form_id not in eligible_ids]
        if invalid_ids:
            errors["form_ids"] = (
                "بعض الاستمارات المحددة غير مؤهلة: يجب إكمال المراجعة الأولى "
                "والثانية، وألا تكون مسلّمة مسبقاً."
            )

    return values, errors


def pretty_json(value):
    text = clean_text(value)
    if not text:
        return ""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return text


def save_batch_reviews(form_ids, stage, reviewer_name, reviewed_at, pdf_path):
    stage_fields = REVIEW_STAGES[stage]
    db = get_db()
    for form_id in form_ids:
        existing = db.execute(
            "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
        ).fetchone()
        values = {
            stage["reviewer"]: existing[stage["reviewer"]] if existing else ""
            for stage in REVIEW_STAGES.values()
        }
        values.update(
            {
                stage["reviewed_at"]: (
                    existing[stage["reviewed_at"]] if existing else ""
                )
                for stage in REVIEW_STAGES.values()
            }
        )
        values[stage_fields["reviewer"]] = reviewer_name
        values[stage_fields["reviewed_at"]] = reviewed_at
        save_review_record(
            form_id,
            first_reviewer_name=values["first_reviewer_name"],
            first_reviewed_at=values["first_reviewed_at"],
            second_reviewer_name=values["second_reviewer_name"],
            second_reviewed_at=values["second_reviewed_at"],
            pdf_path=pdf_path,
        )


def migrate_review_columns(db):
    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(form_reviews)")
    }
    additions = {
        "first_reviewer_name": "TEXT NOT NULL DEFAULT ''",
        "first_reviewed_at": "TEXT NOT NULL DEFAULT ''",
        "second_reviewer_name": "TEXT NOT NULL DEFAULT ''",
        "second_reviewed_at": "TEXT NOT NULL DEFAULT ''",
        "delivery_queued_at": "TEXT NOT NULL DEFAULT ''",
        "pdf_path": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE form_reviews ADD COLUMN {name} {definition}")

    if "reviewer_name" in columns:
        db.execute(
            """
            UPDATE form_reviews
            SET first_reviewer_name = reviewer_name
            WHERE first_reviewer_name = '' AND reviewer_name <> ''
            """
        )
    if "reviewed_at" in columns:
        db.execute(
            """
            UPDATE form_reviews
            SET first_reviewed_at = reviewed_at
            WHERE first_reviewed_at = '' AND reviewed_at <> ''
            """
        )

    db.execute("DROP INDEX IF EXISTS idx_form_reviews_reviewed_at")
    for column in ("reviewer_name", "reviewed_at"):
        if column in columns:
            try:
                db.execute(f"ALTER TABLE form_reviews DROP COLUMN {column}")
            except sqlite3.OperationalError:
                pass

    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_form_reviews_first_reviewed_at
        ON form_reviews (first_reviewed_at)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_form_reviews_second_reviewed_at
        ON form_reviews (second_reviewed_at)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_form_reviews_delivery_queued_at
        ON form_reviews (delivery_queued_at)
        """
    )
    sync_delivery_queued_at(db)


def migrate_legacy_reviews(db, form_columns):
    if not {"reviewer_name", "reviewed_at"} <= form_columns:
        return

    rows = db.execute(
        """
        SELECT * FROM lab_forms
        WHERE reviewer_name <> '' OR reviewed_at <> ''
        """
    ).fetchall()
    for row in rows:
        reviewer_name = clean_text(row["reviewer_name"])
        reviewed_at = clean_text(row["reviewed_at"])
        folder_path = review_folder_path(row["id"], reviewed_at) if reviewed_at else ""
        db.execute(
            """
            INSERT OR IGNORE INTO form_reviews
                (lab_form_id, first_reviewer_name, first_reviewed_at, folder_path)
            VALUES (?, ?, ?, ?)
            """,
            (row["id"], reviewer_name, reviewed_at, folder_path),
        )
        review_row = db.execute(
            "SELECT * FROM form_reviews WHERE lab_form_id = ?", (row["id"],)
        ).fetchone()
        if folder_path:
            write_review_metadata(folder_path, row, review_row)

    for column in ("reviewer_name", "reviewed_at"):
        try:
            db.execute(f"ALTER TABLE lab_forms DROP COLUMN {column}")
        except sqlite3.OperationalError:
            pass


def json_body():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def authenticate(username, password):
    row = get_db().execute(
        "SELECT password_hash FROM users WHERE username = ?", (str(username),)
    ).fetchone()
    if row is None:
        return False
    try:
        return check_password_hash(row["password_hash"], str(password))
    except (TypeError, ValueError):
        return False


def safe_next(target, default=None):
    target = clean_text(target)
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default or url_for("main.forms_page")


def current_session_user():
    if "_current_session_user" in g:
        return g._current_session_user

    username = clean_text(session.get("user"))
    user = None
    if username:
        user = get_db().execute(
            "SELECT id, username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user is None:
            session.pop("user", None)

    g._current_session_user = user
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_session_user():
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"error": "يجب تسجيل الدخول أولًا"}), 401
        target = request.full_path.rstrip("?")
        return redirect(url_for("main.login_page", next=target))

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_session_user()
        if user is None or user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def lab_form_to_dict(row):
    data = {field: row[field] for field in LAB_FORM_FIELDS}
    data["id"] = row["id"]
    data["national_id"] = row["national_id"]
    data["lab_number"] = row["lab_number"]
    data["patient_name"] = row["patient_name"]
    data["stamp_image"] = row["stamp_image"]
    data["signature_image"] = row["signature_image"]
    data["show_stamp"] = bool(row["show_stamp"])
    data["show_signature"] = bool(row["show_signature"])
    data["created_by"] = row["created_by"]
    data["created_at"] = row["created_at"]
    data["updated_at"] = row["updated_at"]
    return data


def upload_dir():
    path = Path(current_app.config["UPLOAD_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


LOGO_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
FIXED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".webp")


def logo_dir():
    path = Path(current_app.config["LOGOS_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def fixed_image(kind):
    """يبحث عن صورة ختم/توقيع ثابتة بالاسم داخل مجلد العناصر الثابتة."""
    directory = Path(current_app.config["FIXED_IMAGES_DIR"])
    for extension in FIXED_IMAGE_EXTENSIONS:
        candidate = directory / f"{kind}{extension}"
        if candidate.is_file():
            return {
                "url": url_for("main.fixed_file", filename=candidate.name),
                "version": int(candidate.stat().st_mtime),
            }
    return None


def logo_paths():
    try:
        entries = sorted(
            (
                entry
                for entry in logo_dir().iterdir()
                if entry.is_file() and entry.suffix.lower() in LOGO_EXTENSIONS
            ),
            key=lambda entry: entry.name.lower(),
        )
    except OSError:
        entries = []

    right, left = [], []
    for index, entry in enumerate(entries):
        (right if index % 2 == 0 else left).append(entry)
    return right, left


def logo_slots():
    right, left = logo_paths()
    return (
        [
            {
                "url": url_for("main.logos_file", filename=entry.name),
                "version": int(entry.stat().st_mtime),
            }
            for entry in right
        ],
        [
            {
                "url": url_for("main.logos_file", filename=entry.name),
                "version": int(entry.stat().st_mtime),
            }
            for entry in left
        ],
    )


def store_image(data_url):
    from PIL import Image

    try:
        header, encoded = data_url.split(",", 1)
        raw = base64.b64decode(encoded, validate=True)
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as error:
        raise ValueError("تعذر قراءة الصورة المرفوعة") from error

    if not header.startswith("data:image/"):
        raise ValueError("يُسمح برفع ملفات صور فقط")

    width, height = image.size
    longest = max(width, height)
    if longest > 1400:
        scale = 1400 / longest
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)

    filename = f"{uuid.uuid4().hex}.png" if image.mode in ("RGBA", "LA", "P") else f"{uuid.uuid4().hex}.jpg"
    destination = upload_dir() / filename

    try:
        if filename.endswith(".png"):
            image.save(destination, format="PNG", optimize=True)
        else:
            image.convert("RGB").save(destination, format="JPEG", quality=88, optimize=True)
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise ValueError("تعذر حفظ الصورة المرفوعة") from error
    return filename


def discard_image(filename):
    filename = clean_text(filename)
    if not filename or Path(filename).name != filename:
        return
    target = upload_dir() / filename
    try:
        target.unlink()
    except OSError:
        # The file may still be locked by a concurrent download on Windows.
        pass


def store_uploaded_image(raw, current=""):
    text = clean_text(raw)
    if not text:
        return "", current
    if text.startswith("data:image/"):
        filename = store_image(text)
        return filename, (current if current and current != filename else "")
    if text.startswith("data:"):
        raise ValueError("يُسمح برفع ملفات صور فقط")
    if Path(text).name == text and (upload_dir() / text).is_file():
        return text, (current if current and current != text else "")
    return current, ""


def validate_lab_form(payload, form_id=None, existing=None):
    values = {field: clean_text(payload.get(field)) for field in LAB_FORM_FIELDS}
    errors = {}

    if not values["national_id"]:
        errors["national_id"] = "الرقم القومي مطلوب"
    elif not values["national_id"].isdigit():
        errors["national_id"] = "الرقم القومي يجب أن يحتوي على أرقام فقط"

    if not values["lab_number"]:
        errors["lab_number"] = "الرقم المعملي مطلوب"
    elif len(values["lab_number"]) > 60:
        errors["lab_number"] = "الرقم المعملي أطول من الحد المسموح"

    if not values["patient_name"] or len(values["patient_name"]) < 3:
        errors["patient_name"] = "يرجى إدخال اسم المريض"
    elif len(values["patient_name"]) > 120:
        errors["patient_name"] = "اسم المريض أطول من الحد المسموح"

    if values["age_months"]:
        if not values["age_months"].isdigit() or int(values["age_months"]) > 999:
            errors["age_months"] = "أدخل عدد شهور صحيحًا"
    if values["age_years"]:
        if not values["age_years"].isdigit() or int(values["age_years"]) > 120:
            errors["age_years"] = "أدخل عدد سنوات صحيحًا"

    for field in LAB_FORM_DATE_FIELDS:
        text = values[field]
        if not text:
            continue
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            errors[field] = "صيغة التاريخ غير صحيحة"
            continue
        if parsed > date.today():
            errors[field] = "لا يمكن أن يكون التاريخ في المستقبل"

    for field in ("sample1_l20b", "sample2_l20b"):
        if values[field] and values[field] not in FORM_RESULTS:
            errors[field] = "قيمة النتيجة غير صحيحة"

    for field in ("sample1_final", "sample2_final"):
        if len(values[field]) > 120:
            errors[field] = "النتيجة النهائية طويلة جدًا"

    if not values["sample_condition"]:
        values["sample_condition"] = FORM_CONDITIONS[0]
    elif values["sample_condition"] not in FORM_CONDITIONS:
        errors["sample_condition"] = "حالة العينات غير صحيحة"

    if values["governorate"] and values["governorate"] not in GOVERNORATES:
        errors["governorate"] = "يرجى اختيار محافظة صحيحة"

    if len(values["center"]) > 120:
        errors["center"] = "اسم المركز أطول من الحد المسموح"

    if values["stamp_position"] not in FORM_POSITIONS:
        values["stamp_position"] = "left"
    if values["signature_position"] not in FORM_POSITIONS:
        values["signature_position"] = "left"

    if len(values["signatory_name"]) > 120:
        errors["signatory_name"] = "اسم الموقِّع أطول من الحد المسموح"
    if not values["signatory_name"]:
        values["signatory_name"] = ""

    if len(values["notes"]) > 500:
        errors["notes"] = "الملاحظات أطول من الحد المسموح"

    if values["lab_number"]:
        query = "SELECT id FROM lab_forms WHERE lab_number = ?"
        params = [values["lab_number"]]
        if form_id is not None:
            query += " AND id != ?"
            params.append(form_id)
        if get_db().execute(query, params).fetchone():
            errors["lab_number"] = "هذا الرقم المعملي مسجل بالفعل"

    current_stamp = existing["stamp_image"] if existing else ""
    current_signature = existing["signature_image"] if existing else ""

    values.update(
        {
            "stamp_image": current_stamp,
            "signature_image": current_signature,
            "show_stamp": 1 if payload.get("show_stamp", True) else 0,
            "show_signature": 1 if payload.get("show_signature", True) else 0,
        }
    )

    if errors:
        return values, errors, []

    try:
        stamp_image, stamp_old = store_uploaded_image(payload.get("stamp_image"), current_stamp)
        signature_image, signature_old = store_uploaded_image(
            payload.get("signature_image"), current_signature
        )
    except ValueError as error:
        errors["stamp_image"] = str(error)
        return values, errors, []

    values["stamp_image"] = stamp_image
    values["signature_image"] = signature_image
    discarded = [name for name in (stamp_old, signature_old) if name]
    return values, errors, discarded


def build_lab_form_filters(args):
    clauses = []
    params = []

    search = clean_text(args.get("search"))
    if search:
        pattern = f"%{search}%"
        clauses.append(
            "(patient_name LIKE ? OR national_id LIKE ? OR lab_number LIKE ? OR center LIKE ? OR governorate LIKE ?)"
        )
        params.extend([pattern] * 5)

    governorate = clean_text(args.get("governorate"))
    if governorate:
        clauses.append("governorate = ?")
        params.append(governorate)

    result = clean_text(args.get("result"))
    if result in FORM_RESULTS:
        clauses.append("(sample1_final = ? OR sample2_final = ?)")
        params.extend([result, result])

    where = ""
    if clauses:
        where = " WHERE " + " AND ".join(clauses)
    return where, params


@bp.get("/")
def index():
    if current_session_user():
        return redirect(url_for("main.forms_page"))
    return redirect(url_for("main.login_page"))


@bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET" and current_session_user():
        return redirect(url_for("main.forms_page"))

    next_target = safe_next(request.values.get("next"))
    username = ""
    error = ""

    if request.method == "POST":
        username = clean_text(request.form.get("username"))
        password = str(request.form.get("password") or "")
        if not username or not password:
            error = "يرجى إدخال اسم المستخدم وكلمة المرور"
        elif not authenticate(username, password):
            error = "اسم المستخدم أو كلمة المرور غير صحيحة"
        else:
            session.clear()
            session["user"] = username
            return redirect(next_target)

    status = 401 if error else 200
    return render_template("login.html", error=error, username=username, next=next_target), status


@bp.post("/api/login")
def api_login():
    payload = json_body() or request.form
    username = clean_text(payload.get("username"))
    password = str(payload.get("password") or "")

    if not username or not password:
        return jsonify({"error": "يرجى إدخال اسم المستخدم وكلمة المرور"}), 400
    if not authenticate(username, password):
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401

    session.clear()
    session["user"] = username
    return jsonify({"ok": True, "redirect": safe_next(payload.get("next"))})


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login_page"))


USERNAME_PATTERN = re.compile(r"^[\w.\-]{3,50}$", re.UNICODE)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
USER_ROLES = {"admin": "مدير", "user": "مستخدم"}


def validate_password(password, confirm):
    errors = {}

    if not password:
        errors["password"] = "كلمة المرور مطلوبة"
    elif len(password) < PASSWORD_MIN_LENGTH:
        errors["password"] = f"كلمة المرور يجب ألا تقل عن {PASSWORD_MIN_LENGTH} أحرف"
    elif len(password) > PASSWORD_MAX_LENGTH:
        errors["password"] = "كلمة المرور أطول من الحد المسموح"

    if not confirm:
        errors["password_confirm"] = "يرجى تأكيد كلمة المرور"
    elif password != confirm:
        errors["password_confirm"] = "كلمتا المرور غير متطابقتين"

    return errors


def validate_new_user(username, password, confirm, role):
    errors = {}

    if not username:
        errors["username"] = "اسم المستخدم مطلوب"
    elif not USERNAME_PATTERN.fullmatch(username):
        errors["username"] = "اسم المستخدم 3–50 حرفاً بدون مسافات (حروف وأرقام و . _ -)"

    if role not in USER_ROLES:
        errors["role"] = "الدور المحدد غير صالح"

    errors.update(validate_password(password, confirm))
    return errors


@bp.get("/users")
@login_required
@admin_required
def users_page():
    current_username = current_session_user()["username"]
    users = [
        dict(row)
        for row in get_db().execute(
            "SELECT id, username, role, created_at FROM users ORDER BY created_at DESC, id DESC"
        ).fetchall()
    ]
    for user in users:
        user["is_current"] = user["username"].casefold() == current_username.casefold()

    return render_template(
        "users.html",
        users=users,
        created=clean_text(request.args.get("created")),
        updated=clean_text(request.args.get("updated")),
        deleted=clean_text(request.args.get("deleted")),
        error=clean_text(request.args.get("error")),
    )


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user_page():
    values = {"username": "", "role": "user"}
    errors = {}

    if request.method == "POST":
        username = clean_text(request.form.get("username"))
        password = str(request.form.get("password") or "")
        confirm = str(request.form.get("password_confirm") or "")
        role = clean_text(request.form.get("role")) or "user"
        values = {"username": username, "role": role}
        errors = validate_new_user(username, password, confirm, role)

        if not errors:
            db = get_db()
            exists = db.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if exists is not None:
                errors["username"] = "اسم المستخدم مستخدم بالفعل"
            else:
                try:
                    db.execute(
                        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                        (username, generate_password_hash(password), role),
                    )
                    db.commit()
                except sqlite3.IntegrityError:
                    errors["username"] = "اسم المستخدم مستخدم بالفعل"
                else:
                    return redirect(url_for("main.users_page", created=username))

    status = 400 if errors else 200
    return render_template("user_new.html", errors=errors, values=values), status


@bp.route("/users/<int:user_id>/password", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user_password_page(user_id):
    db = get_db()
    user = db.execute(
        "SELECT id, username, role, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        abort(404)

    errors = {}
    if request.method == "POST":
        password = str(request.form.get("password") or "")
        confirm = str(request.form.get("password_confirm") or "")
        errors = validate_password(password, confirm)

        if not errors:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), user_id),
            )
            db.commit()
            return redirect(url_for("main.users_page", updated=user["username"]))

    current_username = str(session.get("user") or "")
    is_current = user["username"].casefold() == current_username.casefold()

    status = 400 if errors else 200
    return (
        render_template(
            "user_password.html", user=user, errors=errors, is_current=is_current
        ),
        status,
    )


@bp.post("/users/<int:user_id>/delete")
@login_required
@admin_required
def delete_user(user_id):
    db = get_db()
    user = db.execute(
        "SELECT id, username FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        return redirect(url_for("main.users_page", error="notfound"))

    current_username = str(session.get("user") or "")
    if user["username"].casefold() == current_username.casefold():
        return redirect(url_for("main.users_page", error="self"))

    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return redirect(url_for("main.users_page", deleted=user["username"]))


@bp.app_errorhandler(403)
def forbidden(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "لا تملك صلاحية الوصول إلى هذا المورد"}), 403
    return render_template("forbidden.html"), 403


@bp.get("/api/health")
def health():
    return jsonify({"status": "ok"})


LAB_FORM_COLUMNS = LAB_FORM_FIELDS + [
    "stamp_image",
    "signature_image",
    "show_stamp",
    "show_signature",
]


def lab_form_summary(db):
    return {
        "total": db.execute("SELECT COUNT(*) AS c FROM lab_forms").fetchone()["c"],
        "finalized": db.execute(
            "SELECT COUNT(*) AS c FROM lab_forms WHERE sample1_final <> '' OR sample2_final <> ''"
        ).fetchone()["c"],
        "pending": db.execute(
            "SELECT COUNT(*) AS c FROM lab_forms WHERE sample1_final = '' AND sample2_final = ''"
        ).fetchone()["c"],
        "positive": db.execute(
            "SELECT COUNT(*) AS c FROM lab_forms WHERE sample1_final = 'إيجابي' OR sample2_final = 'إيجابي'"
        ).fetchone()["c"],
    }


def insert_lab_form(values, created_by=""):
    columns = [*LAB_FORM_COLUMNS, "created_by"]
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO lab_forms ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [*[values[column] for column in LAB_FORM_COLUMNS], created_by],
    )
    db.commit()
    return cursor.lastrowid


def replace_lab_form(form_id, values):
    assignments = ", ".join(f"{column} = ?" for column in LAB_FORM_COLUMNS)
    db = get_db()
    db.execute(
        f"UPDATE lab_forms SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [*[values[column] for column in LAB_FORM_COLUMNS], form_id],
    )
    db.commit()


@bp.get("/forms")
@login_required
def forms_page():
    return render_template("forms.html")


@bp.get("/forms/new")
@login_required
def new_form_page():
    return render_template("form.html", form=None)


@bp.get("/forms/<int:form_id>")
@login_required
def edit_form_page(form_id):
    row = get_db().execute("SELECT * FROM lab_forms WHERE id = ?", (form_id,)).fetchone()
    if row is None:
        abort(404)
    return render_template("form.html", form=lab_form_to_dict(row))


@bp.get("/forms/batch")
@login_required
def batch_forms_page():
    form_ids = []
    for chunk in request.args.getlist("ids"):
        for part in chunk.split(","):
            part = part.strip()
            if part.isdigit():
                form_id = int(part)
                if form_id not in form_ids:
                    form_ids.append(form_id)
    form_ids = form_ids[:100]
    if not form_ids:
        abort(404)

    placeholders = ", ".join("?" for _ in form_ids)
    rows = get_db().execute(
        f"SELECT * FROM lab_forms WHERE id IN ({placeholders})", form_ids
    ).fetchall()
    by_id = {row["id"]: lab_form_to_dict(row) for row in rows}
    forms = [by_id[form_id] for form_id in form_ids if form_id in by_id]
    if not forms:
        abort(404)
    return render_template("forms_batch.html", forms=forms)


@bp.get("/uploads/<filename>")
def uploaded_file(filename):
    if Path(filename).name != filename:
        abort(404)
    return send_from_directory(upload_dir(), filename)


@bp.get("/logos/<filename>")
def logos_file(filename):
    if Path(filename).name != filename:
        abort(404)
    return send_from_directory(logo_dir(), filename)


@bp.get("/fixed/<filename>")
def fixed_file(filename):
    if Path(filename).name != filename:
        abort(404)
    return send_from_directory(current_app.config["FIXED_IMAGES_DIR"], filename)


@bp.get("/api/forms")
@login_required
def list_forms():
    db = get_db()
    where, params = build_lab_form_filters(request.args)

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(50, max(1, int(request.args.get("per_page", 10))))
    except (TypeError, ValueError):
        per_page = 10

    total = db.execute(f"SELECT COUNT(*) AS count FROM lab_forms{where}", params).fetchone()["count"]
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    rows = db.execute(
        f"""
        SELECT * FROM lab_forms{where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, per_page, offset],
    ).fetchall()

    return jsonify(
        {
            "items": [lab_form_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
            "summary": lab_form_summary(db),
        }
    )


@bp.get("/api/forms/<int:form_id>")
@login_required
def get_form(form_id):
    row = get_db().execute("SELECT * FROM lab_forms WHERE id = ?", (form_id,)).fetchone()
    if row is None:
        return jsonify({"error": "لم يتم العثور على الاستمارة"}), 404
    return jsonify(lab_form_to_dict(row))


@bp.post("/api/forms")
@login_required
def create_form():
    payload = json_body()
    values, errors, discarded = validate_lab_form(payload)
    if errors:
        for name in discarded:
            discard_image(name)
        return jsonify({"error": "يرجى تصحيح الحقول المحددة", "fields": errors}), 400

    try:
        form_id = insert_lab_form(values, current_session_user()["username"])
    except sqlite3.IntegrityError:
        for name in discarded:
            discard_image(name)
        return (
            jsonify(
                {
                    "error": "يرجى تصحيح الحقول المحددة",
                    "fields": {"lab_number": "هذا الرقم المعملي مسجل بالفعل"},
                }
            ),
            400,
        )

    for name in discarded:
        discard_image(name)
    row = get_db().execute("SELECT * FROM lab_forms WHERE id = ?", (form_id,)).fetchone()
    return jsonify(lab_form_to_dict(row)), 201


@bp.put("/api/forms/<int:form_id>")
@login_required
def update_form(form_id):
    db = get_db()
    existing = db.execute("SELECT * FROM lab_forms WHERE id = ?", (form_id,)).fetchone()
    if existing is None:
        return jsonify({"error": "لم يتم العثور على الاستمارة"}), 404

    payload = json_body()
    values, errors, discarded = validate_lab_form(payload, form_id=form_id, existing=existing)
    if errors:
        for name in discarded:
            discard_image(name)
        return jsonify({"error": "يرجى تصحيح الحقول المحددة", "fields": errors}), 400

    try:
        replace_lab_form(form_id, values)
    except sqlite3.IntegrityError:
        for name in discarded:
            discard_image(name)
        return (
            jsonify(
                {
                    "error": "يرجى تصحيح الحقول المحددة",
                    "fields": {"lab_number": "هذا الرقم المعملي مسجل بالفعل"},
                }
            ),
            400,
        )

    for name in discarded:
        discard_image(name)
    row = db.execute("SELECT * FROM lab_forms WHERE id = ?", (form_id,)).fetchone()
    return jsonify(lab_form_to_dict(row))


@bp.delete("/api/forms/<int:form_id>")
@login_required
def delete_form(form_id):
    db = get_db()
    row = db.execute("SELECT * FROM lab_forms WHERE id = ?", (form_id,)).fetchone()
    if row is None:
        return jsonify({"error": "لم يتم العثور على الاستمارة"}), 404
    db.execute("DELETE FROM lab_forms WHERE id = ?", (form_id,))
    db.commit()
    discard_image(row["stamp_image"])
    discard_image(row["signature_image"])
    return Response(status=204)


def reviews_context():
    db = get_db()
    forms = db.execute(
        """
        SELECT f.id, f.lab_number, f.patient_name, f.governorate,
               f.created_at, f.created_by,
               r.first_reviewer_name, r.first_reviewed_at,
               r.second_reviewer_name, r.second_reviewed_at,
               r.pdf_path, r.folder_path
        FROM lab_forms f
        LEFT JOIN form_reviews r ON r.lab_form_id = f.id
        ORDER BY f.created_at DESC, f.id DESC
        """
    ).fetchall()
    first_reviewed = sum(1 for row in forms if row["first_reviewed_at"])
    second_reviewed = sum(1 for row in forms if row["second_reviewed_at"])
    return {
        "forms": forms,
        "first_reviewed_count": first_reviewed,
        "second_reviewed_count": second_reviewed,
        "pending_first_count": len(forms) - first_reviewed,
        "pending_second_count": len(forms) - second_reviewed,
        "saved": request.args.get("saved") == "1",
        "batch_saved": request.args.get("batch_saved", ""),
        "delivery_notice": session.pop("delivery_notice", None),
        "now_value": datetime.now().strftime("%Y-%m-%dT%H:%M"),
    }


@bp.get("/reviews")
@login_required
def reviews_page():
    user = current_session_user()
    context = reviews_context()
    context["batch_values"] = {
        "reviewer_name": user["username"] if user else "",
        "reviewed_at": context["now_value"],
        "stage": "first",
        "form_ids": [],
        "apply_mode": "pdf",
    }
    context["batch_errors"] = {}
    return render_template("reviews.html", **context)


@bp.post("/reviews/batch")
@login_required
def reviews_batch_upload():
    user = current_session_user()
    context = reviews_context()
    stage = clean_text(request.form.get("stage"))
    reviewer_name = clean_text(request.form.get("reviewer_name"))
    reviewed_at = clean_text(request.form.get("reviewed_at"))
    apply_mode = clean_text(request.form.get("apply_mode")) or "pdf"
    if apply_mode not in {"selected", "pdf"}:
        apply_mode = "pdf"
    if not reviewer_name and user:
        reviewer_name = user["username"]
    if not reviewed_at:
        reviewed_at = context["now_value"]

    selected_ids = []
    for raw_id in request.form.getlist("form_ids"):
        try:
            form_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if form_id not in selected_ids:
            selected_ids.append(form_id)

    context["batch_values"] = {
        "reviewer_name": reviewer_name,
        "reviewed_at": reviewed_at,
        "stage": stage,
        "form_ids": selected_ids,
        "apply_mode": apply_mode,
    }
    errors = {}

    if stage not in REVIEW_STAGES:
        errors["stage"] = "اختر المراجعة الأولى أو الثانية"

    values, stage_errors = validate_review_details(reviewer_name, reviewed_at)
    errors.update(stage_errors)
    reviewer_name = values["reviewer_name"]
    reviewed_at = values["reviewed_at"]

    db = get_db()
    if apply_mode == "selected":
        if not selected_ids:
            errors["form_ids"] = (
                "اختر استمارة واحدة على الأقل لرفع المراجعة المجمعة"
            )
        else:
            placeholders = ", ".join("?" for _ in selected_ids)
            existing_ids = {
                row["id"]
                for row in db.execute(
                    f"SELECT id FROM lab_forms WHERE id IN ({placeholders})",
                    selected_ids,
                ).fetchall()
            }
            if len(existing_ids) != len(selected_ids):
                errors["form_ids"] = "بعض الاستمارات المحددة غير موجودة"
            elif len(selected_ids) == 1:
                all_ids = [
                    row["id"]
                    for row in db.execute(
                        "SELECT id FROM lab_forms "
                        "ORDER BY created_at DESC, id DESC"
                    ).fetchall()
                ]
                if len(all_ids) > 1:
                    selected_ids = all_ids
                    context["batch_values"]["form_ids"] = selected_ids

    pdf_upload = request.files.get("review_pdf")
    if not pdf_upload or not clean_text(getattr(pdf_upload, "filename", "")):
        errors["review_pdf"] = "ملف PDF المجمع مطلوب"

    pdf_path = ""
    if not errors:
        try:
            pdf_path = store_review_pdf(pdf_upload, reviewed_at)
        except ValueError as error:
            errors["review_pdf"] = str(error)

    if not errors:
        try:
            matched_ids = find_pdf_form_ids(pdf_path, db)
        except ValueError as error:
            errors["review_pdf"] = str(error)
        else:
            if not matched_ids:
                errors["review_pdf"] = (
                    "لم يتم العثور على استمارات مطابقة لبيانات ملف PDF. "
                    "تأكد من احتواء الملف على الرقم المعملي أو الرقم القومي."
                )
            elif apply_mode == "pdf":
                selected_ids = matched_ids
            else:
                matched_set = set(matched_ids)
                selected_ids = [
                    form_id for form_id in selected_ids if form_id in matched_set
                ]
                if not selected_ids:
                    errors["review_pdf"] = (
                        "لا توجد استمارات محددة ضمن الاستمارات المطابقة "
                        "لبيانات ملف PDF."
                    )
        if errors:
            discard_review_pdf(pdf_path)

    if not errors:
        try:
            save_batch_reviews(
                selected_ids, stage, reviewer_name, reviewed_at, pdf_path
            )
        except Exception:
            discard_review_pdf(pdf_path)
            raise
        pdf_result = ensure_delivery_pdf(db)
        set_delivery_notice(db, selected_ids, pdf_result)
        return redirect(
            url_for(
                "main.reviews_page",
                batch_saved=len(selected_ids),
            )
        )

    context["batch_errors"] = errors
    return render_template("reviews.html", **context), 400


@bp.get("/reviews/pdf/<path:filename>")
@login_required
def review_pdf(filename):
    base = reviews_dir().resolve()
    target = (base / filename).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        abort(404)
    if target.suffix.lower() != ".pdf" or not target.is_file():
        abort(404)
    return send_file(target, mimetype="application/pdf", as_attachment=False)


@bp.route("/reviews/<int:form_id>", methods=["GET", "POST"])
@login_required
def review_form_page(form_id):
    db = get_db()
    form_row = db.execute(
        "SELECT * FROM lab_forms WHERE id = ?", (form_id,)
    ).fetchone()
    if form_row is None:
        abort(404)

    review = db.execute(
        "SELECT * FROM form_reviews WHERE lab_form_id = ?", (form_id,)
    ).fetchone()
    values = {}
    for stage in REVIEW_STAGES.values():
        for field in (stage["reviewer"], stage["reviewed_at"]):
            values[field] = review[field] if review else ""
    errors = {}

    if request.method == "POST":
        has_stage = False
        for stage_key, stage in REVIEW_STAGES.items():
            stage_values, stage_errors = validate_review_stage(
                request.form, stage_key
            )
            values[stage["reviewer"]] = stage_values["reviewer_name"]
            values[stage["reviewed_at"]] = stage_values["reviewed_at"]
            errors.update(stage_errors)
            if stage_values["reviewer_name"] or stage_values["reviewed_at"]:
                has_stage = True

        if not has_stage:
            errors["review"] = "أدخل بيانات مرحلة مراجعة واحدة على الأقل"
        if not errors:
            save_review_record(
                form_id,
                first_reviewer_name=values["first_reviewer_name"],
                first_reviewed_at=values["first_reviewed_at"],
                second_reviewer_name=values["second_reviewer_name"],
                second_reviewed_at=values["second_reviewed_at"],
            )
            pdf_result = ensure_delivery_pdf(db)
            set_delivery_notice(db, [form_id], pdf_result)
            return redirect(url_for("main.reviews_page", saved=1))

    return render_template(
        "review_form.html",
        form=lab_form_to_dict(form_row),
        review=review,
        values=values,
        errors=errors,
    )


@bp.get("/deliveries")
@login_required
@admin_required
def ebi_deliveries_page():
    db = get_db()
    user = current_session_user()
    eligible_forms = fetch_ebi_eligible_forms(db)
    combined_pdf = ensure_delivery_pdf(db)
    history = fetch_ebi_delivery_history(db)
    settings = ebi_api_settings()
    sent_id = request.args.get("sent", type=int)
    failed_id = request.args.get("failed", type=int)
    sent_delivery = fetch_ebi_delivery(db, sent_id) if sent_id else None
    failed_delivery = fetch_ebi_delivery(db, failed_id) if failed_id else None
    stats = {
        "eligible": len(eligible_forms),
        "delivered": db.execute(
            """
            SELECT COUNT(DISTINCT ef.lab_form_id) AS count
            FROM ebi_delivery_forms ef
            JOIN ebi_deliveries d ON d.id = ef.delivery_id
            WHERE d.status = 'delivered'
            """
        ).fetchone()["count"],
        "deliveries": db.execute(
            "SELECT COUNT(*) AS count FROM ebi_deliveries"
        ).fetchone()["count"],
        "failed": db.execute(
            "SELECT COUNT(*) AS count FROM ebi_deliveries WHERE status = 'failed'"
        ).fetchone()["count"],
    }
    values = {
        "recipient_name": "",
        "recipient_entity": "",
        "recipient_contact": "",
        "recipient_notes": "",
        "delivery_date": date.today().isoformat(),
        "delivered_by": user["username"] if user else "",
        "notes": "",
        "form_ids": [],
    }
    return render_template(
        "deliveries.html",
        eligible_forms=eligible_forms,
        combined_pdf=combined_pdf,
        history=history,
        settings=settings,
        stats=stats,
        values=values,
        errors={},
        sent_delivery=sent_delivery,
        failed_delivery=failed_delivery,
    )


@bp.get("/deliveries/pdf")
@login_required
@admin_required
def ebi_delivery_pdf():
    info = ensure_delivery_pdf(get_db())
    if not info.get("available"):
        abort(404)
    filename = clean_text(info.get("filename"))
    target = delivery_pdf_dir() / filename
    if Path(filename).name != filename or not target.is_file():
        abort(404)
    return send_file(
        target,
        mimetype="application/pdf",
        as_attachment=request.args.get("download") == "1",
        download_name=filename,
    )


@bp.post("/deliveries/pdf/regenerate")
@login_required
@admin_required
def ebi_delivery_pdf_regenerate():
    ensure_delivery_pdf(get_db(), force=True)
    return redirect(url_for("main.ebi_deliveries_page"))


@bp.post("/deliveries")
@login_required
@admin_required
def ebi_delivery_submit():
    db = get_db()
    user = current_session_user()
    selected_ids = []
    for raw_id in request.form.getlist("form_ids"):
        try:
            form_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if form_id not in selected_ids:
            selected_ids.append(form_id)

    values = {
        "recipient_name": clean_text(request.form.get("recipient_name")),
        "recipient_entity": clean_text(request.form.get("recipient_entity")),
        "recipient_contact": clean_text(request.form.get("recipient_contact")),
        "recipient_notes": clean_text(request.form.get("recipient_notes")),
        "delivery_date": clean_text(request.form.get("delivery_date")),
        "delivered_by": clean_text(request.form.get("delivered_by")),
        "notes": clean_text(request.form.get("notes")),
        "form_ids": selected_ids,
    }
    if not values["delivered_by"] and user:
        values["delivered_by"] = user["username"]

    eligible_forms = fetch_ebi_eligible_forms(db)
    combined_pdf = ensure_delivery_pdf(db)
    eligible_by_id = {row["id"]: row for row in eligible_forms}
    values, errors = validate_ebi_delivery(
        values, selected_ids, set(eligible_by_id)
    )
    settings = ebi_api_settings()
    if not settings["configured"]:
        errors["api"] = (
            "خدمة EBI غير مهيأة. اضبط EBI_API_URL وEBI_API_TOKEN أو "
            "EBI_API_KEY على الخادم قبل التسليم."
        )

    if errors:
        history = fetch_ebi_delivery_history(db)
        stats = {
            "eligible": len(eligible_forms),
            "delivered": db.execute(
                """
                SELECT COUNT(DISTINCT ef.lab_form_id) AS count
                FROM ebi_delivery_forms ef
                JOIN ebi_deliveries d ON d.id = ef.delivery_id
                WHERE d.status = 'delivered'
                """
            ).fetchone()["count"],
            "deliveries": db.execute(
                "SELECT COUNT(*) AS count FROM ebi_deliveries"
            ).fetchone()["count"],
            "failed": db.execute(
                "SELECT COUNT(*) AS count FROM ebi_deliveries "
                "WHERE status = 'failed'"
            ).fetchone()["count"],
        }
        return (
            render_template(
                "deliveries.html",
                eligible_forms=eligible_forms,
                combined_pdf=combined_pdf,
                history=history,
                settings=settings,
                stats=stats,
                values=values,
                errors=errors,
                sent_delivery=None,
                failed_delivery=None,
            ),
            400,
        )

    selected_forms = [eligible_by_id[form_id] for form_id in selected_ids]
    reference = new_ebi_reference()
    cursor = db.execute(
        """
        INSERT INTO ebi_deliveries (
            reference, recipient_name, recipient_entity, recipient_contact,
            recipient_notes, delivery_date, delivered_by, notes, status,
            form_count, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            reference,
            values["recipient_name"],
            values["recipient_entity"],
            values["recipient_contact"],
            values["recipient_notes"],
            values["delivery_date"],
            values["delivered_by"],
            values["notes"],
            len(selected_forms),
            user["username"] if user else "",
        ),
    )
    delivery_id = cursor.lastrowid
    for form in selected_forms:
        db.execute(
            """
            INSERT INTO ebi_delivery_forms (
                delivery_id, lab_form_id, lab_number, national_id, patient_name
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                delivery_id,
                form["id"],
                form["lab_number"],
                form["national_id"],
                form["patient_name"],
            ),
        )
    db.commit()

    delivery = fetch_ebi_delivery(db, delivery_id)
    payload = build_ebi_payload(delivery, selected_forms)
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    db.execute(
        """
        UPDATE ebi_deliveries
        SET request_payload = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (payload_text, delivery_id),
    )
    db.commit()

    try:
        response_status, response_body = send_ebi_payload(payload, settings)
    except EbiApiError as error:
        db.execute(
            """
            UPDATE ebi_deliveries
            SET status = 'failed', error_message = ?, response_status = ?,
                response_body = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(error), error.status, error.body[:200000], delivery_id),
        )
        db.commit()
        return redirect(url_for("main.ebi_deliveries_page", failed=delivery_id))

    db.execute(
        """
        UPDATE ebi_deliveries
        SET status = 'delivered', response_status = ?, response_body = ?,
            error_message = '', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (response_status, response_body[:200000], delivery_id),
    )
    db.commit()
    ensure_delivery_pdf(db)
    return redirect(url_for("main.ebi_deliveries_page", sent=delivery_id))


@bp.get("/deliveries/<int:delivery_id>")
@login_required
@admin_required
def ebi_delivery_detail(delivery_id):
    db = get_db()
    delivery = fetch_ebi_delivery(db, delivery_id)
    if delivery is None:
        abort(404)
    return render_template(
        "delivery_detail.html",
        delivery=delivery,
        forms=fetch_ebi_delivery_forms(db, delivery_id),
        payload_pretty=pretty_json(delivery["request_payload"]),
        response_pretty=pretty_json(delivery["response_body"]),
    )


@bp.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "المسار غير موجود"}), 404
    return "الصفحة غير موجودة", 404


@bp.errorhandler(405)
def method_not_allowed(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "طريقة الطلب غير مسموحة"}), 405
    return "طريقة الطلب غير مسموحة", 405


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "polio.db")),
        UPLOAD_DIR=os.environ.get("UPLOAD_PATH", str(BASE_DIR / "data" / "uploads")),
        REVIEWS_DIR=os.environ.get("REVIEWS_PATH", str(BASE_DIR / "data" / "reviews")),
        DELIVERY_PDF_DIR=os.environ.get(
            "DELIVERY_PDF_PATH", str(BASE_DIR / "data" / "deliveries")
        ),
        DELIVERY_PDF_ENABLED=os.environ.get("DELIVERY_PDF_ENABLED", "1").lower()
        not in {"0", "false", "no", "off"},
        DELIVERY_PDF_BROWSER=os.environ.get("DELIVERY_PDF_BROWSER", ""),
        DELIVERY_PDF_TIMEOUT=os.environ.get("DELIVERY_PDF_TIMEOUT", "60"),
        LOGOS_DIR=os.environ.get("LOGOS_PATH", str(BASE_DIR / "static" / "logos")),
        FIXED_IMAGES_DIR=os.environ.get("FIXED_IMAGES_PATH", str(BASE_DIR / "static" / "fixed")),
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
        SECRET_KEY=os.environ.get("SECRET_KEY", "polio-dev-secret-change-me"),
        AUTH_USERNAME=os.environ.get("AUTH_USERNAME", "admin"),
        AUTH_PASSWORD=os.environ.get("AUTH_PASSWORD", "polio1234"),
        EBI_API_URL=os.environ.get("EBI_API_URL", ""),
        EBI_API_TOKEN=os.environ.get("EBI_API_TOKEN", ""),
        EBI_API_KEY=os.environ.get("EBI_API_KEY", ""),
        EBI_API_TIMEOUT=os.environ.get("EBI_API_TIMEOUT", "20"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SEED_DEMO=True,
    )
    if test_config:
        app.config.update(test_config)
    if app.config.get("TESTING") and not (
        test_config and "DELIVERY_PDF_ENABLED" in test_config
    ):
        app.config["DELIVERY_PDF_ENABLED"] = False

    password = str(app.config.pop("AUTH_PASSWORD", "") or "")
    app.config["AUTH_PASSWORD_HASH"] = generate_password_hash(password)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["DELIVERY_PDF_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["LOGOS_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["FIXED_IMAGES_DIR"]).mkdir(parents=True, exist_ok=True)
    app.json.ensure_ascii = False
    app.teardown_appcontext(close_db)
    app.register_blueprint(bp)
    app.jinja_env.filters["datetime_ar"] = format_datetime_ar

    @app.context_processor
    def inject_form_options():
        logos_right, logos_left = logo_slots()
        user = current_session_user()
        return {
            "FORM_RESULTS": FORM_RESULTS,
            "FORM_CONDITIONS": FORM_CONDITIONS,
            "FORM_POSITIONS": FORM_POSITIONS,
            "GOVERNORATES": GOVERNORATES,
            "EBI_DELIVERY_STATUSES": EBI_DELIVERY_STATUSES,
            "logos_right": logos_right,
            "logos_left": logos_left,
            "fixed_stamp": fixed_image("stamp"),
            "fixed_signature": fixed_image("signature"),
            "current_user": user["username"] if user else None,
            "current_user_role": user["role"] if user else None,
        }

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    with app.app_context():
        init_db()
        if app.config.get("SEED_DEMO", True):
            seed_db()
        seed_admin_user()

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
