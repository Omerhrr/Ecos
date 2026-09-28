"""catalog depth (variants/videos), COD remittance register, LP versions + scheduling

Revision ID: b8f2d1a4c7e9
Revises: c41d7a9e3b10
Create Date: 2026-09-29 21:10:00.000000

Adds (Task 12):
- §10 catalog depth: products.videos + product_variants (SKU/cost-delta/stock)
- §10 order line variant snapshot: order_items.variant_id + variant_label
- §24 COD remittance register: cod_remittances + cod_remittance_lines
- §15 LP versioning + scheduling: landing_page_versions + landing_pages.scheduled_at/scheduled_by
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f2d1a4c7e9'
down_revision: Union[str, None] = 'c41d7a9e3b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- §10: product videos + variants -------------------------------
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('videos', sa.JSON(), nullable=True))

    op.create_table('product_variants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=60), nullable=False),
    sa.Column('option_name', sa.String(length=60), nullable=False),
    sa.Column('option_value', sa.String(length=120), nullable=False),
    sa.Column('cost_delta', sa.Float(), nullable=False),
    sa.Column('weight_delta_kg', sa.Float(), nullable=False),
    sa.Column('stock', sa.Integer(), nullable=False),
    sa.Column('image', sa.String(length=1024), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sku')
    )
    op.create_index(op.f('ix_product_variants_product_id'), 'product_variants', ['product_id'], unique=False)
    op.create_index(op.f('ix_product_variants_sku'), 'product_variants', ['sku'], unique=False)
    op.create_index(op.f('ix_product_variants_status'), 'product_variants', ['status'], unique=False)

    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('variant_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('variant_label', sa.String(length=200), nullable=True))
        batch_op.create_index(batch_op.f('ix_order_items_variant_id'), ['variant_id'], unique=False)

    # --- §24: COD remittance register ---------------------------------
    op.create_table('cod_remittances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('register_code', sa.String(length=30), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('carrier', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('expected_amount', sa.Float(), nullable=False),
    sa.Column('remitted_amount', sa.Float(), nullable=False),
    sa.Column('counted_amount', sa.Float(), nullable=False),
    sa.Column('variance_amount', sa.Float(), nullable=False),
    sa.Column('reference', sa.String(length=120), nullable=False),
    sa.Column('note', sa.String(length=1024), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('remitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reconciled_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('register_code')
    )
    op.create_index(op.f('ix_cod_remittances_carrier'), 'cod_remittances', ['carrier'], unique=False)
    op.create_index(op.f('ix_cod_remittances_org_id'), 'cod_remittances', ['org_id'], unique=False)
    op.create_index(op.f('ix_cod_remittances_status'), 'cod_remittances', ['status'], unique=False)

    op.create_table('cod_remittance_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('remittance_id', sa.Integer(), nullable=False),
    sa.Column('payment_id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('shipment_id', sa.Integer(), nullable=True),
    sa.Column('expected_amount', sa.Float(), nullable=False),
    sa.Column('counted_amount', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cod_remittance_lines_order_id'), 'cod_remittance_lines', ['order_id'], unique=False)
    op.create_index(op.f('ix_cod_remittance_lines_payment_id'), 'cod_remittance_lines', ['payment_id'], unique=False)
    op.create_index(op.f('ix_cod_remittance_lines_remittance_id'), 'cod_remittance_lines', ['remittance_id'], unique=False)

    # --- §15: LP versioning + scheduling ------------------------------
    op.create_table('landing_page_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('page_id', sa.Integer(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('blocks', sa.JSON(), nullable=False),
    sa.Column('theme', sa.JSON(), nullable=False),
    sa.Column('seo', sa.JSON(), nullable=False),
    sa.Column('published_by', sa.Integer(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('page_id', 'version_no', name='uq_lp_version_page_no')
    )
    op.create_index(op.f('ix_landing_page_versions_page_id'), 'landing_page_versions', ['page_id'], unique=False)

    with op.batch_alter_table('landing_pages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('scheduled_by', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('landing_pages', schema=None) as batch_op:
        batch_op.drop_column('scheduled_by')
        batch_op.drop_column('scheduled_at')

    op.drop_table('landing_page_versions')
    op.drop_table('cod_remittance_lines')
    op.drop_table('cod_remittances')

    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_order_items_variant_id'))
        batch_op.drop_column('variant_label')
        batch_op.drop_column('variant_id')

    op.drop_index(op.f('ix_product_variants_status'), table_name='product_variants')
    op.drop_index(op.f('ix_product_variants_sku'), table_name='product_variants')
    op.drop_index(op.f('ix_product_variants_product_id'), table_name='product_variants')
    op.drop_table('product_variants')

    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('videos')
