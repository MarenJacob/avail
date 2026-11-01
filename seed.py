import os
from app import app, db, ensure_schema_compatibility
from models import MenuItem, Admin
from werkzeug.security import generate_password_hash

menu = [
    # Rice
    {"name": "Jollof Rice + Chicken", "price": 3500, "category": "Rice",
     "description": "Smoky jollof rice with grilled chicken"},
    {"name": "Fried Rice + Turkey", "price": 4000, "category": "Rice",
     "description": "Veggie fried rice with peppered turkey"},
    {"name": "White Rice + Stew", "price": 2500, "category": "Rice",
     "description": "Classic white rice and tomato stew"},
    {"name": "Jollof Spaghetti", "price": 2800, "category": "Rice",
     "description": "Spicy jollof-style pasta"},

    # Shawarma
    {"name": "Chicken Shawarma", "price": 2500, "category": "Shawarma",
     "description": "Grilled chicken wrapped in pita"},
    {"name": "Beef Shawarma", "price": 2800, "category": "Shawarma",
     "description": "Spicy beef strips with veggies"},
    {"name": "Jumbo Mixed Shawarma", "price": 4000, "category": "Shawarma",
     "description": "Loaded with chicken, beef & sausage"},
    {"name": "Chicken Sandwich", "price": 2000, "category": "Shawarma",
     "description": "Toasted bread with shredded chicken"},

    # Burgers
    {"name": "Classic Beef Burger", "price": 3000, "category": "Burgers",
     "description": "Beef patty, lettuce, tomato, sauce"},
    {"name": "Chicken Burger", "price": 3500, "category": "Burgers",
     "description": "Crispy chicken fillet burger"},

    # Chicken
    {"name": "Fried Chicken (4pcs)", "price": 3800, "category": "Chicken",
     "description": "Crispy fried chicken"},
    {"name": "Peppered Chicken", "price": 3000, "category": "Chicken",
     "description": "Spicy peppered chicken"},
    {"name": "Grilled Chicken", "price": 3500, "category": "Chicken",
     "description": "Char-grilled chicken"},
    {"name": "Gizzard", "price": 2500, "category": "Chicken",
     "description": "Peppered gizzard"},

    # Snacks
    {"name": "Meat Pie", "price": 800, "category": "Snacks",
     "description": "Flaky pastry with minced meat"},
    {"name": "Chicken Pie", "price": 900, "category": "Snacks",
     "description": "Pastry filled with chicken"},
    {"name": "Sausage Roll", "price": 600, "category": "Snacks",
     "description": "Savory sausage in pastry"},
    {"name": "Doughnut", "price": 500, "category": "Snacks",
     "description": "Sweet fried dough"},
    {"name": "Scotch Egg", "price": 700, "category": "Snacks",
     "description": "Boiled egg wrapped in sausage meat"},

    # Sides
    {"name": "Fries", "price": 1500, "category": "Sides",
     "description": "Golden crispy fries"},
    {"name": "Coleslaw", "price": 1000, "category": "Sides",
     "description": "Creamy cabbage salad"},

    # Drinks
    {"name": "Coke (50cl)", "price": 500, "category": "Drinks",
     "description": "Chilled Coca-Cola"},
    {"name": "Chapman", "price": 1200, "category": "Drinks",
     "description": "Refreshing Nigerian Chapman"},
    {"name": "Bottled Water", "price": 300, "category": "Drinks",
     "description": "75cl table water"},
]

with app.app_context():
    db.create_all()
    ensure_schema_compatibility()

    if not Admin.query.first():
        admin_username = os.environ.get("JENNY_ADMIN_USERNAME", "").strip()
        admin_password = os.environ.get("JENNY_ADMIN_PASSWORD", "")
        if admin_username and len(admin_password) >= 12:
            db.session.add(Admin(username=admin_username,
                                 password_hash=generate_password_hash(admin_password)))
            print("Admin account created from environment configuration.")
        else:
            print("WARNING: No admin created. Set JENNY_ADMIN_USERNAME and JENNY_ADMIN_PASSWORD (12+ characters), then rerun seed.py.")

    existing = {i.name for i in MenuItem.query.all()}
    added = 0
    for m in menu:
        if m["name"] in existing:
            continue
        db.session.add(MenuItem(
            name=m["name"], description=m["description"],
            price=m["price"], category=m["category"],
            image="default.jpg"   # admin will replace with real photo
        ))
        added += 1

    db.session.commit()
    print(f"✅ Seed done. Added {added} new items (total {MenuItem.query.count()}).")