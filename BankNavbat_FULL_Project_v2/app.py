from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date, timezone
from pathlib import Path
import os
import re
import secrets
import time

app = Flask(__name__)

# ---------------- SOZLAMALAR ----------------
# Hammasi muhit o'zgaruvchilari (environment variables) orqali o'zgartiriladi.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "banknavbat-dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

# Ma'lumotlar bazasi: DATABASE_URL berilsa shu (MySQL / PostgreSQL), bo'lmasa SQLite.
#   MySQL:      mysql+pymysql://user:parol@localhost:3306/banknavbat?charset=utf8mb4
#   PostgreSQL: postgresql+psycopg2://user:parol@localhost:5432/banknavbat
db_url = os.environ.get("DATABASE_URL")
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
else:
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{Path(app.instance_path) / 'banknavbat.db'}"
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
db = SQLAlchemy(app)

ADMIN_LOGIN = os.environ.get("ADMIN_EMAIL", "erbolatberdiqulov@bank.uz").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "erbolat73")

TIME_SLOTS = ["09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00"]
MAX_PER_SLOT = 3  # bitta xizmat, bitta sana va vaqtga nechta odam yozilishi mumkin
STATUSES = ["Kutilmoqda", "Tasdiqlandi", "Bajarildi", "Bekor qilindi"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------- MODELLAR ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user", nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    bookings = db.relationship("Booking", backref="user", lazy=True)


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    icon = db.Column(db.String(20), default="🏦")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    bookings = db.relationship("Booking", backref="service", lazy=True)


class Booking(db.Model):
    __table_args__ = (
        # Bir kunda bir xil navbat raqami ikki marta berilmasligi uchun
        db.UniqueConstraint("booking_date", "queue_number", name="uq_booking_day_queue"),
    )
    id = db.Column(db.Integer, primary_key=True)
    queue_number = db.Column(db.Integer, nullable=False)
    booking_date = db.Column(db.Date, nullable=False, index=True)
    booking_time = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(30), default="Kutilmoqda")
    created_at = db.Column(db.DateTime, default=utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("service.id"), nullable=False)


# ---------------- YORDAMCHILAR ----------------
def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf", "")
        sent = request.form.get("_csrf", "")
        if not token or not secrets.compare_digest(token, sent):
            flash("Sessiya muddati tugagan. Qaytadan urinib ko‘ring.", "warning")
            return redirect(request.referrer or url_for("home"))


# Oddiy login urinishlarini cheklash (xotirada; bitta server uchun yetarli)
_FAILED = {}
MAX_FAILS, WINDOW = 5, 300


def too_many_attempts():
    now = time.time()
    hits = [t for t in _FAILED.get(request.remote_addr, []) if now - t < WINDOW]
    _FAILED[request.remote_addr] = hits
    return len(hits) >= MAX_FAILS


def register_fail():
    _FAILED.setdefault(request.remote_addr, []).append(time.time())


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Avval tizimga kiring.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user.role != "admin":
            flash("Administrator huquqi talab qilinadi.", "danger")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def next_queue_number(day):
    """Navbat raqami har kun uchun 101 dan boshlanadi."""
    last = db.session.query(func.max(Booking.queue_number)).filter(Booking.booking_date == day).scalar()
    return (last or 100) + 1


def try_login(email, password, fail_msg, admin_only=False):
    """Muvaffaqiyatli bo'lsa User qaytaradi, aks holda None."""
    if too_many_attempts():
        flash("Juda ko‘p urinish. Bir necha daqiqadan keyin qayta urinib ko‘ring.", "danger")
        return None
    user = User.query.filter_by(email=email).first()
    ok = bool(user) and check_password_hash(user.password_hash, password)
    if ok and admin_only and user.role != "admin":
        ok = False
    if not ok:
        register_fail()
        flash(fail_msg, "danger")
        return None
    _FAILED.pop(request.remote_addr, None)
    return user


