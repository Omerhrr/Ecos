"""Second-stage corridor seed — Marketstore + supplier portal + AGM (idempotent).

Runs on EVERY boot after `seed_if_empty` and upgrades existing deployments
in place: if no supplier organization exists yet, this provisions

  - a supplier org + portal user, linked to the first Supplier row
  - an agent org + AGM user + profile + default warehouse, linked to the
    demo operator (vendor <-> agent)
  - supplier listings in every review state (draft / submitted / published)
  - one fully-tracked demo sourcing run (buy -> pay -> CN ladder -> arrival
    -> agent putaway) so the Marketstore, Sourcing and AGM pages light up

All writes go through the SAME service functions the API uses, so events,
notifications, ledger entries and stock behave exactly like production.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agm import models as agm_m
from app.agm import service as agm_service
from app.catalog import models as cm
from app.core import security as sec
from app.identity import models as im
from app.market import models as market_m
from app.market import service as market_service
from app.notifications import service as notif_service
from app.storefront import models as stm
from app.supply import models as sm

DEMO_PASSWORD = "demo1234"


def seed_market_if_missing(db: Session) -> bool:
    if db.query(im.Organization).filter(im.Organization.type == "supplier").count() > 0:
        return False

    print("[seed] corridor depth missing -> provisioning supplier portal, "
          "Marketstore listings and the AGM")

    # --- Supplier org + portal user, linked to the first Supplier row -----
    supplier = (
        db.query(sm.Supplier).filter(sm.Supplier.org_id.is_(None)).order_by(sm.Supplier.id).first()
    )
    if supplier is None:
        supplier = db.query(sm.Supplier).order_by(sm.Supplier.id).first()
    if supplier is None:
        print("[seed] no suppliers yet — skipping market seed (run base seed first)")
        return False

    sup_org = im.Organization(name=f"{supplier.name} Co.", type="supplier", country=supplier.country, currency="CNY")
    db.add(sup_org)
    db.flush()
    sup_user = im.User(
        org_id=sup_org.id, name="Li Wei", email="supplier@shenzhen.example",
        role="supplier", phone="+86 138 5550 0101",
        password_hash=sec.hash_password(DEMO_PASSWORD),
    )
    db.add(sup_user)
    supplier.org_id = sup_org.id
    supplier.status = "verified"
    db.flush()
    notif_service.ensure_preferences(db, sup_user.id)

    # --- Agent org + AGM user + profile + default warehouse + vendor link -
    operator_org = db.query(im.Organization).filter(im.Organization.type == "operator").order_by(im.Organization.id).first()
    agent_org = im.Organization(name="Eko Fulfillment Services", type="agent", country="NG", currency="NGN")
    db.add(agent_org)
    db.flush()
    agent_user = im.User(
        org_id=agent_org.id, name="Kelechi Nwafor", email="agent@eko.example",
        role="agm", phone="+234 803 555 0777",
        password_hash=sec.hash_password(DEMO_PASSWORD),
    )
    db.add(agent_user)
    profile = agm_m.AgentProfile(
        org_id=agent_org.id, contact_name="Kelechi Nwafor",
        phone="+234 803 555 0777", whatsapp="+234 803 555 0777",
        city="Lagos", country="NG",
        address="14 Clement St, Ilasamaja, Lagos", capacity_note="2 warehouses, 400 pallet slots, COD riders",
        rating=4.6,
    )
    db.add(profile)
    db.flush()
    wh = agm_service.create_warehouse(
        db, agent_org_id=agent_org.id, name="Eko Hub — Ilasamaja",
        city="Lagos", country="NG", address="14 Clement St, Ilasamaja, Lagos", is_default=True,
    )
    db.add(agm_m.AgentWarehouse(
        agent_org_id=agent_org.id, code=f"AGW-{agent_org.id}-02",
        name="Eko Hub — Ikeja", city="Lagos", country="NG",
        address="22 Obafemi Awolowo Way, Ikeja", is_default=0,
    ))
    if operator_org is not None:
        agm_service.add_link(db, agent_org_id=agent_org.id, vendor_org_id=operator_org.id)
    db.flush()
    notif_service.ensure_preferences(db, agent_user.id)

    # --- Supplier listings in every review state ---------------------------
    listings_spec = [
        # title, category, industry, cost CNY, weight, moq, target status
        ("Mini Projector HD 1080p", "electronics", "consumer-electronics", 210.0, 1.4, 5, "published"),
        ("Solar Power Bank 20000mAh", "electronics", "consumer-electronics", 88.0, 0.55, 10, "published"),
        ("Electric Milk Frother Rechargeable", "home-appliances", "home-living", 26.5, 0.35, 20, "published"),
        ("Silk Satin Bonnet Set (3-pack)", "beauty", "beauty", 19.0, 0.22, 30, "submitted"),
        ("Stainless Kitchen Knife 6-piece", "home-appliances", "home-living", 64.0, 0.95, 5, "draft"),
    ]
    created: dict[str, market_m.SupplierProduct] = {}
    for (title, category, industry, cost, weight, moq, target) in listings_spec:
        sp = market_service.create_supplier_product(
            db, supplier_id=supplier.id, org_id=sup_org.id,
            title=title, category=category, industry=industry,
            cost_price=cost, currency="CNY", weight_kg=weight, moq=moq,
            description=(
                f"{title} sourced and quality-checked through the Ecos network. "
                "Ships from our origin hub with full corridor tracking."
            ),
            images=[f"https://picsum.photos/seed/{title.lower().replace(' ', '-')[:40]}/800/600"],
            specs={"warranty": "6 months", "origin": "CN"},
        )
        if target in ("submitted", "published"):
            market_service.submit_for_review(db, sp)
        if target == "published":
            market_service.review_product(db, sp, decision="approve", notes="Sample verified — listing quality good.")
            market_service.publish_product(db, sp)
        created[title] = sp
    db.flush()

    # --- One fully-tracked demo sourcing run (vendor -> agent destination) -
    if operator_org is not None:
        projector = created.get("Mini Projector HD 1080p")
        if projector is not None and projector.catalog_product_id is not None:
            so = market_service.create_sourcing_order(
                db, supplier_product_id=projector.id, org_id=operator_org.id,
                qty=8, agent_org_id=agent_org.id, created_by=None,
                note="Stock-up for Q4 campaign — deliver to the Eko hub.",
            )
            market_service.pay_sourcing_order(db, so, method="online_transfer")
            for code, loc, desc in [
                ("supplier_processing", "Shenzhen, CN", "Supplier accepted the order and is preparing it."),
                ("picked_up", "Shenzhen, CN", "Collected from the supplier warehouse."),
                ("origin_warehouse", "Shenzhen consolidation center", "Consolidated with corridor freight."),
                ("exported", "Shenzhen Port", "Export customs cleared."),
                ("in_transit", "Indian Ocean", "Vessel on route to Lagos."),
                ("customs", "Apapa, Lagos", "Import clearance in progress."),
                ("destination_hub", "Lagos Hub", "Received at the destination hub."),
                ("delivered", "Eko Hub — Ilasamaja", "Delivered to the agent warehouse."),
            ]:
                market_service.add_sourcing_event(db, so, code=code, location=loc, description=desc)
            market_service.receive_sourcing_order(db, so)

        # --- Mark one confirmed customer order for agent fulfillment --------
        store = db.query(stm.Store).filter(stm.Store.org_id == operator_org.id).order_by(stm.Store.id).first()
        if store is not None:
            from app.orders import models as om

            confirmed = (
                db.query(om.Order)
                .filter(om.Order.store_id == store.id, om.Order.status == "confirmed")
                .order_by(om.Order.id)
                .first()
            )
            if confirmed is not None:
                agm_service.mark_order_for_agent(
                    db, order=confirmed, agent_org_id=agent_org.id,
                    vendor_org_id=operator_org.id,
                )

    db.flush()
    print("[seed] corridor depth ready — supplier portal, Marketstore, AGM live.")
    return True
