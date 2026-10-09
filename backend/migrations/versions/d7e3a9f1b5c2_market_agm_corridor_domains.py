"""market + agm corridor domains (§8-11 Marketstore/sourcing, §20-24 AGM)

Revision ID: d7e3a9f1b5c2
Revises: a3f9d2c6e4b1
Create Date: 2026-10-09

New participant surfaces of the corridor:
  suppliers.org_id        — portal tenancy link (supplier org <-> Supplier row)
  supplier_products       — supplier uploads with Luxeen review gate
  sourcing_orders         — operator prepaid marketstore purchases
  sourcing_events         — §23 tracking ladder for inbound corridor freight
  agent_profiles          — agent directory cards
  agent_links             — vendor <-> agent relationships
  agent_warehouses        — agent-run physical locations
  agent_stock_items       — per (warehouse, vendor, product) inventory
  agent_stock_movements   — signed AGM stock ledger
  agent_orders            — fulfillment alerts (call -> ship -> COD)
  agent_remittances(_lines) — §24 agent COD custody registers
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d7e3a9f1b5c2"
down_revision: Union[str, None] = "a3f9d2c6e4b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("suppliers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_suppliers_org_id"), ["org_id"], unique=False)

    op.create_table(
        "supplier_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=4096), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=False),
        sa.Column("cost_price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("moq", sa.Integer(), nullable=False),
        sa.Column("images", sa.JSON(), nullable=True),
        sa.Column("specs", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_notes", sa.String(length=1024), nullable=False),
        sa.Column("catalog_product_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("supplier_products", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_supplier_products_supplier_id"), ["supplier_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_supplier_products_org_id"), ["org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_supplier_products_title"), ["title"], unique=False)
        batch_op.create_index(batch_op.f("ix_supplier_products_category"), ["category"], unique=False)
        batch_op.create_index(batch_op.f("ix_supplier_products_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_supplier_products_catalog_product_id"), ["catalog_product_id"], unique=False)

    op.create_table(
        "sourcing_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(length=30), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("supplier_product_id", sa.Integer(), nullable=False),
        sa.Column("catalog_product_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("unit_cost_cny", sa.Float(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("cny_total", sa.Float(), nullable=False),
        sa.Column("fx_rate", sa.Float(), nullable=False),
        sa.Column("local_currency", sa.String(length=3), nullable=False),
        sa.Column("local_total", sa.Float(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("payment_reference", sa.String(length=100), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_org_id", sa.Integer(), nullable=True),
        sa.Column("dest_name", sa.String(length=255), nullable=False),
        sa.Column("dest_phone", sa.String(length=50), nullable=False),
        sa.Column("dest_address", sa.String(length=1024), nullable=False),
        sa.Column("dest_city", sa.String(length=100), nullable=False),
        sa.Column("dest_country", sa.String(length=2), nullable=False),
        sa.Column("supplier_note", sa.String(length=1024), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number"),
    )
    with op.batch_alter_table("sourcing_orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sourcing_orders_org_id"), ["org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_sourcing_orders_supplier_id"), ["supplier_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_sourcing_orders_supplier_product_id"), ["supplier_product_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_sourcing_orders_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_sourcing_orders_status"), ["status"], unique=False)

    op.create_table(
        "sourcing_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sourcing_order_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sourcing_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sourcing_events_sourcing_order_id"), ["sourcing_order_id"], unique=False)

    op.create_table(
        "agent_profiles",
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("whatsapp", sa.String(length=50), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("address", sa.String(length=1024), nullable=False),
        sa.Column("capacity_note", sa.String(length=500), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("org_id"),
    )
    with op.batch_alter_table("agent_profiles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_profiles_status"), ["status"], unique=False)

    op.create_table(
        "agent_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_org_id", sa.Integer(), nullable=False),
        sa.Column("vendor_org_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_org_id", "vendor_org_id", name="uq_agent_link_pair"),
    )
    with op.batch_alter_table("agent_links", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_links_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_links_vendor_org_id"), ["vendor_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_links_status"), ["status"], unique=False)

    op.create_table(
        "agent_warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_org_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("address", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_default", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    with op.batch_alter_table("agent_warehouses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_warehouses_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_warehouses_status"), ["status"], unique=False)

    op.create_table(
        "agent_stock_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_org_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("vendor_org_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("on_hand", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "vendor_org_id", "product_id", name="uq_agent_stock_wh_vendor_product"),
    )
    with op.batch_alter_table("agent_stock_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_stock_items_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_items_warehouse_id"), ["warehouse_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_items_vendor_org_id"), ["vendor_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_items_product_id"), ["product_id"], unique=False)

    op.create_table(
        "agent_stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_org_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("vendor_org_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(length=50), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=1024), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_stock_movements", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_stock_movements_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_movements_warehouse_id"), ["warehouse_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_movements_vendor_org_id"), ["vendor_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_movements_product_id"), ["product_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_stock_movements_movement_type"), ["movement_type"], unique=False)

    op.create_table(
        "agent_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("agent_org_id", sa.Integer(), nullable=False),
        sa.Column("vendor_org_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_phone", sa.String(length=50), nullable=False),
        sa.Column("customer_address", sa.String(length=1024), nullable=False),
        sa.Column("customer_city", sa.String(length=100), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("cod_expected", sa.Float(), nullable=False),
        sa.Column("cod_collected", sa.Float(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remittance_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=1024), nullable=False),
        sa.Column("failed_reason", sa.String(length=500), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    with op.batch_alter_table("agent_orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_orders_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_orders_vendor_org_id"), ["vendor_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_orders_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_orders_product_id"), ["product_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_orders_remittance_id"), ["remittance_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_orders_status"), ["status"], unique=False)
        batch_op.create_index("ix_agent_orders_queue", ["agent_org_id", "status"], unique=False)

    op.create_table(
        "agent_remittances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("register_code", sa.String(length=30), nullable=False),
        sa.Column("agent_org_id", sa.Integer(), nullable=False),
        sa.Column("vendor_org_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expected_amount", sa.Float(), nullable=False),
        sa.Column("remitted_amount", sa.Float(), nullable=False),
        sa.Column("counted_amount", sa.Float(), nullable=False),
        sa.Column("variance_amount", sa.Float(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("note", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("remitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("register_code"),
    )
    with op.batch_alter_table("agent_remittances", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_remittances_agent_org_id"), ["agent_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_remittances_vendor_org_id"), ["vendor_org_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_remittances_status"), ["status"], unique=False)

    op.create_table(
        "agent_remittance_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("remittance_id", sa.Integer(), nullable=False),
        sa.Column("agent_order_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("vendor_org_id", sa.Integer(), nullable=False),
        sa.Column("expected_amount", sa.Float(), nullable=False),
        sa.Column("counted_amount", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_remittance_lines", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_remittance_lines_remittance_id"), ["remittance_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_remittance_lines_agent_order_id"), ["agent_order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_remittance_lines_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_remittance_lines_vendor_org_id"), ["vendor_org_id"], unique=False)


def downgrade() -> None:
    op.drop_table("agent_remittance_lines")
    op.drop_table("agent_remittances")
    with op.batch_alter_table("agent_orders", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_orders_queue")
    op.drop_table("agent_orders")
    op.drop_table("agent_stock_movements")
    op.drop_table("agent_stock_items")
    op.drop_table("agent_warehouses")
    op.drop_table("agent_links")
    with op.batch_alter_table("agent_profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_profiles_status"))
    op.drop_table("agent_profiles")
    op.drop_table("sourcing_events")
    op.drop_table("sourcing_orders")
    op.drop_table("supplier_products")
    with op.batch_alter_table("suppliers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_suppliers_org_id"))
        batch_op.drop_column("org_id")