def seed():
    db.create_all()
    if not User.query.filter_by(email=ADMIN_LOGIN).first():
        db.session.add(User(full_name="Administrator", email=ADMIN_LOGIN,
                            password_hash=generate_password_hash(ADMIN_PASSWORD), role="admin"))
    if Service.query.count() == 0:
        for name, desc, icon in [
            ("Karta ochish", "Bank kartasini ochish va rasmiylashtirish.", "💳"),
            ("Kredit bo‘yicha maslahat", "Kredit shartlari va imkoniyatlari bo‘yicha maslahat.", "💰"),
            ("Hisob raqami ochish", "Jismoniy shaxs uchun bank hisob raqamini ochish.", "🏦"),
            ("Pul o‘tkazmasi", "Ichki va xalqaro pul o‘tkazmalari bo‘yicha xizmat.", "💸"),
        ]:
            db.session.add(Service(name=name, description=desc, icon=icon))
    db.session.commit()


# ---------------- OMMAVIY SAHIFALAR ----------------
@app.route("/")
def home():
    services = Service.query.filter_by(active=True).order_by(Service.id).all()
    return render_template("home.html", services=services, next_number=next_queue_number(date.today()))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()[:120]
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not EMAIL_RE.match(email) or len(password) < 6:
            flash("Ismni, to‘g‘ri email va kamida 6 belgili parolni kiriting.", "danger")
            return render_template("auth/register.html")
        if email == ADMIN_LOGIN:
            flash("Bu login administrator uchun ajratilgan.", "danger")
            return render_template("auth/register.html")
        if User.query.filter_by(email=email).first():
            flash("Bu email allaqachon ro‘yxatdan o‘tgan.", "warning")
            return render_template("auth/register.html")
        db.session.add(User(full_name=name, email=email, password_hash=generate_password_hash(password)))
        db.session.commit()
        flash("Ro‘yxatdan o‘tish muvaffaqiyatli. Endi tizimga kiring.", "success")
        return redirect(url_for("login"))
    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = try_login(email, request.form.get("password", ""), "Email yoki parol noto‘g‘ri.")
        if not user:
            return redirect(url_for("login"))
        session.clear()
        session["user_id"] = user.id
        return redirect(url_for("admin_dashboard" if user.role == "admin" else "dashboard"))
    return render_template("auth/login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Tizimdan chiqdingiz.", "success")
    return redirect(url_for("home"))


# ---------------- FOYDALANUVCHI ----------------
@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    bookings = (Booking.query.options(joinedload(Booking.service))
                .filter_by(user_id=user.id)
                .order_by(Booking.booking_date.desc(), Booking.id.desc()).all())
    services = Service.query.filter_by(active=True).order_by(Service.id).all()
    return render_template("user/dashboard.html", bookings=bookings, services=services,
                           today=date.today().isoformat(), time_slots=TIME_SLOTS)


