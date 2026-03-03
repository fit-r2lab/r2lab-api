from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from .database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist (dev convenience; prod uses alembic)
    SQLModel.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="R2Lab API",
        description="R2Lab testbed management — users, slices, leases",
        version="0.1.0",
        lifespan=lifespan,
    )

    from .routers import auth, users, slices, resources, leases, stats
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(slices.router)
    app.include_router(resources.router)
    app.include_router(leases.router)
    app.include_router(stats.router)

    return app


app = create_app()
