"""§44 audit logs + §57 waterfall profiles + §21 freight rate cards

Revision ID: e2b7d9c4a1f6
Revises: d7e3a9f1b5c2
Create Date: 2026-10-10

- audit_logs            (§44 — actor/action/object/before/after/source/auth)
- waterfall_profiles    (§57 — configurable settlement/economics rates)
- freight_rate_cards    (§21 — per-mode corridor freight pricing)
- sourcing_orders.rate_card_snapshot (§21 — freeze the card the quote priced)
"""
from alembic import op
import sqlalchemy as sa

revision = "e2b7d9c4a1f6"
down_revision = "d7e3a9f1b5c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_label", sa.String(length=255), server_default=""),
        sa.Column("actor_role", sa.String(length=30), server_default=""),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.String(length=60), server_default=""),
        sa.Column("before", sa.String(length=8192), nullable=True),
        sa.Column("after", sa.String(length=8192), nullable=True),
        sa.Column("changed", sa.String(length=4096), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="api"),
        sa.Column("method", sa.String(length=10), server_default=""),
        sa.Column("path", sa.String(length=255), server_default=""),
        sa.Column("ip", sa.String(length=64), server_default=""),
        sa.Column("auth_context", sa.String(length=255), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    with op.batch_alter_table("audit_logs") as batch:
        batch.create_index("ix_audit_logs_org_id", ["org_id"])
        batch.create_index("ix_audit_logs_actor_user_id", ["actor_user_id"])
        batch.create_index("ix_audit_logs_actor_role", ["actor_role"])
        batch.create_index("ix_audit_logs_action", ["action"])
        batch.create_index("ix_audit_logs_entity_type", ["entity_type"])
        batch.create_index("ix_audit_logs_entity_id", ["entity_id"])
        batch.create_index("ix_audit_logs_source", ["source"])

    op.create_table(
        "waterfall_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("corridor", sa.String(length=20), server_default=""),
        sa.Column("category", sa.String(length=60), server_default=""),
        sa.Column("payment_cost_pct", sa.Float(), nullable=True),
        sa.Column("luxeen_margin_pct", sa.Float(), nullable=True),
        sa.Column("operator_markup_pct", sa.Float(), nullable=True),
        sa.Column("logistics_per_kg_ngn", sa.Float(), nullable=True),
        sa.Column("tax_pct", sa.Float(), nullable=True),
        sa.Column("active", sa.Integer(), server_default="1"),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    with op.batch_alter_table("waterfall_profiles") as batch:
        batch.create_index("ix_waterfall_profiles_org_id", ["org_id"])

    op.create_table(
        "freight_rate_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=20), server_default="air"),
        sa.Column("origin_country", sa.String(length=2), server_default="CN"),
        sa.Column("dest_country", sa.String(length=2), server_default="NG"),
        sa.Column("base_fixed_ngn", sa.Float(), server_default="0"),
        sa.Column("per_kg_ngn", sa.Float(), nullable=False),
        sa.Column("fuel_surcharge_pct", sa.Float(), server_default="0"),
        sa.Column("customs_pct", sa.Float(), server_default="0"),
        sa.Column("min_charge_ngn", sa.Float(), server_default="0"),
        sa.Column("lead_time_days_min", sa.Integer(), server_default="7"),
        sa.Column("lead_time_days_max", sa.Integer(), server_default="14"),
        sa.Column("active", sa.Integer(), server_default="1"),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    with op.batch_alter_table("freight_rate_cards") as batch:
        batch.create_index("ix_freight_rate_cards_org_id", ["org_id"])
        batch.create_index("ix_freight_rate_cards_mode", ["mode"])

    with op.batch_alter_table("sourcing_orders") as batch:
        batch.add_column(sa.Column("rate_card_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sourcing_orders") as batch:
        batch.drop_column("rate_card_snapshot")
    op.drop_table("freight_rate_cards")
    op.drop_table("waterfall_profiles")
    op.drop_table("audit_logs")
