import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app


class NewUserTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database = root / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database),
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

    def create_user(self, **overrides):
        payload = {
            "username": "lab.user",
            "password": "StrongPass9",
            "password_confirm": "StrongPass9",
            "role": "user",
            **overrides,
        }
        return self.client.post("/users/new", data=payload)

    def user_id(self, username):
        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
        self.assertIsNotNone(row)
        return row[0]

    def test_new_user_page_renders(self):
        response = self.client.get("/users/new")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("إنشاء حساب جديد", page)
        self.assertIn('name="username"', page)
        self.assertIn('name="password_confirm"', page)

    def test_admin_sees_user_management_links(self):
        page = self.client.get("/forms").get_data(as_text=True)
        self.assertIn('href="/users/new"', page)
        self.assertIn('href="/users"', page)
        self.assertIn("إضافة مستخدم", page)
        self.assertIn("إدارة المستخدمين", page)

    def test_new_user_page_requires_login(self):
        self.client.post("/logout")
        response = self.client.get("/users/new")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_create_user_and_login_with_it(self):
        response = self.create_user()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/users?created=lab.user", response.headers["Location"])

        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("تم إنشاء المستخدم", page)
        self.assertIn("lab.user", page)

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT password_hash, role FROM users WHERE username = ?",
                ("lab.user",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row[0], "StrongPass9")
        self.assertEqual(row[1], "user")

        self.client.post("/logout")
        login = self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get("/forms").status_code, 200)

    def test_duplicate_username_is_rejected_case_insensitively(self):
        self.assertEqual(self.create_user(username="Lab.User").status_code, 302)
        duplicate = self.create_user(username="lab.user")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("مستخدم بالفعل", duplicate.get_data(as_text=True))

    def test_invalid_passwords_are_rejected(self):
        weak = self.create_user(password="short", password_confirm="short")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("8 أحرف", weak.get_data(as_text=True))

        mismatch = self.create_user(password_confirm="DifferentPass9")
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("غير متطابقتين", mismatch.get_data(as_text=True))

    def test_invalid_username_is_rejected(self):
        response = self.create_user(username="اسم به مسافات")
        self.assertEqual(response.status_code, 400)
        self.assertIn("بدون مسافات", response.get_data(as_text=True))

    def test_invalid_role_is_rejected(self):
        response = self.create_user(role="owner")
        self.assertEqual(response.status_code, 400)
        self.assertIn("الدور المحدد غير صالح", response.get_data(as_text=True))

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ?", ("lab.user",)
            ).fetchone()
        self.assertIsNone(row)

    def test_admin_can_create_manager(self):
        response = self.create_user(username="manager", role="admin")
        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT role FROM users WHERE username = ?", ("manager",)
            ).fetchone()
        self.assertEqual(row[0], "admin")

        self.client.post("/logout")
        login = self.client.post(
            "/api/login",
            json={"username": "manager", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get("/users").status_code, 200)

        page = self.client.get("/forms").get_data(as_text=True)
        self.assertIn('href="/users"', page)
        self.assertIn("إدارة المستخدمين", page)

    def test_new_user_role_dropdown_has_ministry_option(self):
        page = self.client.get("/users/new").get_data(as_text=True)
        self.assertIn('value="moh"', page)
        self.assertIn("وزارة الصحة — وصول لصفحة وزارة الصحة فقط", page)

    def test_admin_can_create_ministry_user(self):
        response = self.create_user(username="moh.user", role="moh")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/users?created=moh.user", response.headers["Location"])

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT role FROM users WHERE username = ?", ("moh.user",)
            ).fetchone()
        self.assertEqual(row[0], "moh")

        page = self.client.get("/users").get_data(as_text=True)
        self.assertIn("moh.user", page)
        self.assertIn("وزارة الصحة", page)

    def test_ministry_user_is_restricted_to_ministry_page(self):
        self.create_user(username="moh.user", role="moh")
        self.client.post("/logout")
        login = self.client.post(
            "/api/login",
            json={"username": "moh.user", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.get_json()["redirect"], "/ministry-of-health")

        page = self.client.get("/ministry-of-health")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("حساب وزارة الصحة", html)
        self.assertIn('href="/ministry-of-health"', html)
        self.assertNotIn('href="/forms"', html)
        self.assertNotIn('href="/users"', html)
        self.assertNotIn('href="/deliveries"', html)
        self.assertNotIn("إدارة المستخدمين", html)
        self.assertNotIn("استمارة جديدة", html)

        for path in (
            "/forms",
            "/forms/new",
            "/reviews",
            "/deliveries",
            "/users",
            "/users/new",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertEqual(response.headers["Location"], "/ministry-of-health", path)

        self.assertEqual(self.client.get("/api/forms").status_code, 403)
        self.assertEqual(self.client.get("/api/health").status_code, 403)
        self.assertEqual(self.client.post("/deliveries", data={}).status_code, 403)

    def test_ministry_user_is_sent_to_ministry_page_on_login(self):
        self.create_user(username="moh.user", role="moh")
        self.client.post("/logout")

        form_login = self.client.post(
            "/login", data={"username": "moh.user", "password": "StrongPass9"}
        )
        self.assertEqual(form_login.status_code, 302)
        self.assertTrue(form_login.headers["Location"].endswith("/ministry-of-health"))

        index = self.client.get("/")
        self.assertEqual(index.status_code, 302)
        self.assertEqual(index.headers["Location"], "/ministry-of-health")

        login_get = self.client.get("/login")
        self.assertEqual(login_get.status_code, 302)
        self.assertEqual(login_get.headers["Location"], "/ministry-of-health")

    def test_regular_user_sidebar_hides_management_links(self):
        self.create_user()
        self.client.post("/logout")
        self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )

        page = self.client.get("/forms").get_data(as_text=True)
        self.assertNotIn('href="/users"', page)
        self.assertNotIn('href="/users/new"', page)
        self.assertNotIn("إدارة المستخدمين", page)
        self.assertNotIn("إضافة مستخدم", page)

    def test_regular_user_cannot_access_management_routes(self):
        self.create_user()
        tester_id = self.user_id("tester")
        self.client.post("/logout")
        self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )

        page = self.client.get("/users")
        self.assertEqual(page.status_code, 403)
        self.assertIn("متاحة للمديرين فقط", page.get_data(as_text=True))

        self.assertEqual(self.client.get("/users/new").status_code, 403)
        self.assertEqual(
            self.client.get(f"/users/{tester_id}/password").status_code, 403
        )
        self.assertEqual(
            self.client.post(f"/users/{tester_id}/delete").status_code, 403
        )

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ?", ("tester",)
            ).fetchone()
        self.assertIsNotNone(row)

    def test_users_page_lists_accounts(self):
        self.create_user()
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("سجل المستخدمين", page)
        self.assertIn("lab.user", page)
        self.assertIn("tester", page)
        self.assertIn("أنت", page)
        self.assertIn("مدير", page)
        self.assertIn("مستخدم", page)
        self.assertIn("تعديل كلمة المرور", page)
        self.assertIn("حذف", page)

    def test_users_page_requires_login(self):
        self.client.post("/logout")
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_edit_password_page_renders(self):
        self.create_user()
        response = self.client.get(f"/users/{self.user_id('lab.user')}/password")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("إعادة تعيين كلمة المرور", page)
        self.assertIn("lab.user", page)
        self.assertIn('name="password"', page)
        self.assertIn('name="password_confirm"', page)

    def test_edit_password_updates_login_credentials(self):
        self.create_user()
        user_id = self.user_id("lab.user")
        response = self.client.post(
            f"/users/{user_id}/password",
            data={"password": "NewStrongPass9", "password_confirm": "NewStrongPass9"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/users?updated=lab.user", response.headers["Location"])

        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("تم تحديث كلمة مرور المستخدم", page)

        self.client.post("/logout")
        old_login = self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )
        self.assertEqual(old_login.status_code, 401)

        new_login = self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "NewStrongPass9"},
        )
        self.assertEqual(new_login.status_code, 200)

    def test_edit_password_validation(self):
        self.create_user()
        user_id = self.user_id("lab.user")

        weak = self.client.post(
            f"/users/{user_id}/password",
            data={"password": "short", "password_confirm": "short"},
        )
        self.assertEqual(weak.status_code, 400)
        self.assertIn("8 أحرف", weak.get_data(as_text=True))

        mismatch = self.client.post(
            f"/users/{user_id}/password",
            data={"password": "NewStrongPass9", "password_confirm": "DifferentPass9"},
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("غير متطابقتين", mismatch.get_data(as_text=True))

        self.client.post("/logout")
        login = self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)

    def test_missing_user_password_page_returns_404(self):
        response = self.client.get("/users/9999/password")
        self.assertEqual(response.status_code, 404)

    def test_delete_user(self):
        self.create_user()
        user_id = self.user_id("lab.user")
        response = self.client.post(f"/users/{user_id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/users?deleted=lab.user", response.headers["Location"])

        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("تم حذف المستخدم", page)
        self.assertNotIn(f'href="/users/{user_id}/password"', page)

        self.client.post("/logout")
        login = self.client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 401)

    def test_deleted_user_session_is_revoked(self):
        self.create_user()
        user_id = self.user_id("lab.user")
        lab_client = self.app.test_client()
        login = lab_client.post(
            "/api/login",
            json={"username": "lab.user", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(lab_client.get("/forms").status_code, 200)

        self.client.post(f"/users/{user_id}/delete")

        response = lab_client.get("/forms")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_cannot_delete_current_user(self):
        user_id = self.user_id("tester")
        response = self.client.post(f"/users/{user_id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/users?error=self", response.headers["Location"])

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ?", ("tester",)
            ).fetchone()
        self.assertIsNotNone(row)

    def test_delete_missing_user(self):
        response = self.client.post("/users/9999/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/users?error=notfound", response.headers["Location"])

    def test_delete_requires_login(self):
        self.client.post("/logout")
        response = self.client.post(f"/users/{self.user_id('tester')}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


class UserRoleMigrationTestCase(unittest.TestCase):
    def test_existing_users_get_role_and_configured_admin_is_promoted(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        database = root / "legacy.db"

        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                ("tester", generate_password_hash("secret123")),
            )
            connection.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                ("lab.user", generate_password_hash("StrongPass9")),
            )

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

        with sqlite3.connect(database) as connection:
            roles = dict(
                connection.execute("SELECT username, role FROM users").fetchall()
            )
        self.assertEqual(roles["tester"], "admin")
        self.assertEqual(roles["lab.user"], "user")

        client = app.test_client()
        login = client.post(
            "/api/login",
            json={"username": "tester", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/users").status_code, 200)

    def test_legacy_role_check_is_rebuilt_to_allow_ministry_role(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        database = root / "legacy-check.db"

        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                ("tester", generate_password_hash("secret123")),
            )

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

        with sqlite3.connect(database) as connection:
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'moh')",
                ("moh.legacy", generate_password_hash("StrongPass9")),
            )
            connection.commit()
            role = connection.execute(
                "SELECT role FROM users WHERE username = ?", ("moh.legacy",)
            ).fetchone()[0]

        self.assertIn("'moh'", table_sql)
        self.assertEqual(role, "moh")

        client = app.test_client()
        login = client.post(
            "/api/login",
            json={"username": "moh.legacy", "password": "StrongPass9"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.get_json()["redirect"], "/ministry-of-health")
        self.assertEqual(client.get("/ministry-of-health").status_code, 200)
        self.assertEqual(client.get("/forms").status_code, 302)


if __name__ == "__main__":
    unittest.main()
