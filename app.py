import os
import random
import string
import secrets
import hmac
import hashlib
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from models import db, MenuItem, Order, OrderItem, Admin, User, SiteSetting, Promotion, Favorite, Review, LoyaltyLedger, Campaign, ContentPage, AnalyticsEvent, Reservation, MealBundle, DeliveryZone

app = Flask(__name__)
secret_key = os.environ.get("JENNY_SECRET_KEY")
if not secret_key:
    # Development can start without a secret, but production must set one explicitly.
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("APP_ENV") == "production":
        raise RuntimeError("JENNY_SECRET_KEY must be configured in production.")
    secret_key = "local-development-only-" + secrets.token_hex(24)
app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///jennys.db")
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["PAYSTACK_SECRET_KEY"] = os.environ.get("PAYSTACK_SECRET_KEY", "")
app.config["PAYSTACK_PUBLIC_KEY"] = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db.init_app(app)

@app.after_request
def set_static_cache_headers(response):
    path = request.path or ""
    if path.startswith("/static/uploads/") and response.status_code == 200:
        response.headers.setdefault("Cache-Control", "public, max-age=2592000, immutable")
    elif path.startswith("/static/") and response.status_code == 200:
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
    return response

# ---------- Flask-Login ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------- Helpers ----------
def gen_order_number():
    return "JK-" + secrets.token_hex(8).upper()


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Please log in as admin.")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


def get_cart():
    return session.get("cart") or {}

def save_cart(cart):
    session["cart"] = cart
    session.modified = True


