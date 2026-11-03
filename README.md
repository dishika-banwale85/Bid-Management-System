# BidEase · Phase 4

Phase 3 adds Financial Documents, Power of Attorney, Declaration / Undertaking, HR Documents, deadline reminders, dashboard filters and PDF / Excel reports to the Phase 1 and 2 bid compliance app.

Phase 4 adds Compliance Admin screens for versioned workflow templates, request form presentation, contacts and user management. Workflow edits create a new version so existing requests retain their original approval history. Form labels, sections, dropdown choices and required attachment categories are editable; the backend keeps the validated field keys and rules fixed. The current Phase 4 update adds request-level role enforcement, request detail actions and document tracking, and role-focused queues/history pages.

## Project structure

```
BidEase/
  backend/
    app/
      api/             auth, bids, requests, approvals, contacts, notifications, admin
      core/            configuration and JWT/RBAC security
    models/           SQLAlchemy models, workflow versions and form templates
      schemas/          Pydantic v2 request and validation schemas
      services/         workflow engine and email sender
      templates/        Jinja2 email template
    alembic/            database migrations
    tests/              pytest workflow, validation and email tests
    seed.py             demo roles/users/workflows/CC contacts
  frontend/
    src/api/            Axios client and API types
    src/schemas/        matching Zod validation
    src/App.tsx         React Router pages and workflow UI
  docker-compose.yml    PostgreSQL, FastAPI, frontend, MailHog
```

## Run the demo with Docker

Requirements: Docker Desktop with Compose support. From this folder:

```sh
Copy-Item .env.example .env
docker compose up --build
```

Open:

- BidEase: http://localhost:5173
- FastAPI docs: http://localhost:8000/docs
- MailHog inbox: http://localhost:8025

Compose runs `alembic upgrade head` and seeds demo users and workflows before starting the API. The migration carries forward the Phase 1 role names, request status values, user active flag, creators and audit actor IDs. Postgres data and uploaded files are kept in named volumes.

## Tender Fee checklist autofill

Tender Fee and EMD by Challan requests require a Generated Challan and a Checklist. EMD by Bank Guarantee requires a BG Format and a Checklist. Upload the Checklist before filling Tender Fee or EMD by Challan fields; BidEase reads labeled values from DOCX, PDF, JPG or PNG files and fills matching fields for review. Scanned PDFs and images use Tesseract OCR, which is installed in the backend Docker image. For a native Windows backend, install Tesseract OCR and make `tesseract.exe` available on `PATH`, or set `TESSERACT_CMD` to its full path. If the file cannot be read or labels are not recognized, the upload still succeeds and the fields can be entered manually.

## Demo logins

All accounts use password `Demo123!`.

| Role | Email |
|---|---|
| Bid team | member@bidease.com |
| Engagement Partner / Approver | approver@bidease.com |
| Finance | finance@bidease.com |
| Operations | operations@bidease.com |
| Admin | admin@bidease.com |
| HR | hr@bidease.com |
| Risk | risk@bidease.com |

Create a bid from **Bids → New bid**. Then create an **EMD by Bank Guarantee** request, upload the RFP, and submit it. Sign in as Approver and approve the request. Sign in as Bid Team and enter the OPRS reference. Sign in as Operations, upload the issued BG copy, and enter the BG number and issue date to complete. Check MailHog for notification emails and the request detail page for workflow history.

To test rejection and resubmission, return an approval with a comment. The creator can edit the rejected request, and the next submission starts a new workflow attempt while preserving the old attempt's steps and comments.

## Phase 3 workflows and reports

The Phase 3 migration adds refund tracking and the `reminders_sent` deduplication table. The seed script adds HR and Risk roles, four workflow templates, and their configured contacts without removing existing demo records. Run the seed repeatedly safely.

New request types are **Financial Documents** (creator records the external Help Desk SR, then Finance uploads the documents), **Power of Attorney** (Approver then Risk), **Declaration / Undertaking** (one of the designated contacts signs and uploads), and **HR Documents** (HR uploads the certificate). Action assignees can use the **My actions** queue. EMD Challan owners can record a received refund from the request page.

