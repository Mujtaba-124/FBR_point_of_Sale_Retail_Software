# CLAUDE.md — Cheena FBR POS Software

Project instructions for Claude Code. Read this before making any change.

## 1. Project Overview

Cheena FBR POS Software is a professional web application for **one company** that operates **multiple shops/branches** with **multiple users**.

- It is **NOT a multi-tenant SaaS**. Do not add tenant IDs, tenant isolation, per-tenant billing, or subdomain-per-customer logic.
- Core purpose: import sales invoices via Excel, manage users/permissions and shop records, approve sales data, synchronize approved invoices with the FBR POS integration, and generate reports.

> Source requirement document: `FBR_POS_Cheena Software.docx` (uses legacy wording such as "Tenant Admin" and "default company"; there are still no tenants).
>
> **Access categories (decided in Phase 2):** `super_admin` = internal software administration (future: subscription expiry/renewal, SMTP settings) and never accesses company business data; `company_admin` = the company's administrator (users, roles, shops, uploads, approvals, FBR sync, reports); `company_user` = company staff with permissions assigned later by the Company Admin. Super Admin and Company Workspace must stay strictly separated in the backend (`app/api/deps.py` guards) and in the frontend routes (`/super-admin`, `/company`).

## 2. Working Rules for Claude

- Do not start coding, create files, install dependencies, or initialize the database unless the user explicitly instructs it.
- Preserve all existing project files; never delete or overwrite without confirming.
- Implement one module at a time, following the build order in section 14.
- If a requirement is ambiguous, ask rather than guess (see Open Questions, section 15).
- Never commit secrets, FBR tokens, or `.env` files.

## 3. Technology Stack (approved — do not substitute)

| Layer | Technology |
|---|---|
| Frontend | Next.js, TypeScript, Tailwind CSS, shadcn/ui |
| Backend | Python, FastAPI |
| Database | PostgreSQL — database name `cheena_database` |
| ORM / Migrations | SQLAlchemy, Alembic |
| Background jobs | Celery + Redis |
| Excel processing | openpyxl |
| Deployment | Docker, Linux VPS |

## 4. Architecture

- Monorepo layout (proposed):
  ```
  /frontend      Next.js app
  /backend       FastAPI app (app/api, app/models, app/schemas, app/services, app/tasks, app/core)
  /docker        Dockerfiles, compose files, nginx config
  /docs          Requirements and decisions
  ```
- Backend layering: **router → service → repository/model**. Routers stay thin; business logic lives in services; no DB access in routers.
- Long-running work (Excel processing if large, FBR sync, emails) runs in **Celery workers**, never in request handlers.
  - **Approved exception (Email Settings, decided 2026-11-05):** the Super Admin's interactive SMTP diagnostics — *Test Connection* and *Send Test Email* — run inside the request so the admin sees the result immediately. They stay bounded: per-operation SMTP timeout (`SMTP_TIMEOUT_SECONDS`), one test at a time (Redis lock), per-admin rate limits, and an idempotency key so a retry never sends twice. This exception covers only these two diagnostics; every application email (reminders, sync-completion notices, password links) must go through Celery.
- Redis is the Celery broker/result backend (and optional cache). It is not a source of truth; PostgreSQL is.
- Frontend talks to the backend only through the REST API; types for API responses are defined in one place.
- Config via environment variables (12-factor); separate dev/staging/production settings.

## 5. Core Modules

1. **Authentication & Users** — login, password set/reset via email link, user creation limited to a configured maximum.
2. **Roles & Permissions** — each user has a role/rights defining accessible modules. Modules without rights are hidden in the menu **and** blocked by the API.
3. **Shop Setup** — per shop: Shop Name, POS ID, Branch Name, Code, FBR Token.
4. **Excel Template & Upload** — downloadable template; one file at a time; one file = one date.
5. **Sales View** — view uploaded records with totals; filter by date range and shop.
6. **Approval Workflow** — statuses: `Draft` → `Wait for Approval` → `Accept` (by Owner, confirmed with OK) or `Reject` (back for correction).
7. **FBR Sync** — user sets start/end time window; records pushed one by one; Stop / Cancel / Resume; retry of unsent records; email to admin on completion.
8. **Reports** — Sales List (FBR POS invoices) by date and shop; further reports added as requirements are approved.
9. **Audit Log** — who did what and when (uploads, approvals, sync actions, user/shop/token changes).

