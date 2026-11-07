# Cheena FBR POS Software

Single-company, multi-shop, multi-user FBR POS web application. See [CLAUDE.md](CLAUDE.md) for project rules.

**Status: Subscription Management Milestone 2 â€” renewal, renewal history and server-enforced subscription expiry for the Company Workspace.** No business modules yet.

## Stack
Next.js + TypeScript + Tailwind + shadcn/ui Â· FastAPI Â· PostgreSQL (`cheena_database`) Â· SQLAlchemy + Alembic Â· Celery + Redis Â· Docker.

## Layout
```
backend/    FastAPI app, Alembic, tests
frontend/   Next.js app
docker-compose.yml
.env.example
```

## First-time setup
1. Install and start Docker Desktop.
2. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD`.
3. Start everything:
   ```bash
   docker compose up -d --build
   ```

## URLs
| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API / docs | http://localhost:8000 / http://localhost:8000/docs |
| Liveness / readiness | http://localhost:8000/health/live Â· /health/ready |
| PostgreSQL (host) | localhost:5433 (container 5432) |
| Redis (host) | localhost:6380 (container 6379) |

Host ports 5433/6380 are used so they do not clash with a local PostgreSQL/Redis.

## Everyday commands
```bash
docker compose up -d            # start
docker compose ps               # status / health
docker compose logs -f backend  # logs
docker compose down             # stop (keeps data volumes)
```
Never use `docker compose down -v` unless you intend to erase the database.

## Authentication

Three access categories, stored on each user row in the database:

| Category | Workspace | Can open |
|---|---|---|
| `super_admin` | `/super-admin` | Super Admin APIs/pages only |
| `company_admin` | `/company` | Company workspace, including admin-only company APIs |
| `company_user` | `/company` | Company workspace, no admin APIs |

The browser calls the API only through the frontend origin (`/api/v1/*` is
forwarded to the backend), using an HttpOnly session cookie. The backend
checks the session and category on every protected endpoint
(401 = not signed in, 403 = wrong category or failed CSRF check).

### Create the first accounts (one time)

There is no sign-up page. Run these once after `alembic upgrade head`. Each
command prompts for the password twice, without showing it (minimum 12 characters):

```bash
docker compose exec backend python -m app.cli create-super-admin --email you@example.com --name "Your Name"
```
```bash
docker compose exec backend python -m app.cli create-company-admin --email admin@example.com --name "Admin Name"
```

- Safe to re-run: if that account already exists, nothing is changed (exit 0).
- A second initial Super Admin or Company Admin with a *different* email is refused (exit 1),
  and an existing email is never overwritten.
- For automation, pipe the password on stdin with `--password-stdin` (never pass it as an argument).

### Change an account's sign-in email

```bash
docker compose exec backend python -m app.cli change-email --current-email old@example.com
```

You are prompted for the new address (twice) and for **that account's current
password**. Without the correct password nothing changes. The command:

- keeps the user ID, password, access category and active status;
- refuses invalid or already-used addresses (case-insensitive);
- signs out all of that account's active sessions;
- writes an `user.email_changed` row to `audit_events` (refusals are recorded as
  `user.email_change_refused`); passwords and hashes are never recorded.

The new address is **not verified**; email verification arrives with SMTP support.

### Configure the company subscription (one time)

The Super Admin dashboard shows **Not Configured** until the single company
subscription exists. Create it once with the real contract dates:

```bash
docker compose exec backend python -m app.cli configure-subscription --company-name "Company Name" --start-date 2026-01-01 --expiry-date 2026-12-31
```

- Dates are calendar days in Pakistan time (`Asia/Karachi`); the expiry date is the last valid day.
- The command only creates the record. If one already exists it refuses; later changes are
  made through **Subscription Management â†’ Renew Subscription** in the Super Admin workspace.
  Every creation is recorded in `audit_events`.

### Renewing the subscription

Super Admin â†’ Subscription Management â†’ **Renew Subscription**. The new expiry date must be
later than the current expiry date and later than today (so an expired subscription becomes
active again); the start date never changes. Each renewal writes one row to the append-only
`subscription_renewals` table (UPDATE/DELETE are rejected by a database trigger) and a
`subscription.renewed` audit event, in the same transaction.

Status rules (computed by the backend): **Active**; **Expiring Soon** at 15 or fewer days
left (including the expiry day, which shows 0 days left); **Expired** from the day after
expiry (0 days, never negative); **Not Started** before the start date.

### Subscription expiry enforcement

Company Workspace access (Company Admin and Company Users) requires a **valid** subscription:
status Active or Expiring Soon, computed in Pakistan calendar days from the database
record and the server clock. A subscription is valid through its whole expiry day and stops
at **00:00 Asia/Karachi the next day**. It is fail-closed: expired, not started, not
configured or invalid dates all deny Company access. The Super Admin workspace is never
blocked, so renewal always remains possible.

- **Where it is enforced:** every route under `/api/v1/company` (a router-level guard in
  `app/api/routes/workspaces.py`), Company login (`app/services/auth_service.py`), and Company
  background jobs (`app/tasks/subscription_guard.py`). The single policy lives in
  `app/services/subscription_access.py`.
- **Error codes (HTTP 403):** `subscription_expired`, `subscription_not_started`,
  `subscription_not_configured`.
- **Login:** valid Company credentials are refused with the code above and **no session is
  issued**.
- **Existing sessions:** kept (identity preserved) but they no longer authorize any Company
  operation, starting from the first request after the boundary, with no scheduler or
  sign-out needed. `/auth/me` still works and reports `company_access.allowed = false`, so the
  UI shows the restricted screen with Sign Out.
- **After renewal:** retained sessions that are still within their normal lifetime (12 h
  absolute, 60 min idle) work again immediately, and users can sign in with their existing
  credentials. Sessions that were signed out or expired stay dead.
- **Future Company Celery tasks** must use `@requires_company_subscription` (checked when the
  worker starts the task) and call `ensure_company_subscription(db)` before each external
  side effect in long jobs (for example each FBR submission). System tasks must not use it.

### Session settings (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `COOKIE_SECURE` | `true` | Local HTTP dev uses `false`. Production must be `true` (startup fails otherwise). |
| `SESSION_ABSOLUTE_TTL_MINUTES` | `720` | Session ends 12 h after sign-in. |
| `SESSION_IDLE_TTL_MINUTES` | `60` | Session ends after 60 min without activity. |
| `LOGIN_MAX_FAILURES_PER_EMAIL` | `5` | Per 15-minute window. |
| `LOGIN_MAX_ATTEMPTS_PER_IP` | `20` | Per 15-minute window. |
| `TRUST_PROXY_HEADERS` | `false` | `true` only if the backend is reachable solely through a trusted proxy. |

## Email Settings (Super Admin)

Super Admin â†’ **Email Settings** stores one SMTP configuration, turns email sending on or off,
and runs two tests: **Test Connection** (connects, secures, signs in; never sends) and
**Send Test Email** (one fixed message; requires sending to be enabled; 5 per 15 minutes; a
retried request never sends twice). Only the Super Admin can use it (Company accounts: 403).
No application emails (reminders etc.) are sent yet.

### Encryption key (required to save an SMTP password)

The SMTP password is encrypted with AES-256-GCM. The key comes only from the environment, never
the database. Generate it once per environment and put it in `.env` (or your secret store):

```bash
python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

```
EMAIL_SETTINGS_ENCRYPTION_KEY=<the generated value>
```

Then recreate the backend: `docker compose up -d backend celery_worker`.

- **Back the key up separately from database backups.** A database backup without the key
  cannot reveal the password; restoring a backup without the key means re-entering the password.
- Without a key, the page says so and saving a password is refused (no default key exists).
- **Rotation:** move the old key to `EMAIL_SETTINGS_PREVIOUS_KEYS` (comma-separated, decrypt
  only), set a new `EMAIL_SETTINGS_ENCRYPTION_KEY`, recreate the backend, re-enter and save the
  SMTP password, then remove the old key.
- The local development `.env` already has a generated key.

### Gmail setup

1. Use a Google account that will send the system's email (a dedicated one is best).
2. Turn on **2-Step Verification**: Google Account â†’ Security â†’ 2-Step Verification.
3. Create an **App Password**: open `https://myaccount.google.com/apppasswords`, enter a
   name (for example "Cheena POS") and click **Create**. Copy the 16-character password.
   (If the page is unavailable, 2-Step Verification is off, or a Workspace admin has disabled
   App Passwords.)
4. In Email Settings click **Use Gmail settings** (host `smtp.gmail.com`, port `587`,
   STARTTLS; port `465` with SSL/TLS also works), then enter:
   - SMTP username: the full Gmail address
   - SMTP password: the App Password (spaces are removed automatically). Never your normal
     Google password.
   - Sender email: the same Gmail address (or an alias verified in Gmail's "Send mail as")
   - Sender name: for example `Cheena FBR POS`
5. **Save settings**, then **Test Connection**. On success, turn on **Email sending** and
   **Send Test Email** to your own inbox (check Spam the first time).
6. "Username or password rejected" means the App Password is wrong or was revoked: create a
   new one and save it (leaving the field blank keeps the old one).

Security notes: TLS is mandatory with certificate and host-name verification; SMTP hosts that
resolve to private, loopback, link-local or other internal addresses are refused (the
connection is pinned to the checked address); only ports 25, 465, 587 and 2525 are allowed.
`SMTP_ALLOW_PRIVATE_HOSTS=true` exists for local relays in development only and is refused in
production.

## Subscription expiry reminders

Super Admin â†’ Email Settings â†’ **Subscription Expiry Reminders**. Off by default.

- **Schedule (fixed, Asia/Karachi days; the expiry date is inclusive):** daily from 15 days
  before expiry to 1 day before, once on the expiry day, then daily for 5 days after expiry.
  Reminders are queued from **09:00 PKT**.
- **Recipients:** the single active Super Admin (none if there are zero or several), and every
  active Company Admin with a valid email. Company Users never receive them. An address in both
  groups gets one copy.
- **Requires:** reminders enabled, SMTP saved, and Email Sending on.
- **Renewal** cancels queued reminders for the old expiry date (`cancelled_obsolete`) in the
  same transaction; the schedule then follows the new date. History is never deleted.

### How it runs

```
celery_beat â”€â”€(every 30 min)â”€â”€> reminders.evaluate â”€â”€> email_outbox rows (PostgreSQL)
celery_beat â”€â”€(every minute)â”€â”€> email_outbox.dispatch â”€â”€> existing secure SMTP client
```

- `celery_beat` must run exactly once (`docker compose up -d celery_beat`); `celery_worker` can
  be scaled. Rows are claimed with `SELECT â€¦ FOR UPDATE SKIP LOCKED` plus a 5-minute lease.
- A database unique constraint (subscription, expiry date, stage, date, recipient) makes the
  scheduler idempotent; Redis only carries wake-up signals.
- **Retries:** transient errors (network, timeouts, SMTP 4xx) retry after 1, 5, 15 and 45 min,
  up to 5 attempts; permanent rejections (5xx, TLS, authentication) are not retried.
- **Catch-up:** a reminder is only sent on its own date. A missed day is never sent later; after
  an outage only today's reminder is queued.
- **Delivery semantics:** at-least-once. If a worker dies after the SMTP server accepted a
  message but before the result was saved, the attempt is marked *uncertain* and retried, which
  can produce a duplicate (same Message-ID). "Accepted by SMTP Server" is not proof of inbox
  delivery.
- **Development/QA:** `EMAIL_TRANSPORT=sink` writes messages to `EMAIL_SINK_DIR` as `.eml`
  files instead of sending them (refused in production).

### End-to-end reminder verification (disposable QA stack)

Simulates the whole reminder period with the real Celery Worker and Beat, without real email
and without touching `cheena_database` or any system clock:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\qa\Invoke-ReminderE2E.ps1
```

It creates `cheena_database_e2e`, uses Redis DB 12 and the file sink, checks 25 simulated days
(21 reminder dates, 42 recipient events) plus renewal, retries, permanent failures, worker
crashes and timezone boundaries, writes a per-day PASS/FAIL report to
`backend/.qa-e2e/reports/`, removes the disposable resources, and exits non-zero on any failure.
Add `-KeepResources` to keep the e2e database and containers for inspection. The backend refuses
`E2E_TEST_MODE` in production and for any database not named `*_e2e`.

## Shop Management (Company Workspace)

`/company/shops` - fields: Shop Name, Branch Name, Shop Code, POS ID, Sales Tax %, FBR Token.

- **Sales Tax %** (`shops.sales_tax_rate`, NUMERIC(5,2)): 0 to 100, at most 2 decimals, required for
  new shops; no statutory rate is hard-coded. Shops created before migration `0013_shop_sales_tax`
  are "Not configured" and cannot take new Excel uploads until a Company Admin (`shops.edit`) sets
  it. Once set it can be changed (with a confirmation) but not removed. A change applies to new
  upload batches only; it is audited in `shop.updated` with the previous and new rate.

- **Uniqueness:** Shop Code and POS ID are unique across all shops, case-insensitively
  (PostgreSQL unique indexes). POS IDs are strings, so leading zeros are kept.
- **Status:** shops are never deleted; they are deactivated and reactivated. Inactive shops keep
  their identity and FBR settings.
- **Permissions:** View = `shops.view`, Create = `shops.create`, Edit = `shops.edit`,
  Deactivate/Reactivate = `shops.delete` (no permanent deletion exists), FBR token =
  `shops.manage_integration`. The Company Admin has all of them; the Super Admin none.
- **FBR token:** optional at creation ("Token not configured"), set or replaced only through the
  token action, never returned by the API, never logged or audited. Blank never clears a token.

### FBR token encryption key

Tokens are encrypted with AES-256-GCM using `FBR_TOKEN_ENCRYPTION_KEY`, a key separate from the
SMTP key (the backend refuses to use the same key for both). Generate it the same way:

```
python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Back it up separately from database backups. To rotate: move the old key into
`FBR_TOKEN_PREVIOUS_KEYS` (comma-separated, decrypt only), set the new key, recreate the backend,
re-enter each shop token, then remove the old key. A shop whose token was encrypted with a key that
is no longer configured shows "Token needs re-entry". The local `.env` already has a key.

### Shop Allowance (Super Admin)

The Super Admin sets how many shops the company may register on **Subscription Management ->
Shop Allowance**: either **Limited** (a whole number, 1-100,000) or **Unlimited** (stored as an
explicit mode with no number, never a sentinel). The Company Workspace only reads it.

- Active **and** inactive shops use a slot. Deactivating never frees one; reactivating never needs one.
- Lowering the limit below current usage changes no shop; new registrations are refused
  (`409 shop_limit_reached`) until the allowance is higher than the registered count.
- Enforcement: the `shop_allowance` row is locked (`SELECT ... FOR UPDATE`) inside every shop
  creation and every allowance change, and the `shops_enforce_allowance` trigger applies the same
  rule to any other insert path. The allowance row cannot be deleted.
- APIs: `GET/PUT /api/v1/super-admin/shop-allowance` (Super Admin, PUT needs CSRF and
  `expected_version`; works after subscription expiry) and `GET /api/v1/company/shops/allowance`
  (`shops.view`). Responses are aggregate only: no shop IDs, names, codes, POS IDs or tokens.
- Each change is audited as `shop_allowance.changed` (previous and new mode/limit, usage count).
- Migration `0009_shop_allowance` starts as Unlimited, matching the behaviour before it existed.
  The 15-active-user limit is separate and unchanged.

### Shop context (All Shops / one shop)

The sidebar's **Shop context** control (desktop sidebar and mobile drawer) switches between
**All Shops** (consolidated) and one active shop. It is a filter, never a permission.

- **Mechanism:** the selection is the URL parameter `?shop=<immutable shop id>` on shop-aware pages
  (today the Dashboard and Excel Uploads; future Approvals, FBR Sync and Reports are added in
  `frontend/src/components/company/shop-context/paths.ts`). Reload, Back/Forward and links reproduce
  it; nothing is stored in the browser. A Company-layout provider remembers the last selection in
  memory, so links back from company-wide pages keep it. Sign-in/out are full page loads and the
  provider is keyed by user ID, so no selection carries over to another account.
  Trade-off: a selection is not remembered across separate tabs or after closing the tab.
- **Company-wide pages:** User Management, Roles & Permissions and Shop Management are never
  filtered; the control is shown read-only there.
- **API:** `GET /api/v1/company/shop-options?selected=<id>` returns active shops (ID, name, code only)
  and the backend's verdict on the selection (`active`, `inactive`, `not_found`, `invalid`). An
  inactive or unknown selection falls back to All Shops with a notice, never to another shop.
- **Backend contract** (`app/services/shop_context.py`): `resolve()` validates every shop ID server
  side (422 invalid, 404 unknown, 409 inactive), offers `Purpose.OPERATE` (active only, FOR SHARE lock),
  `require_single_shop` (e.g. Excel Upload) and `Purpose.HISTORY` (inactive allowed, read-only).
  `shop_access_condition()` is where per-user shop assignments would go; none exist today.
- **Who sees it:** accounts with an implemented shop-aware module: the Company Admin (Dashboard,
  Excel Uploads) and Company Users who hold `uploads.view`.

### User shop access (Company Admin)

Each Company User has one of: **All Shops** (every shop, including shops created later),
**Selected Shops Only** (the shops ticked in Add/Edit User), or **No Shop Access** (the default
for new users and for every user that existed before migration `0010_user_shop_access`). The
protected Company Admin always has all shops and cannot be reassigned.

- Access to shop data = Company account + valid subscription + module permission + shop scope +
  shop status/purpose. A shop assignment never grants a module permission, and User Management,
  Roles & Permissions and Shop Management stay company-wide.
- Tables: `user_shop_access` (one row per Company User, versioned) and `user_shop_assignments`
  (only while the mode is `selected`, enforced by a composite foreign key; deferred triggers require
  at least one shop and allow rows for Company Users only). Assignments survive deactivation of a
  shop, so history stays readable; inactive shops never take new operations.
- APIs (Company Admin only, CSRF): `GET/PUT /api/v1/company/users/{id}/shop-access`
  (`expected_version`; stale forms get 409; no-op saves write nothing) and
  `GET /api/v1/company/shop-assignment-options`. Every change is audited as
  `company_user.shop_access_changed` with previous/new mode and shop IDs.
- Future modules use `app/services/shop_context.py`: `resolve_operational_shop(...)` (one active,
  assigned shop), `resolve_historical_shop(...)`, and `scope_filter(user, context, Table.shop_id)`
  for consolidated queries, which filters inside SQL. Company Users see "All Assigned Shops".

## Excel Uploads (Company Workspace)

Daily sales files per shop: **Download template → choose shop + sales date → choose one `.xlsx` →
Check file (preview with totals and row errors) → Save as Draft → Upload History → detail.**
Approval (Wait for Approval / Accept / Reject) and FBR sync are later modules; uploads stay `draft`.

- **Template** (`GET /api/v1/company/uploads/template`): sheet `Sales` with exactly 8 columns in
  fixed order (Date, Time, Item, Customer Name, CNIC/NTN, Quantity, Rate, Amount) plus an
  `Instructions` sheet. Date cells are shown as DD/MM/YYYY. No formulas, no macros. The previous
  10-column template is refused for new uploads (`legacy_template`), never reinterpreted.
- **Validation** (`app/services/excel_sales.py`): every row must carry the chosen sales date;
  24-hour time; Item required (text, max 200); CNIC/NTN must be a text cell (leading zeros kept);
  quantity > 0 (3 dp); rate ≥ 0 (4 dp); Amount ≥ 0 (2 dp) and Amount = Quantity × Rate within 0.01
  (ROUND_HALF_UP). The uploaded Amount is stored as given. Any invalid row rejects the whole file
  with a row-numbered error list.
- **Sales tax (tax exclusive):** Sales Tax = Amount × rate / 100, rounded ROUND_HALF_UP to 2 places
  per row; Net = Amount + Sales Tax; file totals are sums of the rounded rows. The server calculates
  them; the browser only displays them. The rate is the shop's Sales Tax % for a new Draft, and the
  Draft's own saved rate for a replacement (the shop's current rate is ignored then).
- **Tax snapshot:** every revision stores `applied_sales_tax_rate`, `tax_rate_source`
  (`shop` | `draft` | `legacy_rows` | `legacy_mixed`) and `template_format`
  (`standard_8col` | `legacy_10col`); every row keeps its `tax_percent`. Saved uploads are never
  recalculated from a shop's current rate. The preview's rate is sent back on save
  (`expected_tax_rate`) and compared under the shop/batch row lock; a rate changed after the check
  is refused (409 `tax_rate_changed`) and the file must be checked again.
- **Legacy 10-column revisions** (before `0013`): kept unchanged, viewable and downloadable; Item
  shows "—". Uniform-rate revisions got a `legacy_rows` snapshot from their own rows (both real
  revisions: 18%); a revision with mixed row rates has none (`legacy_mixed`, shown as "Mixed")
  and cannot be replaced (`draft_tax_rate_unknown`) without a future reviewed tax correction.
- **File safety:** `.xlsx` only, size checked while streaming; macros, external links, formulas,
  formula-like text, merged cells, extra columns, encrypted/OLE files and zip bombs are refused.
  Limits (`.env`): `UPLOAD_MAX_BYTES` (5 MB) and `UPLOAD_MAX_ROWS` (5,000).
- **One upload per shop and date:** `UNIQUE (shop_id, sales_date)` on `upload_batches`. A Draft
  can be replaced (`uploads.edit_draft`, `expected_revision` against stale screens); every
  version is kept in `upload_revisions` with its original file, and `upload_revisions` /
  `sales_records` are append-only (database triggers). Uploaders cannot be deleted
  (`ON DELETE RESTRICT`); deactivate users instead.
- **Preview/save integrity:** Save re-sends the file with the preview's SHA-256; a different file
  is refused (409 `preview_mismatch`), and the file is fully re-validated inside the save transaction.
- **Permissions:** `uploads.view` (history, detail, records, original files), `uploads.upload`
  (check and save), `uploads.edit_draft` (replace a Draft; works only together with View and Upload,
  enforced in `can_replace_drafts`), always limited to the user's assigned shops; unassigned or
  inactive shops answer 404/409. `uploads.delete_draft` and `uploads.submit` exist as role options
  but open no route or button yet. The Super Admin has no access.
- **Upload History filters** are kept in the URL as ISO dates (`?from=2026-11-01&to=2026-11-07&status=draft`),
  so reload and Back/Forward show the same list; the fields show them as DD/MM/YYYY.
- **Privacy:** CNIC/NTN is masked in every API response (last 4 characters); audit entries
  (`upload.created`, `upload.replaced`, `upload.rejected`, `upload.original_downloaded`) hold counts
  and IDs, never customer data.

### Original-file storage (back this up)

Original files are private, outside the web root, in the Docker volume `cheena_upload_storage`
(`UPLOAD_STORAGE_DIR=/var/lib/cheena/uploads`, keys `YYYY/MM/<random>.xlsx`, SHA-256 checked on
every read). **Back up this volume together with the database**: a database restore without the
matching files leaves revisions whose original cannot be downloaded (records stay readable).

## Dates (application standard)

Every date people read or type is **DD/MM/YYYY** (07/11/2026 = 7 November 2026) and every
timestamp **DD/MM/YYYY HH:mm** in 24-hour Pakistan time (Asia/Karachi), whatever the browser
or operating-system locale.

- **Display:** `formatDate` / `formatDateTime` in `frontend/src/lib/format.ts`; backend text
  (validation messages, emails) uses `app/core/dates.py`. Do not format dates locally in components.
- **Entry:** the shared `DatePicker` (`frontend/src/components/ui/date-picker.tsx`): typed DD/MM/YYYY
  (slashes added for digit-only typing) or picked from the calendar; impossible dates such as
  29/02/2027 and dates outside the allowed range are reported, never corrected. Native
  `<input type="date">` is not used because its day/month order follows the browser locale.
- **Storage and APIs are unchanged:** DATE columns, ISO `YYYY-MM-DD` in API parameters and JSON,
  UTC timestamps in the database, ISO values in audit metadata and logs.
- **Excel files** keep their own documented contract: a real date cell, or text `2026-11-07` /
  `07-Nov-2026`. Text such as `07/11/2026` is deliberately not accepted in files (it is ambiguous in
  Excel depending on the computer's region); accepting it would be a separate parser decision.

## Tests and checks

Backend tests use a separate disposable database (`cheena_database_test`, created
automatically) and Redis DB 15. They never touch `cheena_database`.

```bash
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend mypy app
docker compose exec frontend npx tsc --noEmit
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

## Migrations
```bash
docker compose exec backend alembic revision --autogenerate -m "message"
docker compose exec backend alembic upgrade head
```
Current head: `0013_shop_sales_tax` (`users`, `authentication_sessions`, `audit_events`, `app_subscription`, `subscription_renewals`, `email_settings`, `subscription_reminder_settings`, `email_outbox`, `email_delivery_attempts`, `company_roles`, `company_role_permissions`, `password_setup_tokens`, `shops`, `shop_allowance`, `user_shop_access`, `user_shop_assignments`, `upload_batches`, `upload_revisions`, `sales_records`).

The frontend dev container does not hot-reload on Windows; after editing frontend files run:
```bash
docker compose restart frontend
```
