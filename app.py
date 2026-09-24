
from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any

import qrcode
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "meditrack.db"))
QR_ROOT = BASE_DIR / "static" / "qrcodes"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


LOCATIONS = [
    ("LOC-MAIN-ASSET-STORE", "Main Asset Store", "Administration", "asset_store"),
    ("LOC-WHEELCHAIR-PARKING", "Main Wheelchair Parking", "Administration", "parking_station"),
    ("LOC-MAIN-ENTRANCE", "Main Hospital Entrance", "Administration", "entrance"),
    ("LOC-EMERGENCY", "Emergency Room", "Emergency", "room"),
    ("LOC-ICU-01", "ICU 1", "Intensive Care Unit", "room"),
    ("LOC-ICU-02", "ICU 2", "Intensive Care Unit", "room"),
    ("LOC-NICU", "NICU", "Neonatal Intensive Care Unit", "room"),
    ("LOC-CCU", "CCU", "Critical Care Unit", "room"),
    ("LOC-OT-01", "Operation Theatre 1", "Operation Theatre", "room"),
    ("LOC-OT-02", "Operation Theatre 2", "Operation Theatre", "room"),
    ("LOC-WARD-01", "General Ward 1", "General Ward", "room"),
    ("LOC-WARD-02", "General Ward 2", "General Ward", "room"),
    ("LOC-OPD", "Outpatient Department", "OP Department", "room"),
    ("LOC-PHARMACY", "Pharmacy", "Pharmacy", "room"),
    ("LOC-LAB", "Laboratory", "Laboratory", "room"),
    ("LOC-RADIOLOGY", "Radiology Room", "Radiology", "room"),
    ("LOC-BLOOD-BANK", "Blood Bank", "Blood Bank", "room"),
    ("LOC-DIALYSIS", "Dialysis Room", "Dialysis", "room"),
    ("LOC-PHYSIOTHERAPY", "Physiotherapy Room", "Physiotherapy", "room"),
    ("LOC-AMBULANCE-BAY", "Ambulance Parking Bay", "Ambulance", "parking_station"),
    ("LOC-MAINTENANCE", "Maintenance Room", "Maintenance", "maintenance"),
]

