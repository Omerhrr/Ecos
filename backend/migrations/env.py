"""Alembic environment for ECOS (replaces wipe-and-reseed).

Wires alembic to the SAME database URL and metadata the app uses:
- DATABASE_URL via app.core.database (supports the platform `file:` scheme)
- Base.metadata with every domain model imported
- render_as_batch=True so future SQLite column changes migrate cleanly
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.database import Base, DATABASE_URL

# Import every domain model module so metadata is complete.
from app.core import models as core_models  # noqa: F401
from app.identity import models as identity_models  # noqa: F401
from app.supply import models as supply_models  # noqa: F401
from app.catalog import models as catalog_models  # noqa: F401
from app.storefront import models as storefront_models  # noqa: F401
from app.crm import models as crm_models  # noqa: F401
from app.orders import models as orders_models  # noqa: F401
from app.logistics import models as logistics_models  # noqa: F401
from app.payments import models as payments_models  # noqa: F401
from app.finance import models as finance_models  # noqa: F401
from app.landing_pages import models as landing_models  # noqa: F401
from app.marketing import models as marketing_models  # noqa: F401
from app.returns import models as returns_models  # noqa: F401
from app.settlements import models as settlements_models  # noqa: F401
from app.ai_harness import models as ai_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth for the URL (env var / .env / default dev.db).
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
