from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env (DATABASE_URL etc.) regardless of cwd
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ROOT_ENV)

import traceback  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.core.database import Base, engine, SessionLocal  # noqa: E402
from app.core import subscribers  # noqa: E402

# Import all models so create_all sees every table
from app.core import models as core_models  # noqa: F401,E402
from app.identity import models as identity_models  # noqa: F401,E402
from app.supply import models as supply_models  # noqa: F401,E402
from app.catalog import models as catalog_models  # noqa: F401,E402
from app.storefront import models as storefront_models  # noqa: F401,E402
from app.crm import models as crm_models  # noqa: F401,E402
from app.orders import models as orders_models  # noqa: F401,E402
from app.logistics import models as logistics_models  # noqa: F401,E402
from app.payments import models as payments_models  # noqa: F401,E402
from app.finance import models as finance_models  # noqa: F401,E402
from app.landing_pages import models as landing_models  # noqa: F401,E402
from app.marketing import models as marketing_models  # noqa: F401,E402
from app.returns import models as returns_models  # noqa: F401,E402
from app.settlements import models as settlements_models  # noqa: F401,E402
from app.ai_harness import models as ai_models  # noqa: F401,E402
from app.notifications import models as notifications_models  # noqa: F401,E402
from app.procurement import models as procurement_models  # noqa: F401,E402
from app.warehouse import models as warehouse_models  # noqa: F401,E402
from app.automation import models as automation_models  # noqa: F401,E402
from app.cod import models as cod_models  # noqa: F401,E402
from app.market import models as market_models  # noqa: F401,E402
from app.agm import models as agm_models  # noqa: F401,E402

from app.core.seed import seed_if_empty  # noqa: E402
from app.core.deps import require_auth  # noqa: E402
from app.identity.router import router as identity_router  # noqa: E402
from app.identity.router import auth_router  # noqa: E402
from app.supply.router import router as supply_router  # noqa: E402
from app.catalog.router import router as catalog_router  # noqa: E402
from app.storefront.router import router as storefront_router  # noqa: E402
from app.storefront.public import public_router  # noqa: E402
from app.crm.router import router as crm_router  # noqa: E402
from app.crm.router import customers_router  # noqa: E402
from app.orders.router import router as orders_router  # noqa: E402
from app.logistics.router import router as logistics_router  # noqa: E402
from app.payments.router import router as payments_router  # noqa: E402
from app.finance.router import router as finance_router  # noqa: E402
from app.landing_pages.router import router as landing_pages_router  # noqa: E402
from app.marketing.router import router as marketing_router  # noqa: E402
from app.returns.router import router as returns_router  # noqa: E402
from app.settlements.router import router as settlements_router  # noqa: E402
from app.ai_harness.router import router as ai_router  # noqa: E402
from app.notifications.router import router as notifications_router  # noqa: E402
from app.procurement.router import router as procurement_router  # noqa: E402
from app.warehouse.router import router as warehouse_router  # noqa: E402
from app.analytics.router import router as analytics_router  # noqa: E402
from app.automation.router import router as automation_router  # noqa: E402
from app.cod.router import router as cod_router  # noqa: E402
from app.market.router import router as market_router  # noqa: E402
from app.market.router import portal as market_portal_router  # noqa: E402
from app.market.router import admin as market_admin_router  # noqa: E402
from app.agm.router import router as agm_router  # noqa: E402
from app.core.models import DomainEvent  # noqa: E402


def _run_migrations() -> None:
    """Bring the schema to head with Alembic (replaces wipe-and-reseed).

    - Fresh database            -> `upgrade head` builds the full schema.
    - Legacy create_all database -> `stamp head` adopts it (identical schema,
      produced from the same metadata) so future changes migrate normally.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if tables and "alembic_version" not in tables:
        print("[migrations] legacy schema detected -> stamping head")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    subscribers.register_all()
    _run_migrations()
    with SessionLocal() as db:
        seed_if_empty(db)

        # §46 first: the FX table must exist before anything prices the corridor
        from app.finance import fx as fx_service

        fx_service.seed_rates(db)
        db.commit()

        # Corridor depth (Marketstore + supplier portal + AGM): idempotent
        # second-stage seed that also upgrades existing deployments.
        from app.core import seed_market

        seed_market.seed_market_if_missing(db)
        db.commit()

        # §31-38: orgs that already adopted the harness gain newly built
        # operators automatically (no manual deploy per release)
        from app.ai_harness import service as ai_service

        created = ai_service.ensure_operators_deployed(db)
        if created:
            db.commit()
            print(f"[harness] deployed {len(created)} new operator(s): "
                  f"{[o.name for o in created]}")

    # §39 Phase 3 — background outbound worker: drains the notification
    # outbox (email / WhatsApp) every 30s, independent of request traffic.
    import asyncio

    from app.core.database import SessionLocal as _SL
    from app.notifications import outbound as _outbound

    async def _outbound_worker() -> None:
        while True:
            await asyncio.sleep(30)
            try:
                with _SL() as db:
                    result = _outbound.process_outbox(db, limit=25)
                    if result["processed"]:
                        db.commit()
                        print(f"[outbound worker] {result}")
            except Exception:  # noqa: BLE001 — the worker must survive anything
                print("[outbound worker] tick failed:\n" + traceback.format_exc())

    # §15 — landing page scheduler: publishes pages whose scheduled moment
    # has passed, snapshotting each as a new immutable version.
    from app.landing_pages import router as _lp_router

    async def _lp_scheduler() -> None:
        while True:
            await asyncio.sleep(60)
            try:
                with _SL() as db:
                    flipped = _lp_router.run_due_schedules(db)
                    if flipped:
                        print(f"[lp scheduler] auto-published pages: {flipped}")
            except Exception:  # noqa: BLE001 — the scheduler must survive anything
                print("[lp scheduler] tick failed:\n" + traceback.format_exc())

    # fire one immediate tick so overdue schedules land at boot as well
    try:
        with SessionLocal() as db:
            _lp_router.run_due_schedules(db)
    except Exception:  # noqa: BLE001
        print("[lp scheduler] boot tick failed:\n" + traceback.format_exc())

    task = asyncio.create_task(_outbound_worker())
    task2 = asyncio.create_task(_lp_scheduler())
    yield
    task.cancel()
    task2.cancel()


app = FastAPI(
    title="Ecos API",
    version="0.1.0",
    description=(
        "Ecos — Luxeen's global e-commerce operating system (plan §61). "
        "The operator runs the business. Ecos runs the infrastructure underneath it."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in [
    auth_router, identity_router, supply_router, catalog_router, storefront_router,
    public_router, crm_router, customers_router, orders_router, logistics_router,
    payments_router, finance_router, landing_pages_router, marketing_router,
    returns_router, settlements_router, ai_router, notifications_router,
    procurement_router, warehouse_router, analytics_router, automation_router,
    cod_router, market_router, market_portal_router, market_admin_router,
    agm_router,
]:
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "system": "ecos"}


@app.get("/api/events", tags=["events"], dependencies=[Depends(require_auth)])
def list_events(name: str | None = None, limit: int = 100):
    """Domain event audit trail (§40, §44)."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    with Session() as db:
        q = db.query(DomainEvent).order_by(DomainEvent.id.desc())
        if name:
            q = q.filter(DomainEvent.name == name)
        return [
            {"id": e.id, "name": e.name, "payload": e.payload, "created_at": e.created_at.isoformat()}
            for e in q.limit(min(limit, 500)).all()
        ]
