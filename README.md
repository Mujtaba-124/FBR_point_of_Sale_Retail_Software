# Cheena FBR POS Software

Single-company, multi-shop, multi-user FBR POS web application. See [CLAUDE.md](CLAUDE.md) for project rules.

**Status: Subscription Management Milestone 2 — renewal, renewal history and server-enforced subscription expiry for the Company Workspace.** No business modules yet.

## Stack
Next.js + TypeScript + Tailwind + shadcn/ui · FastAPI · PostgreSQL (`cheena_database`) · SQLAlchemy + Alembic · Celery + Redis · Docker.

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
| Liveness / readiness | http://localhost:8000/health/live · /health/ready |
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
  made through **Subscription Management → Renew Subscription** in the Super Admin workspace.
  Every creation is recorded in `audit_events`.

### Renewing the subscription

Super Admin → Subscription Management → **Renew Subscription**. The new expiry date must be
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

Super Admin → **Email Settings** stores one SMTP configuration, turns email sending on or off,
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
2. Turn on **2-Step Verification**: Google Account → Security → 2-Step Verification.
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

Super Admin → Email Settings → **Subscription Expiry Reminders**. Off by default.

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
celery_beat ──(every 30 min)──> reminders.evaluate ──> email_outbox rows (PostgreSQL)
celery_beat ──(every minute)──> email_outbox.dispatch ──> existing secure SMTP client
```

- `celery_beat` must run exactly once (`docker compose up -d celery_beat`); `celery_worker` can
  be scaled. Rows are claimed with `SELECT … FOR UPDATE SKIP LOCKED` plus a 5-minute lease.
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
Current head: `0006_reminders` (`users`, `authentication_sessions`, `audit_events`, `app_subscription`, `subscription_renewals`, `email_settings`, `subscription_reminder_settings`, `email_outbox`, `email_delivery_attempts`).

The frontend dev container does not hot-reload on Windows; after editing frontend files run:
```bash
docker compose restart frontend
```
