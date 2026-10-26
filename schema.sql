CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    national_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    mother_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    governorate TEXT NOT NULL,
    center TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT 'male' CHECK (gender IN ('male', 'female')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'vaccinated', 'deferred')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_children_status ON children (status);
CREATE INDEX IF NOT EXISTS idx_children_governorate ON children (governorate);
CREATE INDEX IF NOT EXISTS idx_children_name ON children (name);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lab_forms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    national_id TEXT NOT NULL DEFAULT '',
    contact_number TEXT NOT NULL DEFAULT '',
    lab_number TEXT NOT NULL DEFAULT '',
    patient_name TEXT NOT NULL DEFAULT '',
    age_months TEXT NOT NULL DEFAULT '',
    age_years TEXT NOT NULL DEFAULT '',
    illness_date TEXT NOT NULL DEFAULT '',
    center TEXT NOT NULL DEFAULT '',
    governorate TEXT NOT NULL DEFAULT '',
    sample_condition TEXT NOT NULL DEFAULT 'جيدة',
    sample1_collect_date TEXT NOT NULL DEFAULT '',
    sample1_receive_date TEXT NOT NULL DEFAULT '',
    sample1_l20b TEXT NOT NULL DEFAULT 'سلبي',
    sample1_prelim_date TEXT NOT NULL DEFAULT '',
    sample1_final TEXT NOT NULL DEFAULT 'سلبي',
    sample1_final_date TEXT NOT NULL DEFAULT '',
    sample2_collect_date TEXT NOT NULL DEFAULT '',
    sample2_receive_date TEXT NOT NULL DEFAULT '',
    sample2_l20b TEXT NOT NULL DEFAULT '',
    sample2_prelim_date TEXT NOT NULL DEFAULT '',
    sample2_final TEXT NOT NULL DEFAULT '',
    sample2_final_date TEXT NOT NULL DEFAULT '',
    stamp_image TEXT NOT NULL DEFAULT '',
    signature_image TEXT NOT NULL DEFAULT '',
    signatory_name TEXT NOT NULL DEFAULT 'ك/ أميرة يحيى زغلول',
    show_stamp INTEGER NOT NULL DEFAULT 1,
    show_signature INTEGER NOT NULL DEFAULT 1,
    stamp_position TEXT NOT NULL DEFAULT 'left',
    signature_position TEXT NOT NULL DEFAULT 'left',
    notes TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS form_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_form_id INTEGER NOT NULL UNIQUE,
    first_reviewer_name TEXT NOT NULL DEFAULT '',
    first_reviewed_at TEXT NOT NULL DEFAULT '',
    second_reviewer_name TEXT NOT NULL DEFAULT '',
    second_reviewed_at TEXT NOT NULL DEFAULT '',
    pdf_path TEXT NOT NULL DEFAULT '',
    folder_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivery_queued_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (lab_form_id) REFERENCES lab_forms (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ebi_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL UNIQUE,
    recipient_name TEXT NOT NULL,
    recipient_entity TEXT NOT NULL DEFAULT '',
    recipient_contact TEXT NOT NULL DEFAULT '',
    recipient_notes TEXT NOT NULL DEFAULT '',
    delivery_date TEXT NOT NULL,
    delivered_by TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'failed')),
    form_count INTEGER NOT NULL DEFAULT 0,
    request_payload TEXT NOT NULL DEFAULT '',
    response_status INTEGER,
    response_body TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ebi_delivery_forms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id INTEGER NOT NULL,
    lab_form_id INTEGER,
    lab_number TEXT NOT NULL DEFAULT '',
    national_id TEXT NOT NULL DEFAULT '',
    patient_name TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (delivery_id) REFERENCES ebi_deliveries (id) ON DELETE CASCADE,
    FOREIGN KEY (lab_form_id) REFERENCES lab_forms (id) ON DELETE SET NULL,
    UNIQUE (delivery_id, lab_form_id)
);

CREATE INDEX IF NOT EXISTS idx_lab_forms_patient ON lab_forms (patient_name);
CREATE INDEX IF NOT EXISTS idx_lab_forms_lab_number ON lab_forms (lab_number);
CREATE INDEX IF NOT EXISTS idx_ebi_deliveries_created_at ON ebi_deliveries (created_at);
CREATE INDEX IF NOT EXISTS idx_ebi_delivery_forms_delivery ON ebi_delivery_forms (delivery_id);
CREATE INDEX IF NOT EXISTS idx_ebi_delivery_forms_form ON ebi_delivery_forms (lab_form_id);