### Excel template columns (fixed order)
`Date, Time (24-hour), Customer Name, CNIC/NTN, Quantity, Rate, Amount, Sale Tax %, Sale Tax Amount, Net Amount`

Validation rules:
- Every row's date must match the file's single date; reject files mixing dates.
- Amount = Quantity × Rate; Sale Tax Amount = Amount × Sale Tax %; Net Amount = Amount + Sale Tax Amount (verify within rounding tolerance; report row-level errors with row numbers).
- Time must be valid 24-hour format. CNIC/NTN format validated.
- Duplicate-file protection (same shop + date already uploaded) must be explicit, not silent.
- Whether a bad row rejects the whole file or only that row is an open question — default to rejecting the file with a full error list until decided.

## 6. Approval Workflow Rules

- Allowed transitions: `Draft → Wait for Approval`, `Wait for Approval → Accept | Reject`, `Reject → Draft` (after correction/re-upload).
- Only a user with the Owner/approver right can Accept or Reject; enforce server-side.
- Only `Accept` files can be sent to FBR. Accepted data is **immutable** (no edit/delete of invoice rows once accepted; corrections go through a defined reversal process).
- Every transition is logged in the audit log with user and timestamp.

## 7. FBR Synchronization Reliability

This is the most critical module. Treat money/tax data conservatively.

- Each invoice record has its own sync state: `pending`, `sending`, `sent`, `failed`, with attempt count, last error, FBR invoice number/response, and timestamps.
- **Idempotency:** never send the same invoice twice. Persist state before and after each FBR call; use a unique reference per invoice; on ambiguous outcomes (timeout), reconcile before resending.
- A **sync run** (job) entity tracks: file, shop, window start/end, status (`scheduled`, `running`, `stopped`, `cancelled`, `completed`, `failed`), counters, and who triggered it.
- **Stop** pauses after the in-flight record finishes; **Resume** continues with remaining `pending`/`failed` records; **Cancel** ends the run and leaves unsent records unsent.
- Respect the user-defined start/end window; do not send outside it.
- Retry with bounded exponential backoff for transient errors (network, 5xx); do not auto-retry validation/4xx rejections — mark `failed` with the FBR message for user action.
- Sequential, one-by-one sending per the requirement; respect FBR rate limits.
- Celery tasks must be safe to re-run (acks late, idempotent), survive worker restarts, and never lose state held only in memory.
- On completion, send an email to the admin with a summary (sent / failed counts).
- Mock FBR client for dev/test; real FBR calls only in staging/production with proper tokens.
- Log every FBR request/response (with token redacted).

## 8. Database Rules

- PostgreSQL database name: `cheena_database`.
- All schema changes via **Alembic migrations** — never edit the schema by hand; migrations must be reviewable and reversible where possible.
- Use `snake_case` plural table names, integer or UUID primary keys (pick one and be consistent), `created_at`/`updated_at` on all tables, `created_by` where relevant.
- Money and tax values: `NUMERIC` (e.g., `NUMERIC(14,2)`), **never float**. Quantity and rates use appropriate precision.
- Enforce integrity with foreign keys, `NOT NULL`, unique constraints (e.g., shop code, POS ID, shop+date upload), and check constraints.
- Index columns used in filters/joins (shop_id, date, status).
- Prefer soft delete / status flags for business records; hard deletes only for non-business data.
- Use transactions for multi-step writes (e.g., file import inserts file header + all rows atomically).
- No raw SQL string concatenation; use SQLAlchemy parameters.

## 9. Security Requirements

- Passwords hashed with a strong algorithm (argon2/bcrypt); never stored or logged in plain text.
- Authentication via secure tokens (short-lived access token + refresh, or secure httpOnly session cookies); logout invalidates sessions.
- Password set/reset through single-use, expiring email links.
- **Authorization enforced on the backend** for every endpoint (role/right + shop scope). Hiding menu items is UI only.
- **FBR tokens are secrets:** encrypt at rest, never return them in API responses (mask), never log them, restrict who can view/change them.
- Validate all input (Pydantic on API, size/type checks on uploads). Uploads: accept only `.xlsx`, limit file size, scan structure with openpyxl safely (read-only mode), never execute macros.
- Protect against OWASP Top 10: SQL injection, XSS, CSRF, IDOR, broken access control. Configure CORS to the known frontend origin only.
- HTTPS everywhere in production; secure headers; rate-limit login and sensitive endpoints.
- Secrets in environment variables / secret store; `.env` is git-ignored; provide `.env.example` only.
- Audit log is append-only.
- Regular database backups with tested restore.