The reminders scheduler runs daily at 09:00 Asia/Kolkata. To run a reminder scan immediately from PowerShell, sign in as Admin and send the token:

```powershell
$admin = Invoke-RestMethod -Method Post -Uri http://localhost:8000/auth/login -ContentType 'application/json' -Body (@{email='admin@bidease.com';password='Demo123!'} | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/reminders/run -Headers @{Authorization="Bearer $($admin.access_token)"}
```

Reports are available from the dashboard and bid page; refund exports are at `GET /reports/refunds.xlsx`.

## Phase 4 administration

Sign in as `admin@bidease.com` and open **Administration** from the left navigation. The screen has three tabs:

- **Workflows**: change step names, order, approval/action kind, assigned role, required action fields and active status. Publishing creates a new version for future submissions while preserving earlier definitions used by existing requests.
- **Form templates**: change the display name, field labels and sections, allowed values for supported dropdowns, and required attachment categories. Field keys and backend validation rules stay fixed so submitted requests remain valid.
- **Contacts**: add, edit and deactivate primary, CC and escalation contacts for a request type, or general Compliance contacts.

The Phase 4 Alembic migrations add workflow versioning, the form template table, and explicit document types. After updating an existing local checkout, run these commands from PowerShell in the project root:

```powershell
Set-Location .\backend
..\venv\Scripts\python.exe -m alembic upgrade head
..\venv\Scripts\python.exe seed.py
Set-Location ..\frontend
npm install
```

Then restart the backend and frontend, or rebuild Compose with `docker compose up --build`. API routes enforce the Admin role for administration and read-only access to compliance requests.

### Phase 4 permissions and request details

- Bid Team members can create and edit their own draft/rejected requests, upload the required files, submit, and record their OPRS reference or EMD refund receipt when applicable.
- Approvers, Risk and Finance can act only on approval steps assigned to their role. HR, Finance and Operations can complete only their configured action steps and upload that step's required file.
- Administrators can view requests and workflow history but cannot create, edit, upload to, submit, approve, reject, complete or update refund status on a compliance request. Admin user, workflow, form and contact settings remain editable through Administration.
- Request lists, queues, bid counts, dashboard data and reports are scoped to requests a user created, is assigned to, or has acted on. Account numbers are masked in non-admin views and exports.
- The request page shows the active workflow step, allowed actions, required document state, versioned downloads, rejection comments and workflow history. Upload metadata includes `document_type` for each file.

The latest database migration is `20261026_0004`. Local startup and tests from PowerShell:

```powershell
Set-Location .\backend
python -m alembic upgrade head
python seed.py
python -m pytest -q
```

Compose runs the migration and seed automatically when starting the backend. To rebuild and run the whole app from the project root, use `docker compose up --build`; open `http://localhost:5173` and sign in with one of the demo accounts above. Manual permission checks: create and submit a request as Bid Team; approve as the assigned role; try the same approval as Finance or Operations; then sign in as Admin and verify the request is view-only while Administration remains available.

Manual walkthrough: create a bid and an appropriate request, upload the required RFP or RFP format, then submit. For Financial Documents, complete the Help Desk action with an SR number, sign in as Finance, upload the prepared documents, and complete. For Power of Attorney, approve as Engagement Partner and Risk. For Declaration, upload a signed declaration from the action step. For HR Documents, sign in as HR, upload the certificate, and complete. For reminder testing, create an EMD Challan with an expected refund date 3, 1, or 0 days away (or 3 days overdue), then trigger the Admin endpoint twice and confirm the unique reminder is created once in Notifications and Email Logs. Mark the refund received to stop future overdue alerts.

### Windows PowerShell: Phase 3 database and frontend updates

Run from the project root after activating the virtual environment:

```powershell
Set-Location .\backend
python -m pip install -r requirements.txt
python -m alembic upgrade head
python seed.py
Set-Location ..\frontend
npm install
```

