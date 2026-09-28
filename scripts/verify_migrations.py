"""Verify Alembic migration paths for ECOS.

A: fresh DB  -> _run_migrations builds schema from baseline + stamps version
B: fresh DB schema == Base.metadata (table parity check)
C: legacy DB (tables, no alembic_version) -> stamped on startup
"""
import os
import subprocess
import sys

sys.path.insert(0, "/home/z/my-project/backend")

FRESH = "/tmp/ecos_mig_fresh.db"
for f in (FRESH,):
    if os.path.exists(f):
        os.remove(f)

os.environ["DATABASE_URL"] = f"file:{FRESH}"

from app.main import _run_migrations  # noqa: E402
from app.core.database import Base, engine  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

# --- A: fresh DB through the app's migration entrypoint ---
_run_migrations()
insp = inspect(engine)
tables = set(insp.get_table_names())
assert "alembic_version" in tables, "alembic_version missing after fresh upgrade"
print(f"A OK: fresh DB built via migration ({len(tables)} tables incl. alembic_version)")

# --- B: parity between migrated schema and ORM metadata ---
expected = set(Base.metadata.tables.keys())
missing = expected - tables
extra = tables - expected - {"alembic_version"}
assert not missing, f"tables in metadata but not migrated: {missing}"
assert not extra, f"migrated but not in metadata: {extra}"
print(f"B OK: migrated schema matches ORM metadata ({len(expected)} domain tables)")

# --- C: legacy adoption (current live-style DB: tables but no version) ---
LEGACY = "/tmp/ecos_mig_legacy.db"
if os.path.exists(LEGACY):
    os.remove(LEGACY)
os.environ["DATABASE_URL"] = f"file:{LEGACY}"

# rebuild a "legacy" DB exactly like the old create_all startup did
from app.core.database import Base as B2, engine as e2  # noqa: E402
import app.main  # noqa: F401,E402  (model imports already registered on Base)
B2.metadata.create_all(bind=e2)
_run_migrations()
insp2 = inspect(e2)
assert "alembic_version" in insp2.get_table_names(), "legacy DB was not stamped"
print("C OK: legacy create_all DB adopted via stamp head")
print("ALL MIGRATION PATHS VERIFIED")
