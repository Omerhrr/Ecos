from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 — ensure models are registered before create_all
from app.database import Base, engine
from app.routers import items

app = FastAPI(
    title="App API",
    version="0.1.0",
    description="FastAPI + SQLAlchemy backend (Nuxt frontend).",
)

# CORS — allow the Nuxt dev server origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(items.router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    # Dev-friendly: create tables on boot. Swap for Alembic migrations later.
    Base.metadata.create_all(bind=engine)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