Restart the API and Vite dev server after the dependency update. If you use Docker Compose, rebuild with `docker compose up --build` so the new Python and frontend dependencies are included.

## Run services without Docker

Requirements: Python 3.11+, Node.js 20+, PostgreSQL 15+. Copy `.env.example` to `.env`, then set `DATABASE_URL` to a PostgreSQL URL reachable from your machine. Start PostgreSQL and MailHog separately (SMTP 1025, web UI 8025).

Backend, from `backend/`:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

Frontend, from `frontend/`:

```sh
npm install
npm run dev
```

Set `VITE_API_URL` if the API is not at `http://localhost:8000`.

### Windows PowerShell: API with Docker Postgres and MailHog

Run these commands from the `BidEase` project root. This is the recommended local setup when the frontend is already running in another terminal:

```powershell
Copy-Item .env.example .env   # only if .env does not already exist
docker compose up -d db mailhog
```

Then continue in the same terminal:

```powershell
cd backend
..\venv\Scripts\Activate.ps1   # if you created venv at the project root
python -m pip install -r requirements.txt
python -m alembic upgrade head
python seed.py
python -m uvicorn app.main:app --reload --port 8000
```

If you created the virtual environment inside `backend` instead, activate it with `.venv\Scripts\Activate.ps1`. Keep this terminal running. The API is at `http://localhost:8000`; the frontend at `http://localhost:5173` calls it directly. To run the entire stack in Docker instead, return to the project root and run `docker compose up --build`.

## Tests

```sh
cd backend
python -m pytest -q
```

The tests cover workflow advancement, API role checks, role-based visibility, admin read-only behavior, creator self-approval prevention, rejection/resubmission history, validation, required attachments, reports and email log creation. They use an isolated SQLite database; the application itself uses PostgreSQL by default.

## Workflows and API

The seed script installs these ordered templates:

- Tender Fee: Approver approval → Completed.
- EMD Challan: Engagement Partner approval → Finance approval → Completed.
- EMD BG: Approver approval → Bid Team records OPRS reference → Operations uploads the BG copy and records BG number and issue date → Completed.

Workflow steps live in `workflow_templates` and `workflow_steps`, not in route-specific state logic. A rejected attempt remains in `request_steps`; resubmission starts the next attempt number. Transitions are protected by role checks and run inside database savepoints/transactions.

Main routes:

- `POST /auth/login`, `GET /auth/me`
- `GET/POST /bids`, `GET/PUT /bids/{id}`, `GET /bids/check-rfp`
- `POST /requests`, `GET/PUT /requests/{id}`, `POST /requests/{id}/submit`
- `POST/GET /requests/{id}/documents`, `GET /requests/{id}/documents/{document_id}/download`
- `GET /requests/{id}/workflow`
- `POST /requests/{id}/steps/{step_id}/approve|reject|complete`
- `GET /approvals/pending`, `GET /operations/queue`
- `GET /notifications`, `POST /notifications/{id}/read`
- `GET/POST/PUT/DELETE /contacts`
- `GET /audit`, `GET /dashboard`

## Configuration and security

Replace `JWT_SECRET` and set a stable, randomly generated Fernet `FERNET_KEY` for any non-demo use. If `FERNET_KEY` is omitted, local development derives an encryption key from `JWT_SECRET`; changing that secret makes existing encrypted form data unreadable. Entire request `form_data` JSON, including account numbers, is encrypted at rest. API responses mask account numbers for users other than the request owner and Operations. The UI masks account numbers to the last four digits.

Uploads use random names in a private directory/volume, accept PDF/DOCX/JPG/PNG, and are limited to 10 MB by default. They are downloaded only through authenticated endpoints. CORS is limited to `FRONTEND_ORIGIN`. Configure production SMTP variables in `.env`; notification email failures are recorded in `email_logs` and do not fail the originating API response. Put the services behind HTTPS for deployment.