## 10. Backend Coding Standards (Python / FastAPI)

- Python 3.12+, type hints everywhere, async where it helps (be consistent with the chosen SQLAlchemy mode).
- Pydantic schemas for all request/response models; never return ORM objects directly.
- Format/lint with `ruff` (+ `black` style); type-check with `mypy`.
- Consistent error responses (status code, machine-readable error code, human message). No raw stack traces to clients.
- Structured logging; no `print`. Never log secrets or personal data (CNIC).
- Small functions, clear names, docstrings on services; no business logic in routers.

## 11. Frontend Coding Standards & UI/UX Guidelines

Standards:
- TypeScript `strict` mode; no `any` unless justified. ESLint + Prettier.
- Next.js App Router; server components where suitable; client components only when needed.
- Use shadcn/ui components and Tailwind utility classes; avoid ad-hoc CSS.
- Form handling with schema validation (e.g., react-hook-form + zod); mirror backend validation messages.
- Centralized API client; handle loading, empty, and error states for every data view.

UI/UX:
- Clean, professional, data-dense but readable layout; responsive (desktop first, tablet usable).
- Sidebar menu shows **only modules the user has rights to**.
- Tables: pagination, sorting, filters (date range, shop), totals row, export where needed.
- Clear status badges for file state (Draft / Wait for Approval / Accept / Reject) and sync state.
- Destructive or irreversible actions (Accept, Cancel sync, delete) require a confirmation dialog.
- Upload screen: template download link, drag-and-drop, row-level validation error report with row numbers.
- Sync screen: live progress (sent / pending / failed), Stop / Cancel / Resume controls, clear time-window display.
- Display time in 24-hour format; amounts with thousand separators and 2 decimals; dates in a consistent format; timezone is Pakistan Standard Time (PKT) for display, stored in UTC.
- Accessible: keyboard navigation, labels, sufficient contrast.

## 12. Testing Requirements

- **Backend:** `pytest`; unit tests for services (Excel validation, calculations, workflow transitions, permissions); API tests with a test database; migration tests (upgrade/downgrade).
- **FBR sync:** tests with a mocked FBR client covering success, timeout, 4xx, 5xx, stop/resume/cancel, duplicate prevention, and worker-restart recovery.
- **Frontend:** component tests (Vitest/React Testing Library) for key forms/tables; E2E (Playwright) for login → upload → approve → sync → report.
- Authorization tests for every protected endpoint (allowed role, denied role, wrong shop).
- Tests must pass in CI before merging; new features require tests; bug fixes require a regression test.
- Never run tests against the production database.

## 13. Development Workflow

- Git with feature branches off `main`; small, focused commits with clear messages; pull requests reviewed before merge.
- Branch naming: `feature/<module>-<short-desc>`, `fix/<short-desc>`.
- Local environment via Docker Compose (backend, frontend, PostgreSQL, Redis, Celery worker); `.env.example` documents all variables.
- Deployment: Docker images on a Linux VPS behind a reverse proxy (nginx/Caddy) with TLS; separate staging config if available.
- CI: lint, type-check, tests, and build on every PR.
- Update docs (`/docs`) and this file when decisions change.
- Always run migrations through Alembic as part of deployment; take a DB backup before production migrations.

## 14. Suggested Build Order

1. Project scaffolding, Docker Compose, config, CI (only when instructed).
2. Database models + Alembic baseline.
3. Authentication, users, roles/permissions.
4. Shop setup (with encrypted FBR token).
5. Excel template download + upload + validation.
6. Sales view with totals and filters.
7. Approval workflow.
8. FBR sync engine (Celery) with mock client, then real integration.
9. Email notifications.
10. Reports, audit log views, hardening, deployment.

## 15. Open Questions (to resolve with the owner)

- Fine-grained Company User permissions; can a user approve their own uploads; shop-scoped approval?
- Email provider for password links and completion notices (SMTP settings live in the Super Admin workspace — implemented in Email Settings Milestone 1; Gmail via App Password is supported).
- Sync window: one-time per run vs recurring schedule? Policy for FBR-rejected records.
- Editing/deleting accepted files; correction/reversal process.
- Bad Excel rows: reject whole file vs partial import.
- Additional reports and export formats (Excel/PDF).
- Staging environment availability.
