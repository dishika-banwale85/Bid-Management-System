# BidFlow — Bid Management & Compliance Workspace

React + Vite frontend and FastAPI/SQLAlchemy API for tender tracking, compliance evidence, reviews, audit history, and bid-readiness reporting.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer

## Run locally

1. Start the API:

   ```powershell
   cd backend
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   # Set JWT_SECRET to a unique random value in .env before using real data.
   uvicorn main:app --reload --port 8000
   ```

2. Start the frontend in a second terminal:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

   Open http://localhost:5173. Create the first administrator via `POST /api/auth/register` with JSON `{ "email", "name", "password" }` (password must be at least 12 characters). Initial registration closes as soon as the first account exists. Then sign in through the UI.

The API's interactive documentation is at http://localhost:8000/docs. Set `VITE_API_URL` in `frontend/.env.local` when the API is hosted elsewhere. Set `DATABASE_URL` for PostgreSQL, for example `postgresql+psycopg://user:password@localhost:5432/bidflow`, and install the appropriate PostgreSQL driver.

## Data and schema changes

Local development uses `backend/bid_management.db` (SQLite). The API creates missing tables on startup for a zero-setup local run. Alembic is included for deployment migration management; initialize it with `alembic init migrations`, configure `target_metadata = Base.metadata` in `migrations/env.py`, then generate and review migrations with `alembic revision --autogenerate -m "describe schema change"` and apply using `alembic upgrade head`. Take a database backup before applying production migrations. For SQLite, stop the API and copy the database file; for PostgreSQL, use `pg_dump` and store the backup outside the application directory.

## Security and operations

- Keep `.env` out of source control. Use a long, random `JWT_SECRET`; the built-in fallback is only for local development.
- Uploads are stored under `UPLOAD_DIR`, are limited by `MAX_UPLOAD_MB`, and accept PDF, Office documents, and common image formats. Use private storage with filesystem permissions restricted to the API account. Back up uploads together with the database.
- Set `CORS_ORIGINS` to the exact frontend origin(s) in deployment.
- SMTP variables are provided for future reminder delivery configuration. This application does not claim to send email or submit external OPRS / IN Help Desk requests. Those remain tracked workflows until an authorized integration is implemented and confirms delivery.
- Contact records are editable by administrators through `/api/admin/compliance-contacts`; seed them with the PDF-approved routing details after confirming those details. The PDF was not accessible in the development environment, so no contact information has been invented.

## Current workflow

Creating a tender generates the compliance checklist and owner tasks. Evidence uploads remain `Pending review`; they do not approve requirements. Review submission and reviewer decisions are separate, and the readiness endpoint and CSV export list outstanding approvals, required fields, attachments, expired evidence, owners, and due dates. User roles are checked by the API. First-account registration is restricted to an empty user database.

## API overview

- `POST /api/auth/register`, `POST /api/auth/token`, `GET /api/auth/me`
- `GET|POST /api/tenders`, `GET|PATCH|DELETE /api/tenders/{id}`
- `GET /api/dashboard`, `GET /api/tenders/{id}/compliance`, `PATCH /api/compliance/{id}`
- `POST /api/tenders/{id}/tasks`, `POST /api/compliance/{id}/submit-review`, `POST /api/compliance/{id}/approval`
- `POST /api/tenders/{id}/documents`, `GET /api/documents/{id}/download`
- `GET /api/tenders/{id}/readiness`, `GET /api/reports/readiness.csv`