ASSET_TYPES = [
    ("Patient Transport", "Wheelchair", "WC", 2, 10, 5, "LOC-WHEELCHAIR-PARKING"),
    ("Respiratory Equipment", "Oxygen Cylinder", "OXY", 2, 30, 5, "LOC-MAIN-ASSET-STORE"),
    ("Patient Transport", "Patient Stretcher", "STR", 2, 10, 5, "LOC-MAIN-ASSET-STORE"),
    ("Infusion Equipment", "Infusion Pump", "IP", 2, 60, 5, "LOC-MAIN-ASSET-STORE"),
    ("Patient Monitoring", "Portable Patient Monitor", "PPM", 2, 60, 5, "LOC-MAIN-ASSET-STORE"),
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def make_qr(value: str, relative_path: str) -> None:
    output = BASE_DIR / "static" / relative_path
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        return
    img = qrcode.make(value)
    img.save(output)


def init_db() -> None:
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL COLLATE NOCASE,
            employee_name TEXT NOT NULL,
            department TEXT NOT NULL,
            phone_number TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('staff','office','management')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            location_type TEXT NOT NULL,
            qr_value TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS asset_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            name TEXT UNIQUE NOT NULL,
            code TEXT UNIQUE NOT NULL,
            minimum_available INTEGER NOT NULL DEFAULT 1,
            return_minutes INTEGER NOT NULL DEFAULT 10
        );

        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_uid TEXT UNIQUE NOT NULL,
            qr_value TEXT UNIQUE NOT NULL,
            asset_type_id INTEGER NOT NULL,
            current_location_id INTEGER,
            holder_id INTEGER,
            status TEXT NOT NULL DEFAULT 'available'
                CHECK(status IN ('available','in_use','return_requested','delayed','maintenance','missing','inactive')),
            condition_status TEXT NOT NULL DEFAULT 'good',
            taken_at TEXT,
            expected_return_at TEXT,
            last_returned_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(asset_type_id) REFERENCES asset_types(id),
            FOREIGN KEY(current_location_id) REFERENCES locations(id),
            FOREIGN KEY(holder_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            employee_id INTEGER,
            action TEXT NOT NULL,
            from_location_id INTEGER,
            to_location_id INTEGER,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(asset_id) REFERENCES assets(id),
            FOREIGN KEY(employee_id) REFERENCES users(id),
            FOREIGN KEY(from_location_id) REFERENCES locations(id),
            FOREIGN KEY(to_location_id) REFERENCES locations(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_user_id INTEGER,
            receiver_role TEXT,
            subject TEXT,
            message_text TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal',
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS emergency_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reported_by INTEGER NOT NULL,
            emergency_type TEXT NOT NULL,
            location_code TEXT,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT,
            FOREIGN KEY(reported_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS emergency_acknowledgements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emergency_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(emergency_id, user_id),
            FOREIGN KEY(emergency_id) REFERENCES emergency_alerts(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role_target TEXT,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            reference_id INTEGER,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS return_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            request_order INTEGER NOT NULL,
            response TEXT NOT NULL DEFAULT 'pending',
            need_reason TEXT,
            promised_return_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            responded_at TEXT,
            FOREIGN KEY(asset_id) REFERENCES assets(id),
            FOREIGN KEY(employee_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS maintenance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            reported_by INTEGER,
            issue_description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'reported',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY(asset_id) REFERENCES assets(id),
            FOREIGN KEY(reported_by) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
        CREATE INDEX IF NOT EXISTS idx_assets_holder ON assets(holder_id);
        CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at);
        CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver_user_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
        """
    )

    if conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO locations(code,name,department,location_type,qr_value) VALUES(?,?,?,?,?)",
            [(code, name, dept, kind, f"LOCATION:{code.removeprefix('LOC-')}") for code, name, dept, kind in LOCATIONS],
        )

    if conn.execute("SELECT COUNT(*) FROM asset_types").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO asset_types(category,name,code,minimum_available,return_minutes) VALUES(?,?,?,?,?)",
            [(cat, name, code, minimum, minutes) for cat, name, code, minimum, minutes, _qty, _loc in ASSET_TYPES],
        )

    if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
        location_map = {row["code"]: row["id"] for row in conn.execute("SELECT id,code FROM locations")}
        type_map = {row["code"]: row["id"] for row in conn.execute("SELECT id,code FROM asset_types")}
        rows = []
        for _cat, _name, code, _min, _mins, quantity, location_code in ASSET_TYPES:
            for number in range(1, quantity + 1):
                uid = f"{code}-{number:03d}"
                rows.append((uid, f"ASSET:{uid}", type_map[code], location_map[location_code]))
        conn.executemany(
            "INSERT INTO assets(asset_uid,qr_value,asset_type_id,current_location_id) VALUES(?,?,?,?)",
            rows,
        )
    conn.commit()

    for row in conn.execute("SELECT code,qr_value FROM locations"):
        make_qr(row["qr_value"], f"qrcodes/locations/{row['code']}.png")
    for row in conn.execute("SELECT asset_uid,qr_value FROM assets"):
        make_qr(row["qr_value"], f"qrcodes/assets/{row['asset_uid']}.png")
    conn.close()


def users_exist() -> bool:
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count > 0


def current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
    conn.close()
    return user


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("home"))
            if user["role"] not in roles:
                flash("You do not have permission to open that page.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def dashboard_url_for_role(role: str) -> str:
    return {
        "staff": url_for("staff_dashboard"),
        "office": url_for("office_dashboard"),
        "management": url_for("management_dashboard"),
    }[role]


def create_notification(
    conn: sqlite3.Connection,
    *,
    title: str,
    message: str,
    notification_type: str,
    user_id: int | None = None,
    role_target: str | None = None,
    reference_id: int | None = None,
) -> None:
    conn.execute(
        """INSERT INTO notifications
           (user_id,role_target,notification_type,title,message,reference_id)
           VALUES(?,?,?,?,?,?)""",
        (user_id, role_target, notification_type, title, message, reference_id),
    )


def asset_counts(conn: sqlite3.Connection, type_id: int) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) AS available,
            COUNT(*) AS total
        FROM assets WHERE asset_type_id=?
        """,
        (type_id,),
    ).fetchone()
    return int(row["available"] or 0), int(row["total"] or 0)


def ensure_return_requests(conn: sqlite3.Connection, type_id: int) -> None:
    type_row = conn.execute("SELECT * FROM asset_types WHERE id=?", (type_id,)).fetchone()
    if not type_row:
        return
    available, _total = asset_counts(conn, type_id)
    if available >= type_row["minimum_available"]:
        conn.execute(
            """UPDATE return_requests SET response='expired'
               WHERE response IN ('pending','returning')
               AND asset_id IN (SELECT id FROM assets WHERE asset_type_id=?)""",
            (type_id,),
        )
        return

    active_count = conn.execute(
        """SELECT COUNT(*) FROM return_requests rr
           JOIN assets a ON a.id=rr.asset_id
           WHERE a.asset_type_id=? AND rr.response IN ('pending','returning')""",
        (type_id,),
    ).fetchone()[0]

    slots = max(0, 1 - active_count)
    if slots == 0:
        return

    candidates = conn.execute(
        """
        SELECT a.id AS asset_id, a.holder_id, a.asset_uid, a.taken_at
        FROM assets a
        WHERE a.asset_type_id=?
          AND a.holder_id IS NOT NULL
          AND a.status IN ('in_use','return_requested','delayed')
          AND NOT EXISTS (
              SELECT 1 FROM return_requests rr
              WHERE rr.asset_id=a.id AND rr.response IN ('pending','need','returning')
          )
        ORDER BY datetime(a.taken_at) ASC
        LIMIT ?
        """,
        (type_id, slots),
    ).fetchall()

    order_start = active_count + 1
    for offset, row in enumerate(candidates):
        cursor = conn.execute(
            """INSERT INTO return_requests(asset_id,employee_id,request_order)
               VALUES(?,?,?)""",
            (row["asset_id"], row["holder_id"], order_start + offset),
        )
        create_notification(
            conn,
            user_id=row["holder_id"],
            notification_type="return_request",
            title=f"{type_row['name']} availability is low",
            message=(
                f"Only {available} {type_row['name']} item(s) are currently available. "
                f"Do you still need {row['asset_uid']}?"
            ),
            reference_id=cursor.lastrowid,
        )


def mark_overdue_returns(conn: sqlite3.Connection) -> None:
    overdue = conn.execute(
        """
        SELECT rr.id,rr.asset_id,rr.employee_id,a.asset_uid
        FROM return_requests rr
        JOIN assets a ON a.id=rr.asset_id
        WHERE rr.response='returning'
          AND rr.promised_return_at IS NOT NULL
          AND datetime(rr.promised_return_at) < datetime('now','localtime')
        """
    ).fetchall()
    for row in overdue:
        conn.execute("UPDATE assets SET status='delayed',updated_at=? WHERE id=?", (now_iso(), row["asset_id"]))
        create_notification(
            conn,
            role_target="office",
            notification_type="delayed_return",
            title="Delayed asset return",
            message=f"{row['asset_uid']} was not returned within the promised time.",
            reference_id=row["id"],
        )


@app.before_request
def prepare_app() -> None:
    init_db()
    if request.endpoint and request.endpoint.startswith("static"):
        return
    if not users_exist() and request.endpoint not in {"setup", "health"}:
        return redirect(url_for("setup"))


@app.context_processor
def inject_user() -> dict[str, Any]:
    return {"logged_user": current_user()}


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if users_exist():
        return redirect(url_for("home"))
    if request.method == "POST":
        office_id = request.form.get("office_id", "").strip()
        office_name = request.form.get("office_name", "").strip()
        office_password = request.form.get("office_password", "")
        management_id = request.form.get("management_id", "").strip()
        management_name = request.form.get("management_name", "").strip()
        management_password = request.form.get("management_password", "")
        if not all([office_id, office_name, office_password, management_id, management_name, management_password]):
            flash("Complete every required field.", "danger")
            return render_template("setup.html")
        if len(office_password) < 8 or len(management_password) < 8:
            flash("Use passwords with at least 8 characters.", "danger")
            return render_template("setup.html")
        conn = get_db()
        try:
            conn.execute(
                """INSERT INTO users(employee_id,employee_name,department,phone_number,password_hash,role)
                   VALUES(?,?,?,?,?,?)""",
                (office_id, office_name, "Administration", "", generate_password_hash(office_password), "office"),
            )
            conn.execute(
                """INSERT INTO users(employee_id,employee_name,department,phone_number,password_hash,role)
                   VALUES(?,?,?,?,?,?)""",
                (
                    management_id,
                    management_name,
                    "Administration",
                    "",
                    generate_password_hash(management_password),
                    "management",
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("The two IDs must be different.", "danger")
            return render_template("setup.html")
        finally:
            conn.close()
        flash("Initial accounts created. Sign in to continue.", "success")
        return redirect(url_for("home"))
    return render_template("setup.html")


@app.route("/")
def home():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("home.html")


@app.route("/login/<role>", methods=["GET", "POST"])
def login(role: str):
    if role not in {"staff", "office", "management"}:
        return redirect(url_for("home"))
    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE employee_id=? COLLATE NOCASE AND role=? AND active=1",
            (employee_id, role),
        ).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(dashboard_url_for_role(role))
        flash("Incorrect user ID, password or portal.", "danger")
    return render_template("login.html", role=role)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("home"))
    return redirect(dashboard_url_for_role(user["role"]))


@app.route("/staff")
@role_required("staff")
def staff_dashboard():
    user = current_user()
    conn = get_db()
    mark_overdue_returns(conn)
    assigned = conn.execute(
        """
        SELECT a.*,t.name AS type_name,l.name AS location_name
        FROM assets a
        JOIN asset_types t ON t.id=a.asset_type_id
        LEFT JOIN locations l ON l.id=a.current_location_id
        WHERE a.holder_id=? ORDER BY datetime(a.taken_at) DESC
        """,
        (user["id"],),
    ).fetchall()
    requests = conn.execute(
        """
        SELECT rr.*,a.asset_uid,t.name AS type_name
        FROM return_requests rr
        JOIN assets a ON a.id=rr.asset_id
        JOIN asset_types t ON t.id=a.asset_type_id
        WHERE rr.employee_id=? AND rr.response IN ('pending','returning')
        ORDER BY datetime(rr.created_at) DESC
        """,
        (user["id"],),
    ).fetchall()
    recent_notifications = conn.execute(
        """
        SELECT * FROM notifications
        WHERE (user_id=? OR role_target='all' OR role_target='staff')
        ORDER BY datetime(created_at) DESC LIMIT 10
        """,
        (user["id"],),
    ).fetchall()
    conn.commit()
    conn.close()
    return render_template(
        "staff_dashboard.html",
        assigned=assigned,
        return_requests=requests,
        notifications=recent_notifications,
    )


@app.route("/scan")
@role_required("staff", "office")
def scan():
    return render_template("scan.html")


def normalize_asset_code(raw: str) -> str:
    value = (raw or "").strip().upper()
    if value.startswith("ASSET:"):
        value = value.split(":", 1)[1]
    return value


@app.route("/asset/<asset_uid>", methods=["GET", "POST"])
@role_required("staff", "office")
def asset_detail(asset_uid: str):
    user = current_user()
    asset_uid = normalize_asset_code(asset_uid)
    conn = get_db()
    asset = conn.execute(
        """
        SELECT a.*,t.category,t.name AS type_name,t.return_minutes,t.minimum_available,
               l.name AS location_name,u.employee_name AS holder_name,u.employee_id AS holder_employee_id
        FROM assets a
        JOIN asset_types t ON t.id=a.asset_type_id
        LEFT JOIN locations l ON l.id=a.current_location_id
        LEFT JOIN users u ON u.id=a.holder_id
        WHERE a.asset_uid=? COLLATE NOCASE
        """,
        (asset_uid,),
    ).fetchone()
    if not asset:
        conn.close()
        flash("Asset QR code was not found.", "danger")
        return redirect(url_for("scan"))

    locations = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()

    if request.method == "POST":
        action = request.form.get("action")
        location_id = request.form.get("location_id", type=int)
        reason = request.form.get("reason", "").strip()
        refreshed = conn.execute("SELECT * FROM assets WHERE id=?", (asset["id"],)).fetchone()
        old_location = refreshed["current_location_id"]

        if action == "take":
            if refreshed["status"] != "available":
                flash("This asset is not available.", "danger")
            else:
                due = (datetime.now() + timedelta(minutes=asset["return_minutes"])).replace(microsecond=0).isoformat(sep=" ")
                conn.execute(
                    """UPDATE assets SET holder_id=?,status='in_use',current_location_id=?,
                       taken_at=?,expected_return_at=?,updated_at=? WHERE id=?""",
                    (user["id"], location_id or old_location, now_iso(), due, now_iso(), asset["id"]),
                )
                conn.execute(
                    """INSERT INTO transactions(asset_id,employee_id,action,from_location_id,to_location_id,reason)
                       VALUES(?,?,?,?,?,?)""",
                    (asset["id"], user["id"], "taken", old_location, location_id or old_location, reason),
                )
                ensure_return_requests(conn, asset["asset_type_id"])
                flash(f"{asset_uid} assigned successfully.", "success")

        elif action == "return":
            if refreshed["holder_id"] not in {user["id"], None} and user["role"] != "office":
                flash("This asset is assigned to another employee.", "danger")
            else:
                conn.execute(
                    """UPDATE assets SET holder_id=NULL,status='available',current_location_id=?,
                       taken_at=NULL,expected_return_at=NULL,last_returned_at=?,updated_at=? WHERE id=?""",
                    (location_id or old_location, now_iso(), now_iso(), asset["id"]),
                )
                conn.execute(
                    """UPDATE return_requests SET response='returned',responded_at=?
                       WHERE asset_id=? AND response IN ('pending','returning','need')""",
                    (now_iso(), asset["id"]),
                )
                conn.execute(
                    """INSERT INTO transactions(asset_id,employee_id,action,from_location_id,to_location_id,reason)
                       VALUES(?,?,?,?,?,?)""",
                    (asset["id"], user["id"], "returned", old_location, location_id or old_location, reason),
                )
                ensure_return_requests(conn, asset["asset_type_id"])
                flash(f"{asset_uid} returned successfully.", "success")

        elif action == "transfer":
            if refreshed["holder_id"] != user["id"] and user["role"] != "office":
                flash("Only the assigned employee or office can transfer this asset.", "danger")
            elif not location_id:
                flash("Select the new location.", "danger")
            else:
                conn.execute(
                    "UPDATE assets SET current_location_id=?,updated_at=? WHERE id=?",
                    (location_id, now_iso(), asset["id"]),
                )
                conn.execute(
                    """INSERT INTO transactions(asset_id,employee_id,action,from_location_id,to_location_id,reason)
                       VALUES(?,?,?,?,?,?)""",
                    (asset["id"], user["id"], "transferred", old_location, location_id, reason),
                )
                flash("Asset location updated.", "success")

        elif action == "damage":
            if not reason:
                flash("Describe the damage or problem.", "danger")
            else:
                conn.execute(
                    """UPDATE assets SET status='maintenance',condition_status='damaged',
                       holder_id=NULL,updated_at=? WHERE id=?""",
                    (now_iso(), asset["id"]),
                )
                conn.execute(
                    """INSERT INTO maintenance_records(asset_id,reported_by,issue_description)
                       VALUES(?,?,?)""",
                    (asset["id"], user["id"], reason),
                )
                conn.execute(
                    """INSERT INTO transactions(asset_id,employee_id,action,from_location_id,to_location_id,reason)
                       VALUES(?,?,?,?,?,?)""",
                    (asset["id"], user["id"], "maintenance_reported", old_location, old_location, reason),
                )
                create_notification(
                    conn,
                    role_target="office",
                    notification_type="maintenance",
                    title="Asset maintenance reported",
                    message=f"{asset_uid}: {reason}",
                    reference_id=asset["id"],
                )
                flash("Maintenance issue reported.", "success")

        conn.commit()
        conn.close()
        return redirect(url_for("asset_detail", asset_uid=asset_uid))

    transactions = conn.execute(
        """
        SELECT tr.*,u.employee_name AS employee_name,u.employee_id AS employee_code,
               fl.name AS from_location_name,tl.name AS to_location_name
        FROM transactions tr
        LEFT JOIN users u ON u.id=tr.employee_id
        LEFT JOIN locations fl ON fl.id=tr.from_location_id
        LEFT JOIN locations tl ON tl.id=tr.to_location_id
        WHERE tr.asset_id=?
        ORDER BY datetime(tr.created_at) DESC
        """,
        (asset["id"],),
    ).fetchall()
    maintenance_history = conn.execute(
        """
        SELECT mr.*,u.employee_name AS reported_by_name,u.employee_id AS reported_by_code
        FROM maintenance_records mr
        LEFT JOIN users u ON u.id=mr.reported_by
        WHERE mr.asset_id=?
        ORDER BY datetime(mr.created_at) DESC
        """,
        (asset["id"],),
    ).fetchall()
    return_history = conn.execute(
        """
        SELECT rr.*,u.employee_name AS employee_name,u.employee_id AS employee_code
        FROM return_requests rr
        LEFT JOIN users u ON u.id=rr.employee_id
        WHERE rr.asset_id=?
        ORDER BY datetime(rr.created_at) DESC
        """,
        (asset["id"],),
    ).fetchall()
    conn.close()
    return render_template(
        "asset_detail.html",
        asset=asset,
        locations=locations,
        transactions=transactions,
        maintenance_history=maintenance_history,
        return_history=return_history,
    )


@app.route("/return-request/<int:request_id>/respond", methods=["POST"])
@role_required("staff")
def respond_return_request(request_id: int):
    user = current_user()
    response_value = request.form.get("response")
    reason = request.form.get("reason", "").strip()
    conn = get_db()
    row = conn.execute(
        """
        SELECT rr.*,a.asset_type_id,a.asset_uid
        FROM return_requests rr JOIN assets a ON a.id=rr.asset_id
        WHERE rr.id=? AND rr.employee_id=?
        """,
        (request_id, user["id"]),
    ).fetchone()
    if not row:
        conn.close()
        flash("Return request was not found.", "danger")
        return redirect(url_for("staff_dashboard"))

    if response_value == "need":
        if not reason:
            conn.close()
            flash("Enter why the asset is still needed.", "danger")
            return redirect(url_for("staff_dashboard"))
        conn.execute(
            """UPDATE return_requests SET response='need',need_reason=?,responded_at=? WHERE id=?""",
            (reason, now_iso(), request_id),
        )
        ensure_return_requests(conn, row["asset_type_id"])
        flash("Your need has been recorded. The request will move to another user.", "success")
    elif response_value == "returning":
        promised = (datetime.now() + timedelta(minutes=10)).replace(microsecond=0).isoformat(sep=" ")
        conn.execute(
            """UPDATE return_requests SET response='returning',promised_return_at=?,responded_at=? WHERE id=?""",
            (promised, now_iso(), request_id),
        )
        conn.execute(
            "UPDATE assets SET status='return_requested',updated_at=? WHERE id=?",
            (now_iso(), row["asset_id"]),
        )
        flash("Return countdown started. Scan the asset at its parking location within 10 minutes.", "success")
    conn.commit()
    conn.close()
    return redirect(url_for("staff_dashboard"))


@app.route("/office")
@role_required("office")
def office_dashboard():
    conn = get_db()
    mark_overdue_returns(conn)
    summaries = conn.execute(
        """
        SELECT t.id,t.category,t.name,t.code,t.minimum_available,
               COUNT(a.id) AS total,
               SUM(CASE WHEN a.status='available' THEN 1 ELSE 0 END) AS available,
               SUM(CASE WHEN a.status IN ('in_use','return_requested','delayed') THEN 1 ELSE 0 END) AS in_use,
               SUM(CASE WHEN a.status='maintenance' THEN 1 ELSE 0 END) AS maintenance,
               SUM(CASE WHEN a.status='delayed' THEN 1 ELSE 0 END) AS delayed
        FROM asset_types t LEFT JOIN assets a ON a.asset_type_id=t.id
        GROUP BY t.id ORDER BY t.category,t.name
        """
    ).fetchall()
    employees = conn.execute(
        "SELECT * FROM users ORDER BY role,employee_name"
    ).fetchall()
    recent_messages = conn.execute(
        """
        SELECT m.*,u.employee_name AS sender_name,u.employee_id AS sender_employee_id
        FROM messages m JOIN users u ON u.id=m.sender_id
        WHERE m.receiver_role IN ('office','all') OR m.receiver_user_id=?
        ORDER BY datetime(m.created_at) DESC LIMIT 20
        """,
        (current_user()["id"],),
    ).fetchall()
    conn.commit()
    conn.close()
    return render_template(
        "office_dashboard.html",
        summaries=summaries,
        employees=employees,
        messages=recent_messages,
    )


@app.route("/office/employees/add", methods=["POST"])
@role_required("office")
def add_employee():
    employee_id = request.form.get("employee_id", "").strip()
    employee_name = request.form.get("employee_name", "").strip()
    department = request.form.get("department", "").strip()
    phone = request.form.get("phone_number", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "staff")
    if role not in {"staff", "office", "management"}:
        role = "staff"
    if not all([employee_id, employee_name, department, password]):
        flash("Complete the employee ID, name, department and password.", "danger")
        return redirect(url_for("office_dashboard"))
    if len(password) < 8:
        flash("Password must contain at least 8 characters.", "danger")
        return redirect(url_for("office_dashboard"))
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO users(employee_id,employee_name,department,phone_number,password_hash,role)
               VALUES(?,?,?,?,?,?)""",
            (employee_id, employee_name, department, phone, generate_password_hash(password), role),
        )
        conn.commit()
        flash("Employee account created.", "success")
    except sqlite3.IntegrityError:
        flash("That employee ID already exists.", "danger")
    finally:
        conn.close()
    return redirect(url_for("office_dashboard"))


@app.route("/office/assets/add", methods=["POST"])
@role_required("office")
def add_asset():
    category = request.form.get("category", "").strip()
    asset_name = request.form.get("asset_name", "").strip()
    type_code = re.sub(r"[^A-Z0-9]", "", request.form.get("type_code", "").upper().strip())[:8]
    asset_uid = normalize_asset_code(request.form.get("asset_uid", ""))
    location_id = request.form.get("location_id", type=int)
    minimum_available = request.form.get("minimum_available", type=int) or 2
    return_minutes = request.form.get("return_minutes", type=int) or 10

    if not all([category, asset_name, asset_uid, location_id]):
        flash("Complete the asset category, name, asset ID and location.", "danger")
        return redirect(url_for("assets_page"))

    if not type_code:
        type_code = re.sub(r"[^A-Z0-9]", "", asset_name.upper())[:6]
    if not type_code:
        type_code = "AST"

    conn = get_db()
    try:
        asset_type = conn.execute(
            "SELECT * FROM asset_types WHERE name=? COLLATE NOCASE",
            (asset_name,),
        ).fetchone()
        if asset_type:
            type_id = asset_type["id"]
            conn.execute(
                "UPDATE asset_types SET category=?, code=?, minimum_available=?, return_minutes=? WHERE id=?",
                (category, type_code, minimum_available, return_minutes, type_id),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO asset_types(category,name,code,minimum_available,return_minutes)
                   VALUES(?,?,?,?,?)""",
                (category, asset_name, type_code, minimum_available, return_minutes),
            )
            type_id = cursor.lastrowid

        conn.execute(
            """INSERT INTO assets(asset_uid,qr_value,asset_type_id,current_location_id)
               VALUES(?,?,?,?)""",
            (asset_uid, f"ASSET:{asset_uid}", type_id, location_id),
        )
        conn.commit()
        make_qr(f"ASSET:{asset_uid}", f"qrcodes/assets/{asset_uid}.png")
        flash("Asset registered and QR code generated.", "success")
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("That asset name, code or asset ID already exists.", "danger")
    finally:
        conn.close()
    return redirect(url_for("assets_page"))


@app.route("/office/assets")
@role_required("office")
def assets_page():
    conn = get_db()
    assets = conn.execute(
        """
        SELECT a.*,t.name AS type_name,t.category,l.name AS location_name,
               u.employee_name AS holder_name,u.employee_id AS holder_employee_id
        FROM assets a JOIN asset_types t ON t.id=a.asset_type_id
        LEFT JOIN locations l ON l.id=a.current_location_id
        LEFT JOIN users u ON u.id=a.holder_id
        ORDER BY t.category,t.name,a.asset_uid
        """
    ).fetchall()
    types = conn.execute("SELECT * FROM asset_types ORDER BY category,name").fetchall()
    locations = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    conn.close()
    return render_template("assets.html", assets=assets, asset_types=types, locations=locations)


@app.route("/office/qrcodes")
@role_required("office")
def qrcodes_page():
    conn = get_db()
    assets = conn.execute(
        "SELECT asset_uid,qr_value FROM assets ORDER BY asset_uid"
    ).fetchall()
    locations = conn.execute(
        "SELECT code,name,qr_value FROM locations ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("qrcodes.html", assets=assets, locations=locations)


@app.route("/management")
@role_required("management")
def management_dashboard():
    conn = get_db()
    totals = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(status='available') AS available,
               SUM(status IN ('in_use','return_requested','delayed')) AS in_use,
               SUM(status='maintenance') AS maintenance,
               SUM(status='missing') AS missing,
               SUM(status='delayed') AS delayed
        FROM assets
        """
    ).fetchone()
    categories = conn.execute(
        """
        SELECT t.category,
               COUNT(a.id) AS total,
               SUM(CASE WHEN a.status='available' THEN 1 ELSE 0 END) AS available,
               SUM(CASE WHEN a.status IN ('in_use','return_requested','delayed') THEN 1 ELSE 0 END) AS in_use
        FROM asset_types t LEFT JOIN assets a ON a.asset_type_id=t.id
        GROUP BY t.category ORDER BY t.category
        """
    ).fetchall()
    activity = conn.execute(
        """
        SELECT substr(created_at,1,13) AS hour,COUNT(*) AS total
        FROM transactions
        WHERE datetime(created_at) >= datetime('now','-48 hours')
        GROUP BY substr(created_at,1,13)
        ORDER BY hour
        """
    ).fetchall()
    emergencies = conn.execute(
        """
        SELECT e.*,u.employee_name,u.employee_id
        FROM emergency_alerts e JOIN users u ON u.id=e.reported_by
        ORDER BY datetime(e.created_at) DESC LIMIT 15
        """
    ).fetchall()
    conn.close()
    return render_template(
        "management_dashboard.html",
        totals=totals,
        categories=categories,
        activity=activity,
        emergencies=emergencies,
    )


@app.route("/messages", methods=["GET", "POST"])
@role_required("staff", "office", "management")
def messages():
    user = current_user()
    conn = get_db()
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message_text = request.form.get("message_text", "").strip()
        priority = request.form.get("priority", "normal")
        receiver_role = request.form.get("receiver_role")
        receiver_user_id = request.form.get("receiver_user_id", type=int)
        if user["role"] == "staff":
            receiver_role = "office"
            receiver_user_id = None
        if not message_text:
            flash("Enter a message.", "danger")
        else:
            conn.execute(
                """INSERT INTO messages
                   (sender_id,receiver_user_id,receiver_role,subject,message_text,priority)
                   VALUES(?,?,?,?,?,?)""",
                (user["id"], receiver_user_id, receiver_role, subject, message_text, priority),
            )
            conn.commit()
            flash("Message sent.", "success")

    inbox = conn.execute(
        """
        SELECT m.*,s.employee_name AS sender_name,s.employee_id AS sender_employee_id
        FROM messages m JOIN users s ON s.id=m.sender_id
        WHERE m.receiver_user_id=?
           OR m.receiver_role=?
           OR m.receiver_role='all'
        ORDER BY datetime(m.created_at) DESC LIMIT 50
        """,
        (user["id"], user["role"]),
    ).fetchall()
    sent = conn.execute(
        """
        SELECT m.*,u.employee_name AS receiver_name
        FROM messages m LEFT JOIN users u ON u.id=m.receiver_user_id
        WHERE m.sender_id=?
        ORDER BY datetime(m.created_at) DESC LIMIT 30
        """,
        (user["id"],),
    ).fetchall()
    recipients = conn.execute(
        "SELECT id,employee_id,employee_name,role FROM users WHERE active=1 ORDER BY role,employee_name"
    ).fetchall()
    conn.close()
    return render_template("messages.html", inbox=inbox, sent=sent, recipients=recipients)


@app.route("/emergency", methods=["GET", "POST"])
@role_required("staff", "office", "management")
def emergency():
    user = current_user()
    conn = get_db()
    if request.method == "POST":
        emergency_type = request.form.get("emergency_type", "").strip()
        location_code = request.form.get("location_code", "").strip()
        description = request.form.get("description", "").strip()
        if not emergency_type:
            flash("Select an emergency type.", "danger")
        else:
            description = description or "No additional details provided."
            cursor = conn.execute(
                """INSERT INTO emergency_alerts(reported_by,emergency_type,location_code,description)
                   VALUES(?,?,?,?)""",
                (user["id"], emergency_type, location_code, description),
            )
            emergency_id = cursor.lastrowid
            create_notification(
                conn,
                role_target="all",
                notification_type="emergency",
                title=f"EMERGENCY: {emergency_type}",
                message=description,
                reference_id=emergency_id,
            )
            conn.commit()
            flash("Emergency alert sent to all active users.", "success")
            return redirect(url_for("dashboard"))

    active = conn.execute(
        """
        SELECT e.*,u.employee_name,u.employee_id
        FROM emergency_alerts e JOIN users u ON u.id=e.reported_by
        WHERE e.status='active' ORDER BY datetime(e.created_at) DESC
        """
    ).fetchall()
    locations = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    conn.close()
    return render_template("emergency.html", active=active, locations=locations)


@app.route("/emergency/<int:emergency_id>/ack", methods=["POST"])
@role_required("staff", "office", "management")
def acknowledge_emergency(emergency_id: int):
    user = current_user()
    response_value = request.form.get("response", "cleared")
    if response_value not in {"cleared", "need_help"}:
        response_value = "cleared"
    conn = get_db()
    conn.execute(
        """
        INSERT INTO emergency_acknowledgements(emergency_id,user_id,response)
        VALUES(?,?,?)
        ON CONFLICT(emergency_id,user_id)
        DO UPDATE SET response=excluded.response,created_at=CURRENT_TIMESTAMP
        """,
        (emergency_id, user["id"], response_value),
    )
    conn.commit()
    conn.close()
    flash("Emergency response recorded.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/emergency/<int:emergency_id>/close", methods=["POST"])
@role_required("office", "management")
def close_emergency(emergency_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE emergency_alerts SET status='closed',closed_at=? WHERE id=?",
        (now_iso(), emergency_id),
    )
    conn.commit()
    conn.close()
    flash("Emergency alert closed.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/api/updates")
@role_required("staff", "office", "management")
def api_updates():
    user = current_user()
    conn = get_db()
    mark_overdue_returns(conn)
    emergencies = [
        dict(row)
        for row in conn.execute(
            """
            SELECT e.id,e.emergency_type,e.location_code,e.description,e.created_at,
                   u.employee_name,u.department
            FROM emergency_alerts e JOIN users u ON u.id=e.reported_by
            WHERE e.status='active' ORDER BY datetime(e.created_at) DESC
            """
        ).fetchall()
    ]
    notifications = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id,title,message,notification_type,created_at
            FROM notifications
            WHERE is_read=0 AND (user_id=? OR role_target=? OR role_target='all')
            ORDER BY datetime(created_at) DESC LIMIT 10
            """,
            (user["id"], user["role"]),
        ).fetchall()
    ]
    unread_messages = conn.execute(
        """
        SELECT COUNT(*) FROM messages
        WHERE is_read=0 AND
        (receiver_user_id=? OR receiver_role=? OR receiver_role='all')
        """,
        (user["id"], user["role"]),
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify(
        emergencies=emergencies,
        notifications=notifications,
        unread_messages=unread_messages,
    )


@app.route("/reports/transactions.csv")
@role_required("office", "management")
def transaction_report():
    try:
        hours = min(max(int(request.args.get("hours", "48")), 1), 720)
    except ValueError:
        hours = 48
    conn = get_db()
    rows = conn.execute(
        """
        SELECT tr.created_at,a.asset_uid,t.category,t.name AS asset_name,
               u.employee_id,u.employee_name,tr.action,
               lf.name AS from_location,lt.name AS to_location,tr.reason
        FROM transactions tr
        JOIN assets a ON a.id=tr.asset_id
        JOIN asset_types t ON t.id=a.asset_type_id
        LEFT JOIN users u ON u.id=tr.employee_id
        LEFT JOIN locations lf ON lf.id=tr.from_location_id
        LEFT JOIN locations lt ON lt.id=tr.to_location_id
        WHERE datetime(tr.created_at) >= datetime('now',?)
        ORDER BY datetime(tr.created_at) DESC
        """,
        (f"-{hours} hours",),
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Date and time",
            "Asset ID",
            "Category",
            "Asset name",
            "Employee ID",
            "Employee name",
            "Action",
            "From location",
            "To location",
            "Reason",
        ]
    )
    for row in rows:
        writer.writerow(list(row))
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=meditrack_{hours}_hour_report.csv"},
    )


@app.route("/qrcode/assets/<path:filename>")
@role_required("office")
def asset_qr_file(filename: str):
    return send_from_directory(QR_ROOT / "assets", filename)


@app.route("/qrcode/locations/<path:filename>")
@role_required("office")
def location_qr_file(filename: str):
    return send_from_directory(QR_ROOT / "locations", filename)


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="The requested page was not found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", message="An unexpected error occurred. Check the terminal for details."), 500


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