The original Phase 1 `prisma/schema.prisma` remains as a historical schema reference. This Phase 2 runtime follows the strict Python stack and uses SQLAlchemy 2.0 with Alembic migrations.

## Expanded bid details

The `20261027_0005` migration adds the nullable RFP publication, project title, pre-bid date and client address columns plus defaulted Not Applicable flags. New bid creation validates required fields and date order; older records continue to load and display “Not provided” for missing values. The legacy database/API field `rfp_reference` is retained and also returned as `rfp_number`.

From PowerShell, with the backend virtual environment active:

```powershell
Set-Location .\backend
python -m alembic upgrade head
python seed.py
python -m pytest -q
Set-Location ..\frontend
npm run test:schemas
npx tsc -b
```

Then start the backend with `python -m uvicorn app.main:app --reload --port 8000` from `backend`, and the frontend with `npm run dev` from `frontend`. The new demo bid is `DEMO-RFP-2027-001`.

Manual walkthrough: sign in as `member@bidease.com`, open **Bids → Create new bid**, fill the Client, RFP details and Key dates cards, and confirm the date timeline updates. Try a published date after submission, a submission date before today, an opening date before submission and a pre-bid date outside the published-to-submission range; each should show an inline error. Tick each Not applicable box and confirm its date input hides and the bid response stores `null`. Enter an existing RFP number, confirm the warning appears, then accept the duplicate confirmation to create it. Open a legacy bid to verify new missing fields show “Not provided”. Check role access by posting a bid as Approver (403) and as Admin (201).

## Step 3: prototype mail and named contacts

Mail is simulated by default. Each request action records a per-recipient row in `email_logs` and returns the notices used by the in-app mail status dialog. A contact without an email address is logged as `NOT_SENT_NO_EMAIL`; an address present in simulation mode is logged as `SIMULATED`. No email is sent unless `MAIL_MODE=smtp` is explicitly configured.

After applying the migration and seeding, the added role accounts are `senior.manager@bidease.com`, `sahil@bidease.com`, `aditi@bidease.com`, and `declaration.team@bidease.com`. They use the demo password `Demo123!`, like the existing demo accounts. The seeded named contacts intentionally have blank email addresses; Compliance Admin can add email, designation, and department later from **Contacts**.

Windows PowerShell, from the repository root:

```powershell
Set-Location .\backend
..\venv\Scripts\python.exe -m alembic upgrade head
..\venv\Scripts\python.exe seed.py
..\venv\Scripts\python.exe seed.py  # safe to repeat; preserves contact emails entered by Admin
..\venv\Scripts\python.exe -m pytest -q
Set-Location ..\frontend
npx tsc -b
npm run dev
```

For Docker, set `MAIL_MODE=simulate` in `.env` (or leave it unset), then from the repository root run `docker compose up --build`. The migration and seed commands above can run in another PowerShell after the backend container and Postgres are ready, using the local venv and a `.env` database URL pointing at `localhost:5432`.

Manual walkthrough:

1. Sign in as `member@bidease.com` / `Demo123!`, create an EMD Bank Guarantee request, upload its RFP, and submit. The modal should show Sambhavya Shanker with the missing-email notice, while the request moves to In Approval and its in-app notification is created.
2. Sign in as `admin@bidease.com`, open **Contacts**, filter Bank Guarantee, edit Sambhavya Shanker, and add a valid email address. Save the contact.
3. Create and submit another EMD Bank Guarantee request. The modal should show `Mail has been sent to Sambhavya Shanker` with simulated status. Check `email_logs` for `SIMULATED` and `NOT_SENT_NO_EMAIL` entries.
4. Sign in as `approver@bidease.com` / `Demo123!`, approve or reject the pending request. Each action returns mail notices and opens the same modal; verify the request status and workflow history changed and an in-app notification remains available.
5. Check role access: Admin can edit Contacts but has no request actions; the new Senior Manager and Declaration Team roles appear in user administration and can be assigned approval workflow steps. PACE Coordinator appears as an action assignee.
