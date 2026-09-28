"""Seed the China -> Nigeria corridor with realistic demo data (Phase 1).

Seeding runs through the SAME service functions the API uses, so the
event log, order state machine, COD collection, and ledger waterfall all
behave exactly like production traffic. The dashboard therefore lights up
with a coherent, auditable story.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.core import security as sec
from app.core.pricing import FX_RATES, LOGISTICS_NGN_PER_KG
from app.crm import models as crm_m
from app.finance import models as fm
from app.identity import models as im
from app.landing_pages import blocks as lp_blocks
from app.landing_pages import models as lpm
from app.logistics import service as logistics_service
from app.orders import models as om
from app.orders import service as order_service
from app.payments import models as pm
from app.payments import service as payment_service
from app.storefront import models as stm
from app.supply import models as sm

DEMO_PASSWORD = "demo1234"

PRODUCTS = [
    # title, category, cost CNY, weight kg, stock, supplier idx
    ("Smart Fitness Watch Pro", "electronics", 95.0, 0.25, 120, 0),
    ("Wireless Earbuds X2", "electronics", 62.0, 0.18, 200, 0),
    ("Portable Neck Fan", "home-appliances", 38.0, 0.42, 150, 1),
    ("LED Rechargeable Lamp", "home-appliances", 55.0, 0.65, 90, 1),
    ("360° Rotating Phone Holder", "accessories", 12.5, 0.12, 500, 2),
    ("Hair Styling Brush Set", "beauty", 48.0, 0.55, 80, 2),
]

SUPPLIERS = [
    ("Shenzhen Huanxi Electronics", "Shenzhen", 4.7, 12),
    ("Guangzhou Yijia Appliances", "Guangzhou", 4.4, 15),
    ("Yiwu Mintra Accessories", "Yiwu", 4.1, 18),
]

CUSTOMERS = [
    ("Amaka Okafor", "+234 803 555 0101", "12 Adeola Odeku St", "Victoria Island", "Lagos"),
    ("Chinedu Balogun", "+234 806 555 0102", "8 Allen Ave", "Ikeja", "Lagos"),
    ("Fatima Yusuf", "+234 809 555 0103", "45 Ahmadu Bello Way", "Kano", "Kano"),
    ("Tunde Adeyemi", "+234 801 555 0104", "23ring Rd", "Ibadan", "Oyo"),
    ("Ngozi Eze", "+234 807 555 0105", "3 Wuse Zone 4", "Abuja", "FCT"),
]


def seed_if_empty(db: Session) -> bool:
    if db.query(im.Organization).count() > 0:
        return False

    # --- Organizations & users (§43) ---
    luxeen = im.Organization(name="Luxeen Network", type="luxeen", country="CN", currency="CNY")
    operator = im.Organization(name="Kara Commerce Ltd", type="operator", country="NG", currency="NGN")
    db.add_all([luxeen, operator])
    db.flush()

    owner = im.User(
        org_id=operator.id, name="Kara Owner", email="owner@kara.example", role="owner",
        password_hash=sec.hash_password(DEMO_PASSWORD),
    )
    db.add_all([
        im.User(org_id=luxeen.id, name="Luxeen Ops", email="ops@luxeen.example", role="luxeen_admin",
                password_hash=sec.hash_password(DEMO_PASSWORD)),
        owner,
        im.User(org_id=operator.id, name="Bisi Agent", email="bisi@kara.example", role="agent",
                password_hash=sec.hash_password(DEMO_PASSWORD)),
    ])
    db.flush()

    # --- Supply network (§8) ---
    suppliers = [
        sm.Supplier(name=n, city=c, status="verified", rating=r, lead_time_days=d)
        for (n, c, r, d) in SUPPLIERS
    ]
    db.add_all(suppliers)
    db.flush()

    # --- Catalog (§10) — supplier data normalized into Ecos products ---
    products = []
    for (title, cat, cost, weight, stock, sidx) in PRODUCTS:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        p = cm.Product(
            supplier_id=suppliers[sidx].id, title=title, category=cat,
            slug=slug,
            supplier_cost=cost, weight_kg=weight, stock=stock, status="active",
            description=(
                f"Imported {title.lower()} sourced via the China-Nigeria corridor. "
                "Quality-checked before shipping, delivered to your door, pay on delivery."
            ),
            specs={"warranty": "3 months", "origin": "CN"},
            images=[f"https://picsum.photos/seed/{slug}/800/600"],
        )
        products.append(p)
    db.add_all(products)
    db.flush()

    # --- Storefront (§13) ---
    store = stm.Store(org_id=operator.id, name="Kara NG Store", slug="kara-ng", country="NG", currency="NGN")
    db.add(store)
    db.flush()

    # --- Customers & leads (§17) ---
    customers = [
        crm_m.Customer(
            store_id=store.id, full_name=n, phone=p, address=a, city=c, state=s
        )
        for (n, p, a, c, s) in CUSTOMERS
    ]
    db.add_all(customers)
    db.flush()

    leads = [
        crm_m.Lead(store_id=store.id, product_id=products[0].id, contact_name=CUSTOMERS[0][0],
                   contact_phone=CUSTOMERS[0][1], status="new",
                   source="meta_ads", campaign="Q3-Lagos-Electronics", assigned_agent="Bisi Agent"),
        crm_m.Lead(store_id=store.id, product_id=products[1].id, contact_name=CUSTOMERS[1][0],
                   contact_phone=CUSTOMERS[1][1], status="contacted", source="meta_ads",
                   campaign="Q3-Lagos-Electronics", assigned_agent="Bisi Agent"),
        crm_m.Lead(store_id=store.id, product_id=products[2].id, contact_name=CUSTOMERS[2][0],
                   contact_phone=CUSTOMERS[2][1], status="interested", source="tiktok",
                   campaign="Neck-Fool-Summer", assigned_agent="Bisi Agent"),
        crm_m.Lead(store_id=store.id, product_id=products[4].id, contact_name=CUSTOMERS[3][0],
                   contact_phone=CUSTOMERS[3][1], status="unreachable", source="organic"),
        crm_m.Lead(store_id=store.id, product_id=products[5].id, contact_name=CUSTOMERS[4][0],
                   contact_phone=CUSTOMERS[4][1], status="new", source="whatsapp"),
    ]
    db.add_all(leads)
    db.flush()

    # --- Orders through real services: state machine + events fire naturally ---
    # Order 1: delivered, COD collected (full cascade incl. ledger)
    r = order_service.create_order(
        db, store_id=store.id, customer_id=customers[0].id,
        product_id=products[0].id, qty=1, payment_method="cod",
    )
    o1 = db.get(om.Order, r["id"])
    order_service.transition_order(db, o1, "confirmed")
    shipment1 = logistics_service.create_shipment_for_order(db, o1)
    for code, loc in [("picked_up", "Shenzhen, CN"), ("exported", "Shenzhen Port"),
                      ("in_transit", "Indian Ocean"), ("customs", "Apapa, Lagos"),
                      ("destination_hub", "Lagos Hub"), ("out_for_delivery", "VI Route 3"),
                      ("delivered", "Victoria Island")]:
        logistics_service.add_tracking_event(db, shipment1, code=code, location=loc)
    # delivered -> COD auto-captured by subscriber -> ledger written

    # Order 2: delivered, online payment captured manually (gateway callback simulation)
    r = order_service.create_order(
        db, store_id=store.id, customer_id=customers[1].id,
        product_id=products[1].id, qty=2, payment_method="online_transfer",
    )
    o2 = db.get(om.Order, r["id"])
    order_service.transition_order(db, o2, "confirmed")
    shipment2 = logistics_service.create_shipment_for_order(db, o2)
    for code, loc in [("picked_up", "Shenzhen, CN"), ("exported", "Shenzhen Port"),
                      ("in_transit", "Indian Ocean"), ("customs", "Apapa, Lagos"),
                      ("destination_hub", "Lagos Hub"), ("out_for_delivery", "Ikeja Route 1"),
                      ("delivered", "Allen Ave, Ikeja")]:
        logistics_service.add_tracking_event(db, shipment2, code=code, location=loc)
    payment2 = db.query(pm.Payment).filter(pm.Payment.order_id == o2.id).first()
    payment_service.capture_payment(db, payment2, reference="TRF-99821")

    # Order 3: in transit (customs stage)
    r = order_service.create_order(
        db, store_id=store.id, customer_id=customers[2].id,
        product_id=products[2].id, qty=1, payment_method="cod",
    )
    o3 = db.get(om.Order, r["id"])
    order_service.transition_order(db, o3, "confirmed")
    shipment3 = logistics_service.create_shipment_for_order(db, o3)
    for code, loc in [("picked_up", "Guangzhou, CN"), ("exported", "Guangzhou Port"),
                      ("in_transit", "Indian Ocean"), ("customs", "Apapa, Lagos")]:
        logistics_service.add_tracking_event(db, shipment3, code=code, location=loc)

    # Order 4: confirmed, awaiting fulfillment
    r = order_service.create_order(
        db, store_id=store.id, customer_id=customers[3].id,
        product_id=products[4].id, qty=3, payment_method="cod",
    )
    o4 = db.get(om.Order, r["id"])
    order_service.transition_order(db, o4, "confirmed")

    # Order 5: pending confirmation (fresh lead conversion)
    order_service.create_order(
        db, store_id=store.id, customer_id=customers[4].id,
        product_id=products[5].id, qty=1, payment_method="online_transfer",
    )

    # --- Landing page engine (§15) + storefront home (§14) ---
    home_blocks, _ = lp_blocks.sanitize_blocks([
        {"type": "hero",
         "headline": "Smart gadgets, delivered across Nigeria",
         "subheadline": "Quality-tested imports from our China network. Order in minutes — pay cash on delivery.",
         "cta_label": "Shop now", "cta_href": "/products",
         "image": "https://picsum.photos/seed/ecos-hero/1600/900"},
        {"type": "trust_badges",
         "items": "🚚 | Nationwide door-to-door delivery\n💵 | Pay on delivery — zero risk\n✅ | 7-day returns, no questions"},
        {"type": "product_showcase", "title": "Trending this week", "mode": "latest", "limit": "6"},
        {"type": "testimonials", "title": "Customers love Kara",
         "items": ("Amaka O. | My watch arrived in 9 days, exactly as described. Paid the rider on delivery.\n"
                   "Chinedu B. | The earbuds are surprisingly good for the price. Ordering again for my sister.\n"
                   "Fatima Y. | Agent called to confirm and delivery took 8 days to Kano. Very smooth.")},
        {"type": "faq", "title": "Questions, answered",
         "items": ("How long does delivery take? | Door-to-door in 7-14 days, tracked from China to your city.\n"
                   "Do I pay before delivery? | No — you pay cash or transfer when your order arrives.\n"
                   "What if it is faulty? | Message your agent within 7 days for a replacement or refund.")},
        {"type": "cta", "title": "Ready to order?",
         "body": "Pick a product and leave your number — an agent will call you to confirm today.",
         "cta_label": "Browse products", "cta_href": "/products"},
    ])
    launch_blocks, _ = lp_blocks.sanitize_blocks([
        {"type": "hero",
         "headline": "Smart Fitness Watch Pro — launch week",
         "subheadline": "Track workouts, sleep and notifications. Launch price this week only.",
         "cta_label": "Get yours", "cta_href": "/products/smart-fitness-watch-pro",
         "image": "https://picsum.photos/seed/ecos-watch/1600/900"},
        {"type": "image_text",
         "image": "https://picsum.photos/seed/ecos-lifestyle/900/700",
         "title": "Built for Lagos life", "image_side": "right",
         "body": "Bright display under the sun, week-long battery for NEPA realities, and calls on your wrist. Delivered anywhere in Nigeria — pay on arrival.",
         "cta_label": "Order now", "cta_href": "/products/smart-fitness-watch-pro"},
        {"type": "product_showcase", "title": "Also trending", "mode": "latest", "limit": "3"},
    ])
    now = datetime.now(timezone.utc)
    db.add_all([
        lpm.LandingPage(
            org_id=operator.id, slug="home", title="Kara NG — Storefront Home",
            status="published", blocks=home_blocks, theme={"primary": "#00b374"},
            seo={"title": "Kara NG — Smart gadgets, pay on delivery",
                 "description": "Shop smart gadgets imported via the China-Nigeria corridor. Nationwide delivery, pay on delivery."},
            created_by=owner.id, published_at=now,
        ),
        lpm.LandingPage(
            org_id=operator.id, slug="smartwatch-launch", title="Smartwatch Launch Campaign",
            status="draft", blocks=launch_blocks, theme={"primary": "#2563eb"},
            seo={"title": "Smart Fitness Watch Pro — Launch Week",
                 "description": "Track workouts, sleep and notifications. Launch price this week only."},
            created_by=owner.id,
        ),
    ])

    db.commit()
    print("[seed] China -> Nigeria corridor demo data created (auth, storefront, landing pages).")
    return True
