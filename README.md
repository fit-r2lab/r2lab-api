# R2Lab API

REST API for the [R2Lab](https://r2lab.inria.fr) wireless testbed — manages users, slices, leases, and registrations.

Built with FastAPI + SQLModel + PostgreSQL.

## Development

```bash
git clone <repo-url>
cd r2lab-api
uv venv && uv sync
cp deploy/.env.example .env    # edit as needed (set R2LAB_MAIL_MODE=console for dev)
alembic upgrade head
uvicorn r2lab_api.app:app --reload
```

API docs at http://localhost:8000/docs

## Tests

```bash
pytest
```

Tests use an in-memory SQLite database — no PostgreSQL needed.

## Deployment

See [deploy/README.md](deploy/README.md).
