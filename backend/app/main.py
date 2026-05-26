from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, agents, wallet, payments, deposit, admin
from app.models import webhook_event  # noqa: F401 — registers table with SQLAlchemy metadata
from app.workers.celery_app import celery_app  # noqa: F401

app = FastAPI(
    title="Agent Revenue Sharing Platform",
    description="Multi-tier AI agent revenue sharing with ProActive, Proportion, and Speculation systems",
    version="1.0.0",
)
#uvicorn app.main:app --reload
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict to your frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(wallet.router)
app.include_router(payments.router)
app.include_router(deposit.router)
app.include_router(admin.router)
