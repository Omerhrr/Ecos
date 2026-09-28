"""automation engine + fx rates + orders display currency

Revision ID: c41d7a9e3b10
Revises: eb9661601ad6
Create Date: 2026-09-29 09:40:00.000000

Adds (Task 11):
- §41 automation engine: automation_rules + automation_runs audit trail
- §46 multi-currency: fx_rates table (canonical directional rates)
- §46 orders: display_currency + fx_rate_used snapshot columns
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41d7a9e3b10'
down_revision: Union[str, None] = 'eb9661601ad6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('automation_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=1024), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('enabled', sa.Integer(), nullable=False),
    sa.Column('conditions', sa.JSON(), nullable=False),
    sa.Column('actions', sa.JSON(), nullable=False),
    sa.Column('cooldown_seconds', sa.Integer(), nullable=False),
    sa.Column('match_count', sa.Integer(), nullable=False),
    sa.Column('last_matched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('automation_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_automation_rules_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_rules_org_id'), ['org_id'], unique=False)

    op.create_table('automation_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rule_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('event_row_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('conditions_result', sa.JSON(), nullable=False),
    sa.Column('actions_executed', sa.JSON(), nullable=False),
    sa.Column('error', sa.String(length=1024), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('automation_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_automation_runs_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_runs_rule_id'), ['rule_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_runs_status'), ['status'], unique=False)

    op.create_table('fx_rates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('base', sa.String(length=3), nullable=False),
    sa.Column('quote', sa.String(length=3), nullable=False),
    sa.Column('rate', sa.Float(), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('base', 'quote', name='uq_fx_base_quote')
    )
    with op.batch_alter_table('fx_rates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fx_rates_base'), ['base'], unique=False)
        batch_op.create_index(batch_op.f('ix_fx_rates_quote'), ['quote'], unique=False)

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('display_currency', sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column('fx_rate_used', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('fx_rate_used')
        batch_op.drop_column('display_currency')

    with op.batch_alter_table('fx_rates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fx_rates_quote'))
        batch_op.drop_index(batch_op.f('ix_fx_rates_base'))
    op.drop_table('fx_rates')

    with op.batch_alter_table('automation_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_automation_runs_status'))
        batch_op.drop_index(batch_op.f('ix_automation_runs_rule_id'))
        batch_op.drop_index(batch_op.f('ix_automation_runs_event_type'))
    op.drop_table('automation_runs')

    with op.batch_alter_table('automation_rules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_automation_rules_org_id'))
        batch_op.drop_index(batch_op.f('ix_automation_rules_event_type'))
    op.drop_table('automation_rules')
