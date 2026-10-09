"""Dropship fulfillment mode — supplier ships direct to customers, skipping AGM

Revision ID: c9e1f3a5b7d8
Revises: e2b7d9c4a1f6
Create Date: 2026-10-10

- sourcing_orders.fulfillment_mode   ('stock' default | 'dropship'):
  dropship orders run the direct-to-recipient ladder and never touch the
  AGM putaway / inventory pool — they end `delivered` at the recipient's door
- sourcing_orders.customer_order_id  (nullable FK-style link): when a
  storefront customer order is relayed to the supplier for dropship
  fulfillment, the traceability chain (§51) stays intact
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e1f3a5b7d8"
down_revision = "e2b7d9c4a1f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sourcing_orders") as batch:
        batch.add_column(sa.Column("fulfillment_mode", sa.String(length=20),
                                   server_default="stock", nullable=False))
        batch.add_column(sa.Column("customer_order_id", sa.Integer(), nullable=True))
        batch.create_index("ix_sourcing_orders_fulfillment_mode", ["fulfillment_mode"])
        batch.create_index("ix_sourcing_orders_customer_order_id", ["customer_order_id"])


def downgrade() -> None:
    with op.batch_alter_table("sourcing_orders") as batch:
        batch.drop_index("ix_sourcing_orders_customer_order_id")
        batch.drop_index("ix_sourcing_orders_fulfillment_mode")
        batch.drop_column("customer_order_id")
        batch.drop_column("fulfillment_mode")
