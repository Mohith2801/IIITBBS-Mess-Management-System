import os
import re
import sqlite3
import secrets
import hashlib
import smtplib
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "mess.db"))
COLLEGE_DOMAIN = "@iiit-bh.ac.in"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEALS = ["Breakfast", "Lunch", "Dinner"]
DEFAULT_PRICES = {"Breakfast": 28, "Lunch": 45, "Dinner": 40}
MEAL_TIMES = {"Breakfast": "7:30 – 9:00 am", "Lunch": "12:30 – 2:30 pm", "Dinner": "7:30 – 9:00 pm"}

WEEKLY_MENU = {
    "Monday": {"Breakfast":"Upma + Matar Curry + Tea","Lunch":"Rice/Roti + Dalma + Tomato/Khatta + Onion Salad","Dinner":"Rice/Roti + Paneer Masala"},
    "Tuesday": {"Breakfast":"Idli, Sambar, Chutney","Lunch":"Rice/Roti + Dal + Rajma + Dahi boondi + Fryums + Sambar","Dinner":"Rice/Roti + Alu ful kobi (last words unclear in photo)"},
    "Wednesday": {"Breakfast":"Dahi Bara + Aloo Dum (handwritten correction)","Lunch":"Rice/Roti + Dal + Chicken (3 pcs) curry / Paneer Curry + Salad","Dinner":"Rice/Roti + Egg Tadka + Chilli (last item cropped) + Gulab Jamun"},
    "Thursday": {"Breakfast":"Upma + Matar Curry + Tea/Coffee","Lunch":"Rice/Roti + Moong Dal + Aloo (handwritten correction; verify)","Dinner":"Choic bhature + curd + achar"},
    "Friday": {"Breakfast":"Uttapam/Masala Chakuli + Sambar + Chutney","Lunch":"Rice/Roti + Arhar Dal + Fish Curry / Palak Paneer + Salad","Dinner":"Rice/Roti + Paneer + Chicken (3 pcs; dish name cropped)"},
    "Saturday": {"Breakfast":"Khakra/Kakra + Aloo Chop + Matar Curry","Lunch":"Rice/Roti + Egg Curry + Navratna Korma + Papad","Dinner":"Rice/Roti + Chilli Kobi"},
    "Sunday": {"Breakfast":"Vada + Matar Curry","Lunch":"Chicken/Veg Biryani (Veg) + Raita + Gulab Jamun","Dinner":"Rice/Roti + Chicken Kasa (3 pcs) + Paneer Hyderabadi"}
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = connect_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      college_id TEXT UNIQUE NOT NULL,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'student',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS menu(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      weekday TEXT NOT NULL,
      meal_type TEXT NOT NULL,
      meal_time TEXT NOT NULL,
      items TEXT NOT NULL,
      UNIQUE(weekday, meal_type)
    );
    CREATE TABLE IF NOT EXISTS meal_prices(
      meal_type TEXT PRIMARY KEY,
      price INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bookings(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      meal_date TEXT NOT NULL,
      meal_type TEXT NOT NULL,
      booked_at TEXT NOT NULL,
      UNIQUE(user_id, meal_date, meal_type)
    );
    CREATE TABLE IF NOT EXISTS meal_attendance(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
      status TEXT NOT NULL DEFAULT 'Pending',
      marked_by INTEGER REFERENCES users(id),
      marked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS feedback(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      rating INTEGER NOT NULL,
      category TEXT NOT NULL,
      comment TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS complaints(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      subject TEXT NOT NULL,
      category TEXT NOT NULL,
      message TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Open',
      created_at TEXT NOT NULL
    );
    """)
    booking_columns = [row["name"] for row in conn.execute("PRAGMA table_info(bookings)").fetchall()]
    if "price_at_booking" not in booking_columns:
        conn.execute("ALTER TABLE bookings ADD COLUMN price_at_booking INTEGER NOT NULL DEFAULT 0")
        # Existing bookings are assigned the current configured price once during migration.
        conn.execute("""UPDATE bookings SET price_at_booking =
            COALESCE((SELECT price FROM meal_prices WHERE meal_prices.meal_type=bookings.meal_type), 0)
            WHERE price_at_booking=0""")

    if conn.execute("SELECT COUNT(*) FROM menu").fetchone()[0] == 0:
        for day, meals in WEEKLY_MENU.items():
            for meal, items in meals.items():
                conn.execute("INSERT INTO menu(weekday,meal_type,meal_time,items) VALUES(?,?,?,?)",
                             (day, meal, MEAL_TIMES[meal], items))
    for meal, price in DEFAULT_PRICES.items():
        conn.execute("INSERT OR IGNORE INTO meal_prices(meal_type,price) VALUES(?,?)", (meal, price))
    # The official management account is fixed; its first password must be set through email OTP.
    management = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if not management:
        conn.execute("""INSERT INTO users(name,college_id,email,password_hash,role,created_at)
                        VALUES(?,?,?,?,?,?)""",
                     ("Mess Management", "MESSADMIN", "ms@iiit-bh.ac.in",
                      generate_password_hash(secrets.token_urlsafe(32)), "admin", datetime.now().isoformat(timespec="seconds")))
    else:
        # If migrating an older demo admin identity, invalidate its old demo password.
        existing_admin = conn.execute("SELECT email FROM users WHERE role='admin' LIMIT 1").fetchone()
        if existing_admin and existing_admin["email"].lower() != "ms@iiit-bh.ac.in":
            conn.execute("UPDATE users SET email=?,password_hash=? WHERE role='admin'",
                         ("ms@iiit-bh.ac.in", generate_password_hash(secrets.token_urlsafe(32))))
        else:
            conn.execute("UPDATE users SET email=? WHERE role='admin'", ("ms@iiit-bh.ac.in",))
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS password_otps(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL,
      otp_hash TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      used INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS app_settings(
      setting_key TEXT PRIMARY KEY,
      setting_value TEXT NOT NULL
    );
    """)
    password_marker = conn.execute(
        "SELECT setting_value FROM app_settings WHERE setting_key='initial_management_password_applied'"
    ).fetchone()
    if not password_marker:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE email=? AND role='admin'",
            (generate_password_hash("iiitbbsr"), "ms@iiit-bh.ac.in")
        )
        conn.execute(
            "INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?)",
            ("initial_management_password_applied", "yes")
        )
    conn.commit()
    conn.close()

def get_db():
    if "db" not in g:
        g.db = connect_db()
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in first.", "warning")
            return redirect(url_for("student_login"))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def next_week_range(today=None):
    """Return next Monday through Sunday. Bookings are accepted only on Sunday."""
    today = today or date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:  # Sunday: next Monday is tomorrow
        days_until_monday = 1
    monday = today + timedelta(days=days_until_monday)
    sunday = monday + timedelta(days=6)
    return monday, sunday

def booking_open(today=None):
    today = today or date.today()
    return today.weekday() == 6  # Sunday only

@app.context_processor
def inject_globals():
    return {"today": date.today().isoformat(), "meal_times": MEAL_TIMES,
            "college_domain": COLLEGE_DOMAIN, "meal_prices": DEFAULT_PRICES}

@app.route("/")
def index():
    return render_template("index.html", menu=WEEKLY_MENU, prices=DEFAULT_PRICES)

@app.route("/menu")
def menu():
    return render_template("menu.html", menu=WEEKLY_MENU, days=DAYS, prices=DEFAULT_PRICES)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email.endswith(COLLEGE_DOMAIN) or email.count("@") != 1:
            flash("Use your official college email ending with @iiit-bh.ac.in.", "danger")
        else:
            college_id = email[:-len(COLLEGE_DOMAIN)]
            if not re.fullmatch(r"[a-zA-Z0-9._-]{3,30}", college_id):
                flash("The college ID part of your email is not valid.", "danger")
            elif not name or not password:
                flash("Please complete all fields.", "danger")
            elif len(password) < 8:
                flash("Password must contain at least 8 characters.", "danger")
            else:
                try:
                    conn = get_db()
                    conn.execute("""INSERT INTO users(name,college_id,email,password_hash,role,created_at)
                                    VALUES(?,?,?,?,?,?)""",
                                 (name, college_id, email, generate_password_hash(password),
                                  "student", datetime.now().isoformat(timespec="seconds")))
                    conn.commit()
                    flash("Registration successful. Your college ID was read from your email. Please log in.", "success")
                    return redirect(url_for("login"))
                except sqlite3.IntegrityError:
                    flash("This college email is already registered.", "danger")
    return render_template("register.html")


def authenticate_user(identity, password, required_role):
    identity = identity.strip().lower()
    user = get_db().execute(
        "SELECT * FROM users WHERE (lower(email)=? OR lower(college_id)=?) AND role=?",
        (identity, identity, required_role)
    ).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        session.clear()
        session.update(user_id=user["id"], name=user["name"], college_id=user["college_id"], role=user["role"])
        return True
    return False

@app.route("/login")
def login():
    return render_template("login_portal.html")

@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        if authenticate_user(request.form.get("identity", ""), request.form.get("password", ""), "student"):
            flash("Welcome, " + session["name"] + "!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid student login details.", "danger")
    return render_template("login.html", account_label="Student")

@app.route("/management/login", methods=["GET", "POST"])
def management_login():
    if request.method == "POST":
        email = request.form.get("identity", "").strip().lower()
        if email != "ms@iiit-bh.ac.in":
            flash("Use the official management email address.", "danger")
        elif authenticate_user(email, request.form.get("password", ""), "admin"):
            flash("Welcome to Mess Management.", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid management password. Use Forgot Password if this is your first login.", "danger")
    return render_template("management_login.html")

def send_password_otp(email, otp):
    host = os.environ.get("MAIL_SERVER")
    port = int(os.environ.get("MAIL_PORT", "587"))
    username = os.environ.get("MAIL_USERNAME")
    password = os.environ.get("MAIL_PASSWORD")
    sender = os.environ.get("MAIL_DEFAULT_SENDER", username or "")
    if not all([host, username, password, sender]):
        raise RuntimeError("Email OTP is not configured yet. The administrator must add SMTP settings to the deployment environment.")
    msg = EmailMessage()
    msg["Subject"] = "IIITBBS Mess Portal - Password Reset OTP"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(
        f"Your IIITBBS Mess Portal password reset OTP is: {otp}\\n\\n"
        "This OTP expires in 5 minutes and can only be used once. "
        "If you did not request this, please ignore this email."
    )
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT id,email FROM users WHERE lower(email)=?", (email,)).fetchone()
        if not user:
            flash("No account is registered with that email address.", "danger")
            return render_template("forgot_password.html")
        # Limit new OTP requests for the same address to one per 60 seconds.
        recent = get_db().execute(
            "SELECT created_at FROM password_otps WHERE email=? ORDER BY id DESC LIMIT 1", (email,)
        ).fetchone()
        if recent:
            try:
                last = datetime.fromisoformat(recent["created_at"])
                if (datetime.now() - last).total_seconds() < 60:
                    flash("Please wait one minute before requesting another OTP.", "warning")
                    return render_template("forgot_password.html")
            except ValueError:
                pass
        otp = f"{secrets.randbelow(1000000):06d}"
        otp_hash = hashlib.sha256(otp.encode()).hexdigest()
        now = datetime.now()
        expiry = (now + timedelta(minutes=5)).isoformat(timespec="seconds")
        try:
            send_password_otp(email, otp)
        except Exception as exc:
            app.logger.exception("Could not send password OTP")
            flash(str(exc), "danger")
            return render_template("forgot_password.html")
        conn = get_db()
        conn.execute("UPDATE password_otps SET used=1 WHERE email=? AND used=0", (email,))
        conn.execute(
            "INSERT INTO password_otps(email,otp_hash,expires_at,created_at) VALUES(?,?,?,?)",
            (email, otp_hash, expiry, now.isoformat(timespec="seconds"))
        )
        conn.commit()
        session["password_reset_email"] = email
        flash("A six-digit OTP has been sent to your registered email.", "success")
        return redirect(url_for("reset_password"))
    return render_template("forgot_password.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("password_reset_email")
    if not email:
        flash("Request a password reset OTP first.", "warning")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(new_password) < 8:
            flash("New password must contain at least 8 characters.", "danger")
        elif new_password != confirm_password:
            flash("Passwords do not match.", "danger")
        else:
            conn = get_db()
            record = conn.execute(
                "SELECT * FROM password_otps WHERE email=? AND used=0 ORDER BY id DESC LIMIT 1", (email,)
            ).fetchone()
            if not record:
                flash("No active OTP found. Request a new one.", "danger")
            elif datetime.fromisoformat(record["expires_at"]) < datetime.now():
                conn.execute("UPDATE password_otps SET used=1 WHERE id=?", (record["id"],))
                conn.commit()
                flash("OTP expired. Request a new OTP.", "danger")
            elif record["attempts"] >= 5:
                conn.execute("UPDATE password_otps SET used=1 WHERE id=?", (record["id"],))
                conn.commit()
                flash("Too many incorrect attempts. Request a new OTP.", "danger")
            elif not secrets.compare_digest(record["otp_hash"], hashlib.sha256(otp.encode()).hexdigest()):
                conn.execute("UPDATE password_otps SET attempts=attempts+1 WHERE id=?", (record["id"],))
                conn.commit()
                flash("Incorrect OTP.", "danger")
            else:
                conn.execute("UPDATE users SET password_hash=? WHERE lower(email)=?",
                             (generate_password_hash(new_password), email))
                conn.execute("UPDATE password_otps SET used=1 WHERE id=?", (record["id"],))
                conn.commit()
                session.pop("password_reset_email", None)
                flash("Password changed successfully. Please log in.", "success")
                return redirect(url_for("management_login" if email == "ms@iiit-bh.ac.in" else "student_login"))
    return render_template("reset_password.html", email=email)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    uid = session["user_id"]
    upcoming_start, upcoming_end = next_week_range()
    bookings = conn.execute("""
      SELECT b.*, COALESCE(b.price_at_booking,p.price,0) AS price,
             COALESCE(a.status,'Not recorded') AS attendance_status
      FROM bookings b
      LEFT JOIN meal_prices p ON p.meal_type=b.meal_type
      LEFT JOIN meal_attendance a ON a.booking_id=b.id
      WHERE b.user_id=? ORDER BY b.meal_date DESC,b.booked_at DESC
    """, (uid,)).fetchall()
    due = conn.execute("""
      SELECT COALESCE(SUM(CASE WHEN b.price_at_booking>0 THEN b.price_at_booking ELSE p.price END),0)
      FROM bookings b LEFT JOIN meal_prices p ON p.meal_type=b.meal_type
      WHERE b.user_id=?
    """, (uid,)).fetchone()[0]
    upcoming_due = sum(row["price"] for row in bookings
                       if upcoming_start.isoformat() <= row["meal_date"] <= upcoming_end.isoformat())
    recent_feedback = conn.execute("SELECT COUNT(*) FROM feedback WHERE user_id=?", (uid,)).fetchone()[0]
    complaints = conn.execute("SELECT * FROM complaints WHERE user_id=? ORDER BY created_at DESC LIMIT 4", (uid,)).fetchall()
    return render_template("dashboard.html", bookings=bookings, due=due, upcoming_due=upcoming_due,
                           week_start=upcoming_start, week_end=upcoming_end,
                           feedback_count=recent_feedback, complaints=complaints)

@app.route("/book-meals", methods=["GET", "POST"])
@login_required
def book_meals():
    start, end = next_week_range()
    opened = booking_open()
    booking_day = start - timedelta(days=1)
    if request.method == "POST":
        if not opened:
            flash("Weekly booking is available only on Sunday for the upcoming Monday–Sunday week.", "warning")
            return redirect(url_for("book_meals"))
        conn = get_db()
        selected = request.form.getlist("meal")
        valid = []
        for item in selected:
            try:
                meal_date, meal_type = item.split("|", 1)
                parsed = date.fromisoformat(meal_date)
                if start <= parsed <= end and meal_type in MEALS:
                    valid.append((meal_date, meal_type))
            except (ValueError, TypeError):
                continue
        # Replace the student's upcoming week's selection as one transaction.
        conn.execute("DELETE FROM bookings WHERE user_id=? AND meal_date BETWEEN ? AND ?",
                     (session["user_id"], start.isoformat(), end.isoformat()))
        now = datetime.now().isoformat(timespec="seconds")
        current_prices = {r["meal_type"]: r["price"] for r in conn.execute("SELECT * FROM meal_prices")}
        for meal_date, meal_type in set(valid):
            conn.execute("""INSERT INTO bookings(user_id,meal_date,meal_type,booked_at,price_at_booking)
                            VALUES(?,?,?,?,?)""",
                         (session["user_id"], meal_date, meal_type, now, current_prices[meal_type]))
        conn.commit()
        flash(f"Your weekly booking has been saved. Selected {len(set(valid))} meals.", "success")
        return redirect(url_for("dashboard"))
    existing = get_db().execute("SELECT meal_date,meal_type FROM bookings WHERE user_id=? AND meal_date BETWEEN ? AND ?",
                                (session["user_id"], start.isoformat(), end.isoformat())).fetchall()
    selected = {r["meal_date"] + "|" + r["meal_type"] for r in existing}
    menu_rows = get_db().execute("SELECT * FROM menu ORDER BY id").fetchall()
    menu_map = {(r["weekday"], r["meal_type"]): r["items"] for r in menu_rows}
    prices = {r["meal_type"]: r["price"] for r in get_db().execute("SELECT * FROM meal_prices")}
    days = []
    d = start
    while d <= end:
        days.append({"date": d, "weekday": d.strftime("%A"), "meals": [
            {"type": m, "items": menu_map.get((d.strftime("%A"), m), ""), "price": prices[m],
             "key": d.isoformat() + "|" + m} for m in MEALS]})
        d += timedelta(days=1)
    return render_template("book_meals.html", days=days, selected=selected, opened=opened,
                           start=start, end=end, booking_day=booking_day, prices=prices)

@app.route("/attendance")
@login_required
@admin_required
def attendance_management():
    conn = get_db()
    target_date = request.args.get("date", date.today().isoformat())
    rows = conn.execute("""
      SELECT b.id AS booking_id,b.meal_date,b.meal_type,u.name,u.college_id,u.email,
             COALESCE(a.status,'Pending') AS status
      FROM bookings b JOIN users u ON u.id=b.user_id
      LEFT JOIN meal_attendance a ON a.booking_id=b.id
      WHERE b.meal_date=? ORDER BY b.meal_type,u.college_id
    """, (target_date,)).fetchall()
    return render_template("attendance_management.html", rows=rows, target_date=target_date)

@app.route("/attendance/<int:booking_id>/update", methods=["POST"])
@login_required
@admin_required
def update_attendance(booking_id):
    status = request.form.get("status")
    if status not in ["Present", "Absent"]:
        flash("Choose Present or Absent.", "danger")
    else:
        conn = get_db()
        conn.execute("""INSERT INTO meal_attendance(booking_id,status,marked_by,marked_at)
                        VALUES(?,?,?,?)
                        ON CONFLICT(booking_id) DO UPDATE SET status=excluded.status,
                        marked_by=excluded.marked_by,marked_at=excluded.marked_at""",
                     (booking_id,status,session["user_id"],datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        flash("Student meal attendance updated.", "success")
    return redirect(url_for("attendance_management", date=request.form.get("meal_date", date.today().isoformat())))

@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    conn = get_db()
    if request.method == "POST":
        try: rating = int(request.form.get("rating", "0"))
        except ValueError: rating = 0
        category = request.form.get("category", "Overall")
        comment = request.form.get("comment", "").strip()
        if rating not in range(1, 6) or not comment:
            flash("Select a rating and write a comment.", "danger")
        else:
            conn.execute("INSERT INTO feedback(user_id,rating,category,comment,created_at) VALUES(?,?,?,?,?)",
                         (session["user_id"],rating,category,comment,datetime.now().isoformat(timespec="seconds")))
            conn.commit()
            flash("Thank you for your feedback.", "success")
            return redirect(url_for("feedback"))
    records = conn.execute("SELECT * FROM feedback WHERE user_id=? ORDER BY created_at DESC",
                           (session["user_id"],)).fetchall()
    return render_template("feedback.html", records=records)

@app.route("/complaints", methods=["GET", "POST"])
@login_required
def complaints():
    conn = get_db()
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        category = request.form.get("category", "Other")
        message = request.form.get("message", "").strip()
        if not subject or not message:
            flash("Enter a subject and description.", "danger")
        else:
            conn.execute("INSERT INTO complaints(user_id,subject,category,message,created_at) VALUES(?,?,?,?,?)",
                         (session["user_id"],subject,category,message,datetime.now().isoformat(timespec="seconds")))
            conn.commit()
            flash("Complaint submitted.", "success")
            return redirect(url_for("complaints"))
    records = conn.execute("SELECT * FROM complaints WHERE user_id=? ORDER BY created_at DESC",
                           (session["user_id"],)).fetchall()
    return render_template("complaints.html", records=records)

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    conn = get_db()
    stats = {
      "students": conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
      "bookings": conn.execute("SELECT COUNT(*) FROM bookings WHERE meal_date>=?", (date.today().isoformat(),)).fetchone()[0],
      "pending": conn.execute("SELECT COUNT(*) FROM bookings b LEFT JOIN meal_attendance a ON a.booking_id=b.id WHERE a.status IS NULL OR a.status='Pending'").fetchone()[0],
      "complaints": conn.execute("SELECT COUNT(*) FROM complaints WHERE status!='Resolved'").fetchone()[0]
    }
    return render_template("admin_dashboard.html", stats=stats)

@app.route("/admin/students")
@login_required
@admin_required
def admin_students():
    rows = get_db().execute("""
      SELECT u.id,u.name,u.college_id,u.email,
             COUNT(b.id) AS booked_meals,
             COALESCE(SUM(CASE WHEN b.id IS NOT NULL THEN
               CASE WHEN b.price_at_booking>0 THEN b.price_at_booking ELSE p.price END
             ELSE 0 END),0) AS due
      FROM users u
      LEFT JOIN bookings b ON b.user_id=u.id
      LEFT JOIN meal_prices p ON p.meal_type=b.meal_type
      WHERE u.role='student'
      GROUP BY u.id,u.name,u.college_id,u.email
      ORDER BY u.college_id
    """).fetchall()
    return render_template("admin_students.html", students=rows)

@app.route("/admin/students/<int:student_id>")
@login_required
@admin_required
def admin_student_bookings(student_id):
    conn = get_db()
    student = conn.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if not student:
        abort(404)
    bookings = conn.execute("""
      SELECT b.*, COALESCE(b.price_at_booking,p.price,0) AS price,
             COALESCE(a.status,'Not recorded') AS attendance_status
      FROM bookings b
      LEFT JOIN meal_prices p ON p.meal_type=b.meal_type
      LEFT JOIN meal_attendance a ON a.booking_id=b.id
      WHERE b.user_id=? ORDER BY b.meal_date DESC,b.booked_at DESC,b.meal_type
    """, (student_id,)).fetchall()
    due = sum(row["price"] for row in bookings)
    return render_template("admin_student_bookings.html", student=student, bookings=bookings, due=due)

@app.route("/admin/menu", methods=["GET", "POST"])
@login_required
@admin_required
def admin_menu():
    conn = get_db()
    if request.method == "POST":
        day=request.form.get("weekday"); meal=request.form.get("meal_type"); items=request.form.get("items","").strip()
        if day not in DAYS or meal not in MEALS or not items:
            flash("Enter a valid day, meal and menu items.", "danger")
        else:
            conn.execute("UPDATE menu SET items=? WHERE weekday=? AND meal_type=?", (items,day,meal))
            conn.commit()
            flash("Menu updated.", "success")
            return redirect(url_for("admin_menu"))
    menu_rows=conn.execute("SELECT * FROM menu ORDER BY id").fetchall()
    prices=conn.execute("SELECT * FROM meal_prices").fetchall()
    return render_template("admin_menu.html", menu_rows=menu_rows, prices=prices, days=DAYS)

@app.route("/admin/prices", methods=["POST"])
@login_required
@admin_required
def update_prices():
    conn=get_db()
    for meal in MEALS:
        try: price=int(request.form.get(meal, DEFAULT_PRICES[meal]))
        except ValueError: price=0
        if price < 0 or price > 10000:
            flash("Enter valid non-negative meal prices.", "danger")
            return redirect(url_for("admin_menu"))
        conn.execute("UPDATE meal_prices SET price=? WHERE meal_type=?", (price,meal))
    conn.commit()
    flash("Meal prices updated.", "success")
    return redirect(url_for("admin_menu"))

@app.route("/admin/complaints")
@login_required
@admin_required
def admin_complaints():
    rows=get_db().execute("""SELECT c.*,u.name,u.college_id FROM complaints c
        JOIN users u ON u.id=c.user_id ORDER BY c.created_at DESC""").fetchall()
    return render_template("admin_complaints.html", complaints=rows)

@app.route("/admin/complaints/<int:cid>", methods=["POST"])
@login_required
@admin_required
def update_complaint(cid):
    status=request.form.get("status")
    if status in ["Open","In Progress","Resolved"]:
        conn=get_db(); conn.execute("UPDATE complaints SET status=? WHERE id=?", (status,cid)); conn.commit()
        flash("Complaint status updated.", "success")
    return redirect(url_for("admin_complaints"))

@app.route("/health")
def health():
    return {"status":"ok"}

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=os.environ.get("FLASK_DEBUG")=="1")
