"""ai_provider_settings — §31 DeepSeek key flow (runtime-editable provider config)

Revision ID: a3f9d2c6e4b1
Revises: b8f2d1a4c7e9
Create Date: 2026-09-29

Singleton row (id=1) holding the harness brain configuration: the DeepSeek
API key (obfuscated at rest by app.core.secretbox), model + base URL
overrides, and the last provider-test outcome. Lets admins flip the harness
to live inference from the admin UI with no restart.
"""

from alembic import op
import sqlalchemy as sa

revision = 'a3f9d2c6e4b1'
down_revision = 'b8f2d1a4c7e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_provider_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider', sa.String(length=40), nullable=False, server_default='deepseek'),
        sa.Column('api_key_enc', sa.String(length=1024), nullable=False, server_default=''),
        sa.Column('model', sa.String(length=60), nullable=False, server_default=''),
        sa.Column('base_url', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_ok', sa.Integer(), nullable=True),
        sa.Column('last_test_latency_ms', sa.Integer(), nullable=True),
        sa.Column('last_test_error', sa.String(length=500), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_table('ai_provider_settings')
