"""Main FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api.routes import router
from app.api.payment_routes import router as payment_router
from app.middleware.idempotency_middleware import IdempotencyMiddleware
from app.infrastructure.db import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    yield


app = FastAPI(
    title="Marketplace API",
    description="DDD-based marketplace API with idempotency support for lab work",
    version="2.0.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Idempotency middleware for payment endpoints
app.add_middleware(IdempotencyMiddleware, ttl_seconds=24 * 60 * 60)


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """Middleware для добавления сессии БД в request.state."""
    async with SessionLocal() as session:
        request.state.db = session
        try:
            response = await call_next(request)
            await session.commit()
            return response
        except Exception as e:
            await session.rollback()
            raise
        finally:
            await session.close()


# Include routes
app.include_router(router, prefix="/api")
app.include_router(payment_router)  # Payment routes для тестирования конкурентности


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "idempotency": "enabled"}