@app.route("/book/<int:service_id>", methods=["POST"])
@login_required
def book(service_id):
    service = db.session.get(Service, service_id)
    if not service or not service.active:
        flash("Xizmat topilmadi.", "danger")
        return redirect(url_for("dashboard"))

    booking_time = request.form.get("booking_time", "")
    try:
        selected_date = datetime.strptime(request.form.get("booking_date", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Sanani to‘g‘ri tanlang.", "danger")
        return redirect(url_for("dashboard"))
    if selected_date < date.today():
        flash("O‘tgan sanani tanlab bo‘lmaydi.", "danger")
        return redirect(url_for("dashboard"))
    if booking_time not in TIME_SLOTS:
        flash("Vaqtni ro‘yxatdan tanlang.", "danger")
        return redirect(url_for("dashboard"))
    if selected_date == date.today() and booking_time <= datetime.now().strftime("%H:%M"):
        flash("Bugungi kun uchun bu vaqt o‘tib ketgan.", "danger")
        return redirect(url_for("dashboard"))

    user = current_user()
    active = Booking.status != "Bekor qilindi"
    if Booking.query.filter(active, Booking.user_id == user.id, Booking.booking_date == selected_date,
                            Booking.booking_time == booking_time).first():
        flash("Siz bu sana va vaqtga allaqachon yozilgansiz.", "warning")
        return redirect(url_for("dashboard"))
    taken = Booking.query.filter(active, Booking.service_id == service.id,
                                 Booking.booking_date == selected_date,
                                 Booking.booking_time == booking_time).count()
    if taken >= MAX_PER_SLOT:
        flash("Bu vaqt band. Boshqa vaqtni tanlang.", "warning")
        return redirect(url_for("dashboard"))

    for _ in range(3):  # bir vaqtda yozilganlarda raqam to'qnashsa qayta urinadi
        booking = Booking(queue_number=next_queue_number(selected_date), booking_date=selected_date,
                          booking_time=booking_time, status="Kutilmoqda",
                          user_id=user.id, service_id=service.id)
        db.session.add(booking)
        try:
            db.session.commit()
            flash(f"Navbat olindi. Sizning navbat raqamingiz: #{booking.queue_number}", "success")
            break
        except IntegrityError:
            db.session.rollback()
    else:
        flash("Navbat olib bo‘lmadi, qayta urinib ko‘ring.", "danger")
    return redirect(url_for("dashboard"))


@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking or booking.user_id != current_user().id:
        abort(404)
    if booking.status in ("Kutilmoqda", "Tasdiqlandi"):
        booking.status = "Bekor qilindi"
        db.session.commit()
        flash("Navbat bekor qilindi.", "success")
    return redirect(url_for("dashboard"))


# ---------------- ADMIN ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        login_value = request.form.get("login", "").strip().lower()
        admin = try_login(login_value, request.form.get("password", ""),
                          "Administrator login yoki parol noto‘g‘ri.", admin_only=True)
        if admin:
            session.clear()
            session["user_id"] = admin.id
            return redirect(url_for("admin_dashboard"))
    return render_template("admin/login.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = {
        "users": User.query.filter_by(role="user").count(),
        "bookings": Booking.query.count(),
        "pending": Booking.query.filter_by(status="Kutilmoqda").count(),
        "services": Service.query.count(),
    }
    status_filter = request.args.get("status", "")
    q = Booking.query.options(joinedload(Booking.user), joinedload(Booking.service))
    if status_filter in STATUSES:
        q = q.filter_by(status=status_filter)
    bookings = q.order_by(Booking.booking_date.desc(), Booking.booking_time, Booking.queue_number).all()
    users = User.query.order_by(User.created_at.desc()).all()
    services = Service.query.order_by(Service.id).all()
    return render_template("admin/dashboard.html", stats=stats, bookings=bookings, users=users,
                           services=services, statuses=STATUSES, status_filter=status_filter)


@app.route("/admin/booking/<int:booking_id>/status", methods=["POST"])
@admin_required
def update_booking_status(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking:
        flash("Navbat topilmadi.", "danger")
    elif request.form.get("status") in STATUSES:
        booking.status = request.form["status"]
        db.session.commit()
        flash("Navbat holati yangilandi.", "success")
    return redirect(url_for("admin_dashboard", status=request.args.get("status", "")))


@app.route("/admin/service/add", methods=["POST"])
@admin_required
def add_service():
    name = request.form.get("name", "").strip()[:120]
    description = request.form.get("description", "").strip()
    icon = request.form.get("icon", "").strip()[:20] or "🏦"
    if name:
        db.session.add(Service(name=name, description=description, icon=icon))
        db.session.commit()
        flash("Yangi xizmat qo‘shildi.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/service/<int:service_id>/toggle", methods=["POST"])
@admin_required
def toggle_service(service_id):
    service = db.session.get(Service, service_id)
    if service:
        service.active = not service.active
        db.session.commit()
        flash("Xizmat faollashtirildi." if service.active else "Xizmat faol ro‘yxatdan chiqarildi.", "success")
    return redirect(url_for("admin_dashboard"))


with app.app_context():
    seed()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
