from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    marketing_consent = db.Column(db.Boolean, nullable=False, default=False)
    loyalty_points = db.Column(db.Integer, nullable=False, default=0)
    referral_code = db.Column(db.String(16), unique=True)
    referred_by = db.Column(db.String(16))
    unsubscribe_token = db.Column(db.String(64), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300))
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(500), default="default.jpg")
    available = db.Column(db.Boolean, default=True)
    availability_status = db.Column(db.String(30), nullable=False, default="available")
    featured_label = db.Column(db.String(30), default="")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(24), unique=True, nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(300))
    order_type = db.Column(db.String(20), default="delivery")
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default="Pending")
    payment_method = db.Column(db.String(30), default="pay_on_pickup")
    payment_status = db.Column(db.String(30), default="unpaid")
    payment_reference = db.Column(db.String(120), unique=True)
    email = db.Column(db.String(120))
    notes = db.Column(db.String(500))
    delivery_fee = db.Column(db.Float, default=0)
    delivery_zone = db.Column(db.String(100))
    delivery_eta_min = db.Column(db.Integer)
    delivery_eta_max = db.Column(db.Integer)
    promotion_code = db.Column(db.String(40))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    loyalty_awarded = db.Column(db.Boolean, nullable=False, default=False)
    loyalty_points_redeemed = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("orders", lazy=True))
    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=1)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)


class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False, default="")


class Promotion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    description = db.Column(db.String(200), default="")
    discount_type = db.Column(db.String(20), default="fixed")
    discount_value = db.Column(db.Float, nullable=False, default=0)
    minimum_total = db.Column(db.Float, default=0)
    active = db.Column(db.Boolean, default=True)
    usage_limit = db.Column(db.Integer, default=0)
    used_count = db.Column(db.Integer, default=0)


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_item.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    item = db.relationship("MenuItem")
    __table_args__ = (db.UniqueConstraint("user_id", "menu_item_id", name="uq_favorite_user_item"),)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_item.id"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    body = db.Column(db.String(700), nullable=False, default="")
    approved = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")
    item = db.relationship("MenuItem")
    order = db.relationship("Order")
    __table_args__ = (db.UniqueConstraint("user_id", "menu_item_id", "order_id", name="uq_review_per_order_item"),)


class LoyaltyLedger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=True, index=True)
    points = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")


class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    body = db.Column(db.String(3000), nullable=False)
    status = db.Column(db.String(20), default="draft", nullable=False)
    sent_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)


class ContentPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.String(300), default="")
    body = db.Column(db.String(5000), default="")
    cta_label = db.Column(db.String(60), default="Explore menu")
    cta_url = db.Column(db.String(300), default="/menu")
    published = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalyticsEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(40), nullable=False, index=True)
    path = db.Column(db.String(300), nullable=False)
    campaign = db.Column(db.String(100))
    session_key = db.Column(db.String(64), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(24), unique=True, nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120))
    reservation_date = db.Column(db.String(20), nullable=False)
    reservation_time = db.Column(db.String(10), nullable=False)
    guests = db.Column(db.Integer, nullable=False, default=2)
    notes = db.Column(db.String(500), default="")
    status = db.Column(db.String(30), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MealBundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default="")
    price = db.Column(db.Float, nullable=False)
    bundle_type = db.Column(db.String(30), default="individual")
    active = db.Column(db.Boolean, default=True)


class DeliveryZone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    delivery_fee = db.Column(db.Float, nullable=False, default=0)
    eta_min = db.Column(db.Integer, nullable=False, default=30)
    eta_max = db.Column(db.Integer, nullable=False, default=60)
    active = db.Column(db.Boolean, nullable=False, default=True)