def process_image(file, max_size=(1200, 1200)):
    """Save an image upload without requiring Pillow/native image libraries on Termux."""
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        return None
    # Check the signature rather than trusting only the extension.
    data = file.read(16)
    file.seek(0)
    signatures = {
        "jpg": data.startswith(b"\xff\xd8\xff"),
        "jpeg": data.startswith(b"\xff\xd8\xff"),
        "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "gif": data.startswith((b"GIF87a", b"GIF89a")),
        "webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }
    if not signatures.get(ext, False):
        return None
    unique = f"{os.path.splitext(filename)[0]}_{secrets.token_hex(5)}.{ext}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], unique))
    return unique


def ensure_schema_compatibility():
    """Add new columns to existing SQLite installs without deleting customer data."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if "order" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("order")}
    additions = {
        "payment_method": "VARCHAR(30) DEFAULT 'pay_on_pickup'",
        "payment_status": "VARCHAR(30) DEFAULT 'unpaid'",
        "payment_reference": "VARCHAR(120)",
        "email": "VARCHAR(120)",
        "notes": "VARCHAR(500)",
        "delivery_fee": "FLOAT DEFAULT 0",
        "delivery_zone": "VARCHAR(100)",
        "delivery_eta_min": "INTEGER",
        "delivery_eta_max": "INTEGER",
        "promotion_code": "VARCHAR(40)",
        "user_id": "INTEGER",
        "loyalty_awarded": "BOOLEAN DEFAULT 0",
        "loyalty_points_redeemed": "INTEGER DEFAULT 0",
    }
    for name, declaration in additions.items():
        if name not in existing:
            db.session.execute(text(f'ALTER TABLE "order" ADD COLUMN {name} {declaration}'))
    if "menu_item" in inspector.get_table_names():
        menu_columns = {c["name"] for c in inspector.get_columns("menu_item")}
        for name, declaration in {"availability_status": "VARCHAR(30) DEFAULT 'available'", "featured_label": "VARCHAR(30) DEFAULT ''"}.items():
            if name not in menu_columns:
                db.session.execute(text(f'ALTER TABLE menu_item ADD COLUMN {name} {declaration}'))
    if "user" in inspector.get_table_names():
        user_columns = {c["name"] for c in inspector.get_columns("user")}
        user_additions = {"marketing_consent": "BOOLEAN DEFAULT 0", "loyalty_points": "INTEGER DEFAULT 0", "referral_code": "VARCHAR(16)", "referred_by": "VARCHAR(16)", "unsubscribe_token": "VARCHAR(64)", "created_at": "DATETIME"}
        for name, declaration in user_additions.items():
            if name not in user_columns:
                db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {name} {declaration}'))
    db.session.commit()
    # Give existing customer accounts a referral code after the additive migration.
    try:
        for customer in User.query.filter(User.referral_code.is_(None)).all():
            customer.referral_code = secrets.token_hex(4).upper()
        for customer in User.query.filter(User.unsubscribe_token.is_(None)).all():
            customer.unsubscribe_token = secrets.token_urlsafe(32)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not backfill customer referral codes")


def make_payment_reference():
    return "JKPAY-" + secrets.token_hex(12).upper()


def paystack_request(path, payload=None):
    key = app.config.get("PAYSTACK_SECRET_KEY")
    if not key:
        raise RuntimeError("Paystack is not configured yet. Set PAYSTACK_SECRET_KEY in the environment.")
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.paystack.co" + path, data=body if payload is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("Paystack request failed: " + detail) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Could not connect to Paystack. Please try again.") from exc


def send_customer_order_update(order):
    """Send transactional order updates; marketing consent is not required for service messages."""
    if not order.email or not os.environ.get("SMTP_HOST"):
        return False
    import smtplib
    from email.message import EmailMessage
    sender = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
    if not sender:
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Jenny's Kitchen order {order.order_number}: {order.status}"
    msg["From"] = sender
    msg["To"] = order.email
    msg.set_content(f"Hi {order.customer_name},\n\nYour Jenny's Kitchen order {order.order_number} is now: {order.status}.\nPayment status: {order.payment_status.replace('_', ' ')}.\nOrder total: NGN {order.total:,.2f}.\n\nFor help, contact the kitchen using the details on our website.\n\nJenny's Kitchen")
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=10) as server:
            server.starttls()
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
        return True
    except Exception:
        app.logger.exception("Customer order update email failed for %s", order.order_number)
        return False


def send_order_notification(order):
    """Best-effort email notification when SMTP environment variables are configured."""
    host = os.environ.get("SMTP_HOST")
    recipient = os.environ.get("ORDER_NOTIFICATION_EMAIL")
    if not host or not recipient:
        return False
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = f"Jenny's Kitchen order {order.order_number}"
    msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", recipient))
    msg["To"] = recipient
    msg.set_content(f"New order: {order.order_number}\nCustomer: {order.customer_name}\nPhone: {order.phone}\nType: {order.order_type}\nTotal: NGN {order.total:,.2f}\nPayment: {order.payment_status}\nStatus: {order.status}")
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=10) as server:
            server.starttls()
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
        return True
    except Exception:
        app.logger.exception("Order notification email failed for %s", order.order_number)
        return False


# ---------- Public ----------
def setting(key, default=""):
    row = SiteSetting.query.filter_by(key=key).first()
    return row.value if row else default

def set_setting(key, value):
    row = SiteSetting.query.filter_by(key=key).first()
    if row is None:
        row = SiteSetting(key=key, value=str(value))
        db.session.add(row)
    else:
        row.value = str(value)


def safe_destination(value, default="/menu"):
    value = (value or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    if value.startswith(("https://", "http://")):
        return value
    return default

def safe_local_redirect(value, default):
    value = (value or "").strip()
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default

def image_url(image, category=None, item_id=0):
    if image and image not in ("default.jpg", ""):
        if image.startswith(("https://", "http://")):
            return image
        return url_for("static", filename="uploads/" + image)
    stock = [
        "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1600891964599-f61ba0e24092?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1604908176997-125f25cc6f3d?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?auto=format&fit=crop&w=900&q=85",
        "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=900&q=85"
    ]
    return stock[(int(item_id or 0) + len(str(category or ""))) % len(stock)]

app.jinja_env.globals["image_url"] = image_url

@app.context_processor
def global_site_context():
    shared = {"phone": setting("phone", ""), "address": setting("address", "Jos South, Plateau State, Nigeria"), "whatsapp": setting("whatsapp", os.environ.get("JENNY_WHATSAPP_NUMBER", "")), "tagline": setting("tagline", "Good food. Good mood.")}
    return {"global_site": shared, "site": shared}


DEFAULT_SLIDES = [
    {"eyebrow":"FRESH FROM OUR KITCHEN", "title":"Good food.\nGood mood.", "description":"Made with care, packed with flavour, and ready to make your day better.", "image":"https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=1200&q=88", "button":"Explore the menu", "link":"/menu"},
    {"eyebrow":"YOUR FAVOURITES, MADE FRESH", "title":"A little joy\nin every bite.", "description":"Discover delicious meals and snacks made for sharing, celebrating, and everyday cravings.", "image":"https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=1200&q=88", "button":"Order your favourite", "link":"/menu"},
    {"eyebrow":"SOMETHING DELICIOUS IS WAITING", "title":"Still hot.\nAlways satisfying.", "description":"Find your next favourite from the Jenny’s Kitchen menu.", "image":"https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?auto=format&fit=crop&w=1200&q=88", "button":"See what’s cooking", "link":"/menu"}
]

def get_slides():
    import json
    try:
        slides = json.loads(setting("hero_slides", ""))
        return slides if isinstance(slides, list) and slides else DEFAULT_SLIDES
    except (ValueError, TypeError):
        return DEFAULT_SLIDES

@app.route("/")
def index():
    featured_ids = setting("featured_ids", "")
    if featured_ids:
        try:
            ids = [int(x) for x in featured_ids.split(",") if x.strip().isdigit()]
            featured = MenuItem.query.filter(MenuItem.available.is_(True), MenuItem.availability_status == "available", MenuItem.id.in_(ids)).all() if ids else []
            featured.sort(key=lambda item: ids.index(item.id))
        except (ValueError, TypeError):
            featured = []
    else:
        featured = MenuItem.query.filter(MenuItem.available.is_(True), MenuItem.availability_status == "available").limit(8).all()
    if not featured:
        featured = MenuItem.query.filter(MenuItem.available.is_(True), MenuItem.availability_status == "available").limit(8).all()
    return render_template("index.html", featured=featured, slides=get_slides(), categories=sorted({i.category for i in MenuItem.query.filter_by(available=True).all()}),
        site={"tagline":setting("tagline", "Good food. Good mood."), "story":setting("story", "Delicious food, thoughtfully prepared and served with warmth."), "phone":setting("phone", ""), "address":setting("address", "Jos South, Plateau State, Nigeria"), "whatsapp":setting("whatsapp", os.environ.get("JENNY_WHATSAPP_NUMBER", "")), "menu_heading":setting("menu_heading", "Still hot. Always loved."), "about_heading":setting("about_heading", "A little love in every plate."), "promotion_heading":setting("promotion_heading", "Something delicious is calling"), "promotion_text":setting("promotion_text", "Discover today’s favourites from Jenny’s Kitchen."), "promotion_link":setting("promotion_link", "/menu"), "promotion_active":setting("promotion_active", "0")})


@app.route("/menu")
def menu():
    items = MenuItem.query.filter(MenuItem.available.is_(True), MenuItem.availability_status == "available").all()
    categories = sorted({i.category for i in items})
    reviews = {}
    for review in Review.query.filter_by(approved=True).all():
        reviews.setdefault(review.menu_item_id, []).append(review)
    menu_schema = {"@context": "https://schema.org", "@type": "Menu", "name": "Jenny's Kitchen Menu", "hasMenuSection": []}
    for category in categories:
        section_items = [{"@type": "MenuItem", "name": item.name, "description": item.description or "", "offers": {"@type": "Offer", "price": float(item.price), "priceCurrency": "NGN"}} for item in items if item.category == category]
        menu_schema["hasMenuSection"].append({"@type": "MenuSection", "name": category, "hasMenuItem": section_items})
    return render_template("menu.html", items=items, categories=categories, active_category=request.args.get("category", "all"), reviews=reviews, menu_schema=menu_schema)


# ---------- Auth (customer) ----------
@app.route("/reserve", methods=["GET", "POST"])
def reserve_table():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        phone = request.form.get("phone", "").strip()[:30]
        date = request.form.get("date", "").strip()
        time = request.form.get("time", "").strip()
        try: guests = int(request.form.get("guests", 2))
        except ValueError: guests = 0
        if not name or len(phone) < 7 or not date or not time or not 1 <= guests <= 30:
            flash("Please check your name, phone, date, time and guest count, then submit again.")
            return redirect(url_for("reserve_table"))
        reference = "RSV-" + secrets.token_hex(4).upper()
        db.session.add(Reservation(reference=reference, customer_name=name, phone=phone,
            email=request.form.get("email", "").strip()[:120], reservation_date=date,
            reservation_time=time, guests=guests, notes=request.form.get("notes", "").strip()[:500]))
        db.session.commit()
        return render_template("reservation_success.html", reference=reference)
    return render_template("reserve.html", today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/admin/reservations")
@admin_required
def admin_reservations():
    reservations = Reservation.query.order_by(Reservation.created_at.desc()).all()
    return render_template("admin/reservations.html", reservations=reservations)


@app.route("/admin/reservations/<int:reservation_id>/status", methods=["POST"])
@admin_required
def reservation_status(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    status = request.form.get("status", "")
    if status in ("Pending", "Confirmed", "Seated", "Completed", "Cancelled"):
        reservation.status = status
        db.session.commit()
        flash("Reservation status updated.")
    else: flash("Choose a valid reservation status.")
    return redirect(url_for("admin_reservations"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form["phone"].strip()
        password = request.form.get("password", "")
        referral_code = request.form.get("referral_code", "").strip().upper()[:16]
        if not name or len(name) > 100 or "@" not in email or len(phone) < 7 or len(password) < 10:
            flash("Enter a valid name, email, phone number, and a password of at least 10 characters.")
            return redirect(url_for("signup"))
        if User.query.filter_by(email=email).first():
            flash("Email already registered. Please log in.")
            return redirect(url_for("login"))
        referred_by = User.query.filter_by(referral_code=referral_code).first() if referral_code else None
        if referral_code and not referred_by:
            flash("That referral code was not found. You can remove it and continue.")
            return redirect(url_for("signup"))
        user = User(full_name=name, email=email, phone=phone,
                    password_hash=generate_password_hash(password),
                    marketing_consent=request.form.get("marketing_consent") == "on",
                    referral_code=secrets.token_hex(4).upper(),
                    unsubscribe_token=secrets.token_urlsafe(32),
                    referred_by=referred_by.referral_code if referred_by else None)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash("Welcome to Jenny's Kitchen!")
        nxt = safe_local_redirect(request.args.get("next"), url_for("menu"))
        return redirect(nxt)
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            flash("Logged in.")
            nxt = safe_local_redirect(request.args.get("next"), url_for("menu"))
            return redirect(nxt)
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.")
    return redirect(url_for("index"))


# ---------- Cart API ----------
@app.route("/api/cart/add", methods=["POST"])
def cart_add():
    data = request.get_json() or {}
    item_id = str(data.get("id"))
    try:
        item = MenuItem.query.get(int(item_id))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid menu item."}), 400
    if not item or not item.available or item.availability_status != "available":
        return jsonify({"error": "This meal is currently unavailable."}), 404
    cart = get_cart()
    cart[item_id] = cart.get(item_id, 0) + 1
    save_cart(cart)
    return jsonify({"success": True, "cart_count": sum(cart.values())})


@app.route("/api/cart/remove", methods=["POST"])
def cart_remove():
    data = request.get_json() or {}
    item_id = str(data.get("id"))
    cart = get_cart()
    if item_id in cart:
        cart[item_id] -= 1
        if cart[item_id] <= 0:
            del cart[item_id]
    save_cart(cart)
    return jsonify({"success": True, "cart_count": sum(cart.values())})


@app.route("/api/promotion/validate", methods=["POST"])
def validate_promotion():
    data = request.get_json() or {}
    code = str(data.get("code", "")).strip().upper()[:40]
    subtotal = 0.0
    for item_id, quantity in get_cart().items():
        try:
            item = db.session.get(MenuItem, int(item_id))
            if item and item.available and item.availability_status == "available":
                subtotal += float(item.price) * int(quantity)
        except (TypeError, ValueError):
            continue
    promotion = Promotion.query.filter_by(code=code, active=True).first()
    if not promotion:
        return jsonify({"valid": False, "message": "We couldn't find an active code with that spelling. Check the code and try again."}), 404
    if subtotal < (promotion.minimum_total or 0):
        return jsonify({"valid": False, "message": f"This offer starts at ₦{promotion.minimum_total:,.0f}. Add another meal to unlock it."}), 400
    if promotion.usage_limit and promotion.used_count >= promotion.usage_limit:
        return jsonify({"valid": False, "message": "This offer has reached its redemption limit. Try another active offer."}), 400
    amount = subtotal * promotion.discount_value / 100 if promotion.discount_type == "percent" else promotion.discount_value
    amount = min(subtotal, max(0, amount))
    return jsonify({"valid": True, "code": promotion.code, "discount": round(amount, 2), "message": f"{promotion.code} applied — you save ₦{amount:,.2f}."})


@app.route("/api/cart/count")
def cart_count():
    return jsonify({"count": sum(get_cart().values())})


# ---------- Cart Page ----------
@app.route("/cart")
def cart_page():
    cart = get_cart()
    detailed, total = [], 0
    for item_id, qty in cart.items():
        item = MenuItem.query.get(int(item_id))
        if item:
            subtotal = item.price * qty
            total += subtotal
            detailed.append({"item": item, "qty": qty, "subtotal": subtotal})
    return render_template("cart.html", items=detailed, total=total)


@app.route("/cart/clear", methods=["POST"])
@login_required
def cart_clear():
    save_cart({})
    return jsonify({"success": True})


# ---------- Checkout ----------
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = get_cart()
    if not cart:
        flash("Your cart is empty.")
        return redirect(url_for("menu"))
    detailed, subtotal = [], 0.0
    for item_id, qty in cart.items():
        try:
            item = db.session.get(MenuItem, int(item_id))
            qty = int(qty)
        except (TypeError, ValueError):
            continue
        if item and item.available and item.availability_status == "available" and 1 <= qty <= 50:
            line_total = round(float(item.price) * qty, 2)
            subtotal += line_total
            detailed.append({"item": item, "qty": qty, "subtotal": line_total})
    if not detailed:
        save_cart({})
        flash("Your cart items are no longer available. Please choose your meals again.")
        return redirect(url_for("menu"))
    delivery_zones = DeliveryZone.query.filter_by(active=True).order_by(DeliveryZone.name).all()
    selected_zone = None
    zone_id = request.values.get("delivery_zone", "").strip()
    if zone_id.isdigit():
        selected_zone = DeliveryZone.query.filter_by(id=int(zone_id), active=True).first()
    delivery_fee = max(0, float(selected_zone.delivery_fee if selected_zone else (setting("delivery_fee", "0") or 0)))
    promotion = None
    promo_code = request.values.get("promotion_code", "").strip().upper()
    if promo_code:
        promotion = Promotion.query.filter_by(code=promo_code, active=True).first()
        if promotion and subtotal >= (promotion.minimum_total or 0) and (not promotion.usage_limit or promotion.used_count < promotion.usage_limit):
            discount = subtotal * promotion.discount_value / 100 if promotion.discount_type == "percent" else promotion.discount_value
            discount = min(subtotal, max(0, discount))
        else:
            promotion = None
            discount = 0
    else:
        discount = 0
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        phone = request.form.get("phone", "").strip()[:30]
        email = request.form.get("email", "").strip().lower()[:120]
        order_type = request.form.get("order_type", "delivery")
        payment_method = request.form.get("payment_method", "pay_on_pickup")
        address = request.form.get("address", "").strip()[:300] if order_type == "delivery" else ""
        notes = request.form.get("notes", "").strip()[:500]
        if not name or len(phone) < 7:
            flash("Please enter your name and a valid contact phone number.")
            return redirect(url_for("checkout"))
        if order_type not in ("delivery", "pickup"):
            flash("Please choose delivery or pickup.")
            return redirect(url_for("checkout"))
        if order_type == "delivery" and not address:
            flash("Please enter your delivery address.")
            return redirect(url_for("checkout"))
        if payment_method not in ("paystack", "pay_on_pickup"):
            flash("Please choose a valid payment method.")
            return redirect(url_for("checkout"))
        if payment_method == "paystack" and not app.config.get("PAYSTACK_SECRET_KEY"):
            flash("Online payment is not configured yet. Choose pay later or contact the kitchen.")
            return redirect(url_for("checkout"))
        if payment_method == "paystack" and (not email or "@" not in email or len(email) > 120):
            flash("Enter a valid email address for Paystack payment.")
            return redirect(url_for("checkout"))
        # Recheck all prices and availability on the server at order creation.
        current_subtotal = 0.0
        for row in detailed:
            fresh = db.session.get(MenuItem, row["item"].id)
            if not fresh or not fresh.available or fresh.availability_status != "available":
                flash(f"{row['item'].name} is no longer available. Please update your cart.")
                return redirect(url_for("cart_page"))
            row["fresh_item"] = fresh
            row["subtotal"] = round(float(fresh.price) * row["qty"], 2)
            current_subtotal += float(fresh.price) * row["qty"]
        applied_discount = 0.0
        points_to_redeem = 0
        loyalty_discount = 0.0
        valid_promotion = None
        if promo_code:
            valid_promotion = Promotion.query.filter_by(code=promo_code, active=True).with_for_update().first()
            if valid_promotion and current_subtotal >= (valid_promotion.minimum_total or 0) and (not valid_promotion.usage_limit or valid_promotion.used_count < valid_promotion.usage_limit):
                applied_discount = current_subtotal * valid_promotion.discount_value / 100 if valid_promotion.discount_type == "percent" else valid_promotion.discount_value
                applied_discount = min(current_subtotal, max(0, applied_discount))
            else:
                flash("That promotion code is invalid, expired, or doesn't meet the minimum order value.")
                return redirect(url_for("checkout"))
        if current_user.is_authenticated and request.form.get("use_points") == "on":
            available_points = max(0, int(current_user.loyalty_points or 0))
            points_to_redeem = (available_points // 100) * 100
            loyalty_discount = min(max(0, current_subtotal - applied_discount), (points_to_redeem // 100) * 500)
            points_to_redeem = min(points_to_redeem, int((loyalty_discount // 500) * 100))
        if order_type == "delivery" and delivery_zones and not selected_zone:
            flash("Choose your delivery area so we can calculate the correct rider fee. If your area is not listed, contact support before ordering.")
            return redirect(url_for("checkout"))
        fee = delivery_fee if order_type == "delivery" else 0
        total = round(max(0, current_subtotal - applied_discount - loyalty_discount) + fee, 2)
        zero_total_order = total <= 0 and payment_method == "paystack"
        if zero_total_order:
            # A zero-value order must not be sent to Paystack for a zero-kobo transaction.
            payment_method = "pay_on_pickup"
        order = Order(order_number=gen_order_number(), customer_name=name, phone=phone,
                      email=email or None, address=address, order_type=order_type, total=total,
                      delivery_fee=fee, delivery_zone=selected_zone.name if selected_zone and order_type == "delivery" else None, delivery_eta_min=selected_zone.eta_min if selected_zone and order_type == "delivery" else None, delivery_eta_max=selected_zone.eta_max if selected_zone and order_type == "delivery" else None, notes=notes, promotion_code=promo_code if valid_promotion else None,
                      status="Confirmed" if zero_total_order else "Pending", payment_method=payment_method,
                      payment_status="paid" if zero_total_order else ("pending" if payment_method == "paystack" else "unpaid"),
                      user_id=current_user.id if current_user.is_authenticated else None,
                      loyalty_points_redeemed=points_to_redeem)
        if payment_method == "paystack":
            order.payment_reference = make_payment_reference()
        db.session.add(order)
        db.session.flush()
        if points_to_redeem and current_user.is_authenticated:
            current_user.loyalty_points = max(0, int(current_user.loyalty_points or 0) - points_to_redeem)
            db.session.add(LoyaltyLedger(user_id=current_user.id, order_id=order.id, points=-points_to_redeem, reason=f"Redeemed on order {order.order_number}"))
        for row in detailed:
            fresh_item = row.get("fresh_item", row["item"])
            db.session.add(OrderItem(order_id=order.id, item_name=fresh_item.name,
                                     price=fresh_item.price, quantity=row["qty"]))
        if valid_promotion and payment_method != "paystack":
            valid_promotion.used_count = (valid_promotion.used_count or 0) + 1
        db.session.commit()
        save_cart({})
        if payment_method == "paystack":
            try:
                if not email:
                    raise RuntimeError("Enter an email address to pay securely with Paystack.")
                result = paystack_request("/transaction/initialize", {
                    "email": email, "amount": int(round(total * 100)),
                    "reference": order.payment_reference,
                    "callback_url": url_for("paystack_callback", _external=True),
                    "metadata": {"order_number": order.order_number, "customer_name": name, "phone": phone}
                })
                if not result.get("status") or not result.get("data", {}).get("authorization_url"):
                    raise RuntimeError("Paystack did not return a payment link.")
                return redirect(result["data"]["authorization_url"])
            except RuntimeError as exc:
                order.payment_status = "initialization_failed"
                db.session.commit()
                app.logger.warning("Paystack initialization failed for %s: %s", order.order_number, exc)
                flash(str(exc) + " Your order was recorded as unpaid; contact the kitchen before retrying.")
                send_order_notification(order)
                return redirect(url_for("order_success", order_number=order.order_number))
        send_order_notification(order)
        send_customer_order_update(order)
        return redirect(url_for("order_success", order_number=order.order_number))
    return render_template("checkout.html", items=detailed, delivery_zones=delivery_zones, selected_zone=selected_zone, total=round(max(0, subtotal-discount)+delivery_fee, 2), subtotal=subtotal,
                           delivery_fee=delivery_fee, discount=discount, promotion=promotion,
                           paystack_ready=bool(app.config.get("PAYSTACK_SECRET_KEY")), loyalty_points=(current_user.loyalty_points or 0) if current_user.is_authenticated else 0, site={"phone": setting("phone", "")})


@app.route("/payments/paystack/callback")
def paystack_callback():
    reference = request.args.get("reference", "").strip()
    order = Order.query.filter_by(payment_reference=reference).first() if reference else None
    if not order:
        flash("We couldn't match this payment to an order. Please contact Jenny's Kitchen with your payment reference.")
        return redirect(url_for("track"))
    try:
        result = paystack_request("/transaction/verify/" + urllib.parse.quote(reference, safe=""))
        data = result.get("data", {})
        expected_kobo = int(round(float(order.total) * 100))
        if result.get("status") and data.get("status") == "success" and data.get("reference") == reference and int(data.get("amount", -1)) == expected_kobo and data.get("currency") == "NGN":
            was_paid = order.payment_status == "paid"
            order.payment_status = "paid"
            if not was_paid and order.promotion_code:
                promo = Promotion.query.filter_by(code=order.promotion_code).first()
                if promo:
                    promo.used_count = (promo.used_count or 0) + 1
            if order.status == "Pending":
                order.status = "Confirmed"
            db.session.commit()
            if not was_paid:
                send_order_notification(order)
                send_customer_order_update(order)
            flash("Payment verified successfully. Your order is confirmed as paid.")
        else:
            order.payment_status = "verification_failed"
            db.session.commit()
            flash("Payment has not been verified as successful. Do not pay again until you check your order status.")
    except RuntimeError as exc:
        app.logger.exception("Paystack verification failed for order %s", order.order_number)
        flash("We couldn't verify the payment right now. Your order remains unpaid until verification succeeds.")
    return redirect(url_for("order_success", order_number=order.order_number))


@app.route("/payments/paystack/webhook", methods=["POST"])
def paystack_webhook():
    secret = app.config.get("PAYSTACK_SECRET_KEY", "")
    signature = request.headers.get("x-paystack-signature", "")
    expected = hmac.new(secret.encode(), request.get_data(), hashlib.sha512).hexdigest() if secret else ""
    if not signature or not expected or not hmac.compare_digest(signature, expected):
        return jsonify({"error": "Invalid signature"}), 401
    event = request.get_json(silent=True) or {}
    if event.get("event") == "charge.success":
        reference = str((event.get("data") or {}).get("reference", ""))
        order = Order.query.filter_by(payment_reference=reference).first()
        if order and order.payment_status != "paid":
            try:
                verified = paystack_request("/transaction/verify/" + urllib.parse.quote(reference, safe=""))
                payment = verified.get("data", {})
                if (verified.get("status") and payment.get("status") == "success" and payment.get("reference") == reference and int(payment.get("amount", -1)) == int(round(order.total * 100)) and payment.get("currency") == "NGN"):
                    order.payment_status = "paid"
                    if order.promotion_code:
                        promo = Promotion.query.filter_by(code=order.promotion_code).first()
                        if promo:
                            promo.used_count = (promo.used_count or 0) + 1
                    if order.status == "Pending":
                        order.status = "Confirmed"
                    db.session.commit()
                    send_order_notification(order)
                    send_customer_order_update(order)
            except RuntimeError:
                app.logger.exception("Webhook verification failed for %s", reference)
                return jsonify({"error": "Verification temporarily unavailable"}), 503
    return jsonify({"received": True}), 200


@app.route("/order/success/<order_number>")
def order_success(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    return render_template("order_success.html", order=order)


@app.route("/track", methods=["GET", "POST"])
def track():
    order = None
    if request.method == "POST":
        num = request.form["order_number"].strip()
        order = Order.query.filter_by(order_number=num).first()
        if not order:
            flash("Order not found. Check your order number.")
    return render_template("track.html", order=order)



# ---------- Phase 3: customer relationships ----------
@app.route("/reviews")
def public_reviews():
    reviews = Review.query.filter_by(approved=True).order_by(Review.created_at.desc()).limit(100).all()
    return render_template("reviews.html", reviews=reviews)

@app.route("/account")
@login_required
def account():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).limit(100).all()
    favorites = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    ledger = LoyaltyLedger.query.filter_by(user_id=current_user.id).order_by(LoyaltyLedger.created_at.desc()).limit(30).all()
    reviews = Review.query.filter_by(user_id=current_user.id).all()
    reviewed_keys = {(r.order_id, r.menu_item_id) for r in reviews}
    reviewable = []
    for order in orders:
        if order.status == "Delivered":
            for line in order.items:
                item = MenuItem.query.filter_by(name=line.item_name).first()
                if item and (order.id, item.id) not in reviewed_keys:
                    reviewable.append({"order": order, "item": item})
    return render_template("account.html", orders=orders, favorites=favorites, ledger=ledger, reviewable=reviewable)

@app.route("/account/reorder/<int:order_id>", methods=["POST"])
@login_required
def reorder(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    cart = get_cart()
    added = 0
    for line in order.items:
        item = MenuItem.query.filter_by(name=line.item_name, available=True).first()
        if item:
            key = str(item.id)
            cart[key] = min(50, int(cart.get(key, 0)) + int(line.quantity))
            added += 1
    save_cart(cart)
    flash("Your previous order is back in the bag." if added else "Those meals are currently unavailable. Please browse the menu.")
    return redirect(url_for("cart_page" if added else "menu"))

@app.route("/favorites/toggle/<int:item_id>", methods=["POST"])
@login_required
def toggle_favorite(item_id):
    item = MenuItem.query.get_or_404(item_id)
    favorite = Favorite.query.filter_by(user_id=current_user.id, menu_item_id=item.id).first()
    if favorite:
        db.session.delete(favorite)
        message = "Removed from favourites."
    else:
        db.session.add(Favorite(user_id=current_user.id, menu_item_id=item.id))
        message = "Saved to favourites."
    db.session.commit()
    flash(message)
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("menu"))

@app.route("/reviews/<int:order_id>/<int:item_id>", methods=["POST"])
@login_required
def submit_review(order_id, item_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id, status="Delivered").first_or_404()
    item = MenuItem.query.get_or_404(item_id)
    purchased = any(line.item_name == item.name for line in order.items)
    if not purchased:
        abort(403)
    try:
        rating = int(request.form.get("rating", "0"))
    except ValueError:
        rating = 0
    body = request.form.get("body", "").strip()[:700]
    if rating not in range(1, 6):
        flash("Please choose a rating from 1 to 5.")
        return redirect(url_for("account"))
    existing = Review.query.filter_by(user_id=current_user.id, menu_item_id=item.id, order_id=order.id).first()
    if existing:
        flash("You have already reviewed this meal for that order.")
    else:
        db.session.add(Review(user_id=current_user.id, menu_item_id=item.id, order_id=order.id, rating=rating, body=body, approved=False))
        db.session.commit()
        flash("Thanks for your feedback! It will appear after a quick review by the kitchen.")
    return redirect(url_for("account"))

@app.route("/account/preferences", methods=["POST"])
@login_required
def account_preferences():
    current_user.marketing_consent = request.form.get("marketing_consent") == "on"
    db.session.commit()
    flash("Your promotional email preference has been updated.")
    return redirect(url_for("account"))

@app.route("/admin/reviews")
@admin_required
def admin_reviews():
    return render_template("admin/reviews.html", reviews=Review.query.order_by(Review.created_at.desc()).all())

@app.route("/admin/reviews/<int:review_id>/moderate", methods=["POST"])
@admin_required
def moderate_review(review_id):
    review = Review.query.get_or_404(review_id)
    action = request.form.get("action")
    if action == "approve":
        review.approved = True
    elif action == "hide":
        review.approved = False
    elif action == "delete":
        db.session.delete(review)
    else:
        abort(400)
    db.session.commit()
    flash("Review moderation saved.")
    return redirect(url_for("admin_reviews"))

# ---------- Phase 4: content, SEO, consent-aware analytics ----------
@app.route("/privacy/analytics-consent", methods=["POST"])
def analytics_consent():
    choice = request.form.get("choice", "")
    if choice not in ("accept", "reject"):
        abort(400)
    response = redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("index"))
    response.set_cookie("jk_analytics_consent", "yes" if choice == "accept" else "no", max_age=180*24*3600, httponly=False, samesite="Lax", secure=(request.is_secure or app.config.get("SESSION_COOKIE_SECURE", False)))
    return response

@app.route("/api/analytics/event", methods=["POST"])
def analytics_event():
    if request.cookies.get("jk_analytics_consent") != "yes":
        return "", 204
    data = request.get_json(silent=True) or {}
    allowed = {"page_view", "menu_search", "add_to_cart", "checkout_start", "order_complete", "campaign_click"}
    name = str(data.get("event", ""))[:40]
    if name not in allowed:
        return jsonify({"error": "Unsupported event"}), 400
    path = str(data.get("path", "/"))[:300]
    campaign = str(data.get("campaign", ""))[:100] or None
    # Avoid storing IP addresses, emails, order numbers, or raw customer identifiers.
    sid = session.get("analytics_sid")
    if not sid:
        sid = secrets.token_hex(12)
        session["analytics_sid"] = sid
    db.session.add(AnalyticsEvent(event_name=name, path=path, campaign=campaign, session_key=hashlib.sha256(sid.encode()).hexdigest()[:32]))
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/p/<slug>")
def content_page(slug):
    page = ContentPage.query.filter_by(slug=slug, published=True).first_or_404()
    return render_template("content_page.html", page=page)

@app.route("/admin/content", methods=["GET", "POST"])
@admin_required
def admin_content():
    if request.method == "POST":
        page_id = request.form.get("page_id", "")
        page = db.session.get(ContentPage, int(page_id)) if page_id.isdigit() else None
        slug = request.form.get("slug", "").strip().lower().strip("-")[:80]
        slug = "-".join(part for part in slug.split() if part)
        title = request.form.get("title", "").strip()[:120]
        if not slug or not slug.replace("-", "").isalnum() or not title:
            flash("Use a simple URL slug (letters, numbers, hyphens) and a page title.")
            return redirect(url_for("admin_content"))
        duplicate = ContentPage.query.filter(ContentPage.slug == slug, ContentPage.id != (page.id if page else -1)).first()
        if duplicate:
            flash("That page URL is already in use.")
            return redirect(url_for("admin_content"))
        if page is None:
            page = ContentPage(slug=slug, title=title)
            db.session.add(page)
        page.slug = slug
        page.title = title
        page.summary = request.form.get("summary", "").strip()[:300]
        # Plain text only; template escapes all content to prevent injected scripts.
        page.body = request.form.get("body", "").strip()[:5000]
        page.cta_label = request.form.get("cta_label", "Explore menu").strip()[:60]
        page.cta_url = safe_destination(request.form.get("cta_url", "/menu"), "/menu")
        page.published = request.form.get("published") == "on"
        db.session.commit()
        flash("Page saved and published status updated.")
        return redirect(url_for("admin_content", edit=page.id))
    edit_id = request.args.get("edit", "")
    edit_page = db.session.get(ContentPage, int(edit_id)) if edit_id.isdigit() else None
    return render_template("admin/content.html", pages=ContentPage.query.order_by(ContentPage.updated_at.desc()).all(), edit_page=edit_page)

@app.route("/admin/campaigns", methods=["GET", "POST"])
@admin_required
def admin_campaigns():
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120]
        subject = request.form.get("subject", "").strip()[:180]
        body = request.form.get("body", "").strip()[:3000]
        if not title or not subject or not body:
            flash("Campaign title, email subject, and message are required.")
            return redirect(url_for("admin_campaigns"))
        campaign = Campaign(title=title, subject=subject, body=body, status="draft")
        db.session.add(campaign)
        db.session.commit()
        flash("Campaign saved as a draft. It has not been sent.")
        return redirect(url_for("admin_campaigns"))
    return render_template("admin/campaigns.html", campaigns=Campaign.query.order_by(Campaign.created_at.desc()).all())

@app.route("/admin/campaigns/<int:campaign_id>/send", methods=["POST"])
@admin_required
def send_campaign(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    if campaign.status in ("sent", "partial"):
        flash("This campaign was already sent or partially sent and cannot be resent safely. Create a new campaign after reviewing recipients.")
        return redirect(url_for("admin_campaigns"))
    host, sender = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
    if not host or not sender:
        flash("Configure SMTP_HOST and SMTP_FROM before sending campaigns.")
        return redirect(url_for("admin_campaigns"))
    import smtplib
    from email.message import EmailMessage
    recipients = User.query.filter_by(marketing_consent=True).all()
    sent = 0
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=20) as server:
            server.starttls()
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            for user in recipients:
                if not user.email:
                    continue
                msg = EmailMessage()
                msg["Subject"] = campaign.subject
                msg["From"] = sender
                msg["To"] = user.email
                msg["List-Unsubscribe"] = f"<{url_for('unsubscribe_campaigns', token=user.unsubscribe_token, _external=True)}>"
                msg.set_content(campaign.body + "\n\nYou received this because you opted in to Jenny's Kitchen promotional emails. To unsubscribe: " + url_for('unsubscribe_campaigns', token=user.unsubscribe_token, _external=True))
                server.send_message(msg)
                sent += 1
    except Exception:
        app.logger.exception("Campaign sending interrupted for campaign %s", campaign.id)
        campaign.status = "partial"
        campaign.sent_count = sent
        db.session.commit()
        flash(f"Campaign sending stopped after {sent} emails due to an SMTP error. Review before retrying; avoid duplicate sends.")
        return redirect(url_for("admin_campaigns"))
    campaign.status = "sent"
    campaign.sent_count = sent
    campaign.sent_at = datetime.utcnow()
    db.session.commit()
    flash(f"Campaign sent to {sent} opted-in customers.")
    return redirect(url_for("admin_campaigns"))

@app.route("/unsubscribe/<token>")
def unsubscribe_campaigns(token):
    user = User.query.filter_by(unsubscribe_token=token).first_or_404()
    user.marketing_consent = False
    db.session.commit()
    return render_template("unsubscribe.html")

@app.route("/admin/analytics")
@admin_required
def admin_analytics():
    from sqlalchemy import func
    events = db.session.query(AnalyticsEvent.event_name, func.count(AnalyticsEvent.id)).group_by(AnalyticsEvent.event_name).all()
    campaigns = db.session.query(AnalyticsEvent.campaign, func.count(AnalyticsEvent.id)).filter(AnalyticsEvent.campaign.isnot(None)).group_by(AnalyticsEvent.campaign).all()
    return render_template("admin/analytics.html", events=events, campaigns=campaigns, total=AnalyticsEvent.query.count(), consent_count=User.query.filter_by(marketing_consent=True).count())

@app.route("/sitemap.xml")
def sitemap():
    from flask import make_response
    pages = ContentPage.query.filter_by(published=True).all()
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for endpoint in ("index", "menu"):
        xml.append(f'<url><loc>{url_for(endpoint, _external=True)}</loc></url>')
    for page in pages:
        xml.append(f'<url><loc>{url_for("content_page", slug=page.slug, _external=True)}</loc></url>')
    xml.append('</urlset>')
    response = make_response("".join(xml))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response

@app.route("/robots.txt")
def robots():
    from flask import make_response
    response = make_response("User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /account\nDisallow: /checkout\nDisallow: /cart\nDisallow: /login\nDisallow: /signup\nDisallow: /track\nSitemap: " + url_for("sitemap", _external=True) + "\n")
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


# ---------- Admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        admin = Admin.query.filter_by(username=u).first()
        if admin and check_password_hash(admin.password_hash, p):
            session.clear()
            session["admin_id"] = admin.id
            session.modified = True
            flash("Logged in as admin.")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.modified = True
    flash("Admin logged out.")
    return redirect(url_for("index"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    stats = {
        "total_orders": len(orders),
        "pending": sum(1 for o in orders if o.status == "Pending"),
        "delivered": sum(1 for o in orders if o.status == "Delivered"),
        "revenue": sum(o.total for o in orders if o.status == "Delivered" and o.payment_status in ("paid", "unpaid")),
        "unpaid": sum(1 for o in orders if o.payment_status not in ("paid",)),
        "average_order": (sum(o.total for o in orders if o.status != "Cancelled") / max(1, sum(1 for o in orders if o.status != "Cancelled"))),
    }
    return render_template("admin/dashboard.html", orders=orders, stats=stats)


@app.route("/admin/order/<int:order_id>/status", methods=["POST"])
@admin_required
def update_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status", "")
    allowed_statuses = {"Pending", "Confirmed", "Preparing", "Ready for Pickup", "Out for Delivery", "Delivered", "Cancelled"}
    if new_status not in allowed_statuses:
        flash("Invalid order status.")
        return redirect(url_for("admin_dashboard"))
    previous_status = order.status
    order.status = new_status
    if new_status == "Cancelled" and previous_status != "Cancelled" and order.user_id and (order.loyalty_points_redeemed or 0) > 0:
        customer_refund = db.session.get(User, order.user_id)
        if customer_refund:
            refund_points = int(order.loyalty_points_redeemed or 0)
            customer_refund.loyalty_points = (customer_refund.loyalty_points or 0) + refund_points
            db.session.add(LoyaltyLedger(user_id=customer_refund.id, order_id=order.id, points=refund_points, reason=f"Refunded cancelled order {order.order_number}"))
            order.loyalty_points_redeemed = 0
    if new_status == "Delivered" and order.user_id and not order.loyalty_awarded:
        customer = db.session.get(User, order.user_id)
        if customer:
            points = max(1, int(float(order.total) // 1000))  # 1 point per ₦1,000 spent
            customer.loyalty_points = (customer.loyalty_points or 0) + points
            db.session.add(LoyaltyLedger(user_id=customer.id, order_id=order.id, points=points, reason=f"Order {order.order_number}"))
            order.loyalty_awarded = True
            if customer.referred_by:
                referrer = User.query.filter_by(referral_code=customer.referred_by).first()
                if referrer and Order.query.filter_by(user_id=customer.id, status="Delivered").count() <= 1:
                    referrer.loyalty_points = (referrer.loyalty_points or 0) + 100
                    db.session.add(LoyaltyLedger(user_id=referrer.id, order_id=order.id, points=100, reason=f"Referral reward for {customer.full_name[:40]}"))
                    customer.loyalty_points = (customer.loyalty_points or 0) + 100
                    db.session.add(LoyaltyLedger(user_id=customer.id, order_id=order.id, points=100, reason="Welcome referral reward"))
    db.session.commit()
    if previous_status != new_status:
        send_order_notification(order)
        send_customer_order_update(order)
    flash(f"Order {order.order_number} → {order.status}")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/menu", methods=["GET", "POST"])
@admin_required
def admin_menu():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        description = request.form.get("description", "").strip()[:300]
        category = request.form.get("category", "").strip()[:50]
        try:
            price = float(request.form.get("price", "0"))
        except ValueError:
            price = 0
        if not name or not category or not (0 < price <= 100000000):
            flash("Enter a meal name, category, and a valid positive price.")
            return redirect(url_for("admin_menu"))
        filename = process_image(request.files.get("image")) or "default.jpg"
        item = MenuItem(name=name, description=description, price=price, category=category, image=filename, availability_status="available")
        db.session.add(item)
        db.session.commit()
        flash("Item added.")
        return redirect(url_for("admin_menu"))
    items = MenuItem.query.order_by(MenuItem.category, MenuItem.name).all()
    return render_template("admin/menu.html", items=items)


@app.route("/admin/menu/<int:item_id>/edit", methods=["POST"])
@admin_required
def edit_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    if request.form.get("name"):
        item.name = request.form["name"]
    if request.form.get("description"):
        item.description = request.form["description"]
    if request.form.get("price"):
        try:
            candidate_price = float(request.form["price"])
            if not (0 < candidate_price <= 100000000):
                raise ValueError
            item.price = candidate_price
        except ValueError:
            flash("Price must be a positive valid number. Other valid changes were saved only if submitted again.")
            return redirect(url_for("admin_menu"))
    if request.form.get("category"):
        item.category = request.form["category"]
    if "featured_label" in request.form:
        label = request.form.get("featured_label", "").strip().lower()
        item.featured_label = label if label in ("", "popular", "new", "best seller") else ""
    new_img = process_image(request.files.get("image"))
    if new_img:
        item.image = new_img
    db.session.commit()
    flash("Item updated.")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/availability", methods=["POST"])
@admin_required
def set_item_availability(item_id):
    item = MenuItem.query.get_or_404(item_id)
    status = request.form.get("availability_status", "")
    if status not in ("available", "temporarily_unavailable", "sold_out_today", "hidden"):
        flash("Choose a valid menu availability status.")
    else:
        item.availability_status = status
        item.available = status != "hidden"
        db.session.commit()
        flash("Menu availability updated.")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Item deleted.")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/toggle", methods=["POST"])
@admin_required
def toggle_item(item_id):
    item = MenuItem.query.get_or_404(item_id)
    item.available = not item.available
    item.availability_status = "available" if item.available else "hidden"
    db.session.commit()
    return redirect(url_for("admin_menu"))


@app.route("/admin/delivery-zones", methods=["GET", "POST"])
@admin_required
def admin_delivery_zones():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        try:
            fee = float(request.form.get("delivery_fee", "0")); eta_min = int(request.form.get("eta_min", "30")); eta_max = int(request.form.get("eta_max", "60"))
        except ValueError:
            flash("Enter a valid fee and delivery-time range."); return redirect(url_for("admin_delivery_zones"))
        if not name or fee < 0 or not 1 <= eta_min <= eta_max <= 1440:
            flash("Check the area name, non-negative rider fee and ETA range (1–1440 minutes).")
            return redirect(url_for("admin_delivery_zones"))
        existing = DeliveryZone.query.filter_by(name=name).first()
        if existing:
            existing.delivery_fee, existing.eta_min, existing.eta_max, existing.active = fee, eta_min, eta_max, True
        else:
            db.session.add(DeliveryZone(name=name, delivery_fee=fee, eta_min=eta_min, eta_max=eta_max))
        db.session.commit(); flash("Delivery area saved.")
        return redirect(url_for("admin_delivery_zones"))
    return render_template("admin/delivery_zones.html", zones=DeliveryZone.query.order_by(DeliveryZone.name).all())


@app.route("/admin/delivery-zones/<int:zone_id>/toggle", methods=["POST"])
@admin_required
def toggle_delivery_zone(zone_id):
    zone = DeliveryZone.query.get_or_404(zone_id); zone.active = not zone.active
    db.session.commit(); flash("Delivery area availability updated.")
    return redirect(url_for("admin_delivery_zones"))


@app.route("/admin/promotions", methods=["GET", "POST"])
@admin_required
def admin_promotions():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()[:40]
        description = request.form.get("description", "").strip()[:200]
        discount_type = request.form.get("discount_type", "fixed")
        try:
            value = float(request.form.get("discount_value", "0"))
            minimum = float(request.form.get("minimum_total", "0"))
            limit = int(request.form.get("usage_limit", "0"))
        except ValueError:
            flash("Enter valid numbers for promotion values.")
            return redirect(url_for("admin_promotions"))
        if not code or not code.replace("-", "").replace("_", "").isalnum() or value <= 0 or minimum < 0 or limit < 0 or discount_type not in ("fixed", "percent") or (discount_type == "percent" and value > 100):
            flash("Check the promotion code and discount values.")
            return redirect(url_for("admin_promotions"))
        if Promotion.query.filter_by(code=code).first():
            flash("That promotion code already exists.")
            return redirect(url_for("admin_promotions"))
        db.session.add(Promotion(code=code, description=description, discount_type=discount_type,
                                 discount_value=value, minimum_total=minimum, usage_limit=limit, active=True))
        db.session.commit()
        flash("Promotion created.")
        return redirect(url_for("admin_promotions"))
    return render_template("admin/promotions.html", promotions=Promotion.query.order_by(Promotion.id.desc()).all())


@app.route("/admin/promotions/<int:promotion_id>/toggle", methods=["POST"])
@admin_required
def toggle_promotion(promotion_id):
    promotion = db.session.get(Promotion, promotion_id) or abort(404)
    promotion.active = not promotion.active
    db.session.commit()
    flash("Promotion status updated.")
    return redirect(url_for("admin_promotions"))


@app.route("/admin/site", methods=["GET", "POST"])
@admin_required
def admin_site():
    import json
    if request.method == "POST":
        for key in ("tagline", "story", "phone", "address", "whatsapp", "menu_heading", "about_heading", "delivery_fee", "promotion_heading", "promotion_text", "promotion_link", "promotion_active"):
            value = ("1" if request.form.get(key) else "0") if key == "promotion_active" else request.form.get(key, "").strip()
            if key == "promotion_link":
                value = safe_destination(value)
            if key == "delivery_fee":
                try:
                    value = str(max(0, float(value or 0)))
                except ValueError:
                    value = "0"
            set_setting(key, value)
        ids = request.form.getlist("featured_ids")
        set_setting("featured_ids", ",".join(x for x in ids if x.isdigit()))
        slides = []
        for n in range(1, 4):
            title = request.form.get(f"slide{n}_title", "").strip()
            image = request.form.get(f"slide{n}_image", "").strip()
            if title and image:
                slides.append({"eyebrow": request.form.get(f"slide{n}_eyebrow", "" ).strip() or "FRESH FROM OUR KITCHEN", "title": title, "description": request.form.get(f"slide{n}_description", "").strip(), "image": image, "button": request.form.get(f"slide{n}_button", "Explore the menu").strip() or "Explore the menu", "link": safe_destination(request.form.get(f"slide{n}_link", "/menu"))})
        if slides:
            set_setting("hero_slides", json.dumps(slides))
        db.session.commit()
        flash("Website content saved successfully.")
        return redirect(url_for("admin_site"))
    items = MenuItem.query.order_by(MenuItem.category, MenuItem.name).all()
    selected = {x for x in setting("featured_ids", "").split(",") if x}
    slides = get_slides()
    slides = (slides + DEFAULT_SLIDES)[:3]
    site = {key: setting(key, default) for key, default in {"tagline":"Good food. Good mood.", "story":"Delicious food, thoughtfully prepared and served with warmth.", "phone":"", "address":"Jos South, Plateau State, Nigeria", "whatsapp":"", "menu_heading":"Our menu", "about_heading":"A little more about us", "delivery_fee":"0", "promotion_heading":"Something delicious is calling", "promotion_text":"Discover today’s favourites from Jenny’s Kitchen.", "promotion_link":"/menu", "promotion_active":"0"}.items()}
    return render_template("admin/site.html", items=items, selected=selected, slides=slides, site=site)

# ---------- RUN THE APP ----------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()
    # Changed to 0.0.0.0 so your phone can connect over WiFi
    app.run(host="0.0.0.0", port=5000, debug=(os.environ.get("FLASK_DEBUG") == "1" and os.environ.get("APP_ENV") != "production" and os.environ.get("FLASK_ENV") != "production"))