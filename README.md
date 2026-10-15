# ScamShield AI

Digital risk protection for brand impersonation across social platforms and mobile app stores — built for
**byteXL HacXLerate Challenge 03**.

ScamShield searches public sources for accounts and apps that look like your brand, excludes your official
assets by exact identifier, scores what remains on independent evidence, and gives analysts a workflow to
confirm, dismiss and track findings over time.

```
frontend/  Next.js 16 · React 19 · TypeScript · Tailwind CSS v4 · Recharts      (port 3000)
backend/   FastAPI · SQLAlchemy 2 · RapidFuzz · Pillow/ImageHash · scikit-learn  (port 8000)
```

The browser only talks to the Next.js origin; `/api/*` is proxied to FastAPI, so the session cookie is
first-party and no API URL or secret is shipped to the client.

---

## 1. Quick start (local, no credentials needed)

Prerequisites: **Python 3.12** and **Node.js 20+** (developed with Node 24).

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt      # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt        # macOS/Linux
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# Frontend (second terminal)
cd frontend
npm install
npm run dev            # http://localhost:3000
```

The SQLite database is created automatically at `backend/data/scamshield.db` on first start.

Optional — create the local demo account, demo brand and a first demo scan in one step:

```bash
cd backend
.venv/Scripts/python scripts/seed_demo.py
```

The seeded credentials are the `SEED_EMAIL` / `SEED_PASSWORD` values in `backend/.env.example`
(local development only; the script refuses to run unless `SCAMSHIELD_ENV=development`).

**Docker (written, not yet run — Docker was unavailable in development):**

```bash
cp .env.docker.example .env          # set POSTGRES_PASSWORD, PUBLIC_URL, SMTP_*, optional secrets
docker compose up -d --build         # PostgreSQL + API (migrates at startup) + scheduler worker + frontend on :3000
```

Put an HTTPS reverse proxy in front: production cookies are `Secure`.

Production build of the frontend: `npm run build && npm start` (set `BACKEND_URL` if FastAPI is not on
`http://127.0.0.1:8000`).

---

## 2. Environment variables

Backend settings use the `SCAMSHIELD_` prefix and can be placed in `backend/.env` (template:
`backend/.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `SCAMSHIELD_ENV` | `development` | `production` enables secure cookies and disables dev-only reset-link logging |
| `SCAMSHIELD_DATABASE_URL` | `sqlite:///backend/data/scamshield.db` | SQLAlchemy URL. PostgreSQL: `postgresql+psycopg://user:pass@host:5432/db` |
| `SCAMSHIELD_UPLOAD_DIR` | `backend/data/uploads` | Re-encoded brand logos |
| `SCAMSHIELD_FRONTEND_ORIGIN` | `http://localhost:3000` | Used to build password-reset links |
| `SCAMSHIELD_COOKIE_SECURE` | auto (true outside dev) | Force the `Secure` cookie flag |
| `SCAMSHIELD_SESSION_TTL_HOURS` | `720` | “Keep me signed in” session + cookie lifetime (30 days) |
| `SCAMSHIELD_SHORT_SESSION_TTL_HOURS` | `12` | Default session lifetime (browser-session cookie) |
| `SCAMSHIELD_EMAIL_VERIFICATION_TTL_HOURS` | `48` | Verification link lifetime |
| `SCAMSHIELD_HTTP_TIMEOUT_SECONDS` | `12` | Per-request timeout to sources |
| `SCAMSHIELD_SOURCE_TIMEOUT_SECONDS` | `90` | Query time budget per source per scan |
| `SCAMSHIELD_SCHEDULER_ENABLED` | `true` | Run the scheduler inside the API process (development). Set `false` on API replicas in production and run the worker instead |
| `SCAMSHIELD_SCHEDULER_TICK_SECONDS` | `60` | How often the scheduler checks for due schedules |
| `SCAMSHIELD_SCHEDULER_MAX_CONCURRENT_SCANS` | `2` | Maximum scheduled scans running at once; extra due runs are deferred 5 minutes |
| `SCAMSHIELD_PROCESS_ROLE` | `api` | `api` or `worker` (the worker sets this itself). Scans record which role runs them, so a restart only fails its own interrupted scans |
| `SCAMSHIELD_RESOLVE_AFTER_MISSES` | `2` | Default number of consecutive clean misses before a finding is resolved (per-organization override in Settings → Detection) |
| `SCAMSHIELD_AUTH_RATE_LIMIT_ATTEMPTS` / `_WINDOW_SECONDS` | `10` / `300` | Auth rate limiting |
| `SCAMSHIELD_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM` | unset | Password-reset email delivery |
| `SCAMSHIELD_USER_AGENT` | ScamShieldAI/1.0 … | Sent to sources — set a real contact address in deployments |
| `SCAMSHIELD_SOURCE_RETRY_DELAY_SECONDS` | `1.5` | Delay before the single retry of a query that timed out or hit a 5xx/network error |
| `SCAMSHIELD_YOUTUBE_API_KEY` | unset | **Secret, optional.** YouTube Data API v3 key. Sent only to googleapis.com, in a request header, never in a URL. Without it the YouTube source reports "not configured" and cannot be enabled |
| `SCAMSHIELD_RATE_LIMIT_BACKEND` | `database` | `database`: shared by every API replica, with hashed keys. `memory`: per process |
| `SCAMSHIELD_METRICS_TOKEN` | unset | **Secret, optional.** Bearer token for `GET /api/metrics` (Prometheus text). The endpoint returns 404 while this is unset |
| `SCAMSHIELD_MASTODON_ACCESS_TOKENS` | unset | **Secret, optional.** `instance=token,instance2=token2` (scope `read:search`). Each token is sent only to its own instance; never returned by the API, shown in the UI or logged |

Frontend: `BACKEND_URL` (server-side only, default `http://127.0.0.1:8000`).

No API keys are required: every integrated source is public and unauthenticated.

---

## Render deployment

The repository includes [`render.yaml`](./render.yaml), which creates a free-tier PostgreSQL
database, FastAPI API service, and Next.js frontend. The API runs the scheduler in-process so a
separate paid background worker is not required for this deployment.

In the Render Dashboard, choose **New → Blueprint**, connect this repository, and apply the
Blueprint. The frontend is built with `BACKEND_URL=https://scamshield-api.onrender.com`, and
proxies its same-origin `/api/*` requests to the API service. If the service names or domains are
changed, update `BACKEND_URL` on the frontend and `SCAMSHIELD_FRONTEND_ORIGIN` on the API before
redeploying.

Optional credentials such as SMTP, YouTube, Mastodon, and metrics tokens should be added as
secrets in Render's environment settings, not committed to `render.yaml`.

For this temporary demo deployment, `SCAMSHIELD_DEMO_MODE=true` enables **Continue as demo**.
That button creates a short-lived session for a synthetic Demo Analyst workspace. Set this
variable to `false` before using the application with real users.

---

## Vercel + Railway deployment

As an alternative to Render, deploy the `frontend/` directory as a Next.js project on Vercel and
deploy the `backend/` directory as a Docker service on Railway. The backend includes
[`backend/railway.toml`](./backend/railway.toml), and the frontend includes
[`frontend/vercel.json`](./frontend/vercel.json).

On Railway, add a PostgreSQL service and set these API variables:

```text
SCAMSHIELD_ENV=production
SCAMSHIELD_DATABASE_URL=${{Postgres.DATABASE_URL}}
SCAMSHIELD_FRONTEND_ORIGIN=https://<your-vercel-domain>
SCAMSHIELD_SCHEDULER_ENABLED=true
SCAMSHIELD_PROCESS_ROLE=api
```

On Vercel, set `BACKEND_URL=https://<your-railway-api-domain>` before building. The Next.js
rewrite keeps API calls same-origin in the browser, so session cookies continue to work. The
Railway service must expose port `8000` and pass `/api/health/ready`.

---

## Scheduled monitoring (`backend/app/services/scheduler.py`, `app/worker.py`)

Each brand can have one **monitoring schedule**, stored in the database (`monitoring_schedules`). It runs:
* **daily** at a local time;
* **weekly** on chosen days at a local time; or
* **every N hours** (1 hour to 30 days).

Schedules use an IANA time zone, so a 09:00 Europe/London scan stays at 09:00 local time through daylight-saving changes. A time that doesn't exist on the spring-forward day (e.g. 02:30) runs at the matching time just after the gap (03:30). An ambiguous fall-back time runs once.

Schedules are set on the brand's **Monitoring** tab, which has **Pause**, **Resume** and **Disable** controls.
Resuming plans the next run from now, so runs missed while paused or while the scheduler was down are skipped, not replayed all at once.

**Running the scheduler.** Scheduled scans run on the server. No browser tab needs to stay open.

```bash
# Development: nothing extra — the API process runs the scheduler (SCAMSHIELD_SCHEDULER_ENABLED=true).

# Production: one worker process, and the scheduler switched off in every API replica.
SCAMSHIELD_SCHEDULER_ENABLED=false uvicorn app.main:app --host 0.0.0.0 --port 8000     # each API replica
cd backend && python -m app.worker                                                  # exactly one worker (systemd/supervisor/container)
```

The worker uses the same database and settings as the API. Scheduled scans run inside the worker, and manual scans still run in the API.
Ctrl+C or SIGTERM marks the worker's in-progress scans as failed ("Cancelled"), so they are never left half-done.
The Scan History page and the Monitoring tab show whether the scheduler is running, based on a heartbeat it writes to the database each tick. If no process is running it, the UI says so.

**Safety rules**
* **One run per due time:** a scheduler claims a run with a compare-and-set update, so two scheduler processes cannot both start it.
* **No overlapping scans:** a unique database index allows only one queued or running scan per brand. A scheduled run that finds a scan already running is skipped and recorded as *skipped — scan already running*. A manual "Scan now" gets `409`.
* **Concurrency limit:** at most `SCAMSHIELD_SCHEDULER_MAX_CONCURRENT_SCANS` scheduled scans run at once. Each source still has its own query spacing, and stops querying when rate-limited or denied access.
* **Back-off:** a failed scheduled scan retries after 15 minutes, doubling each time up to 24 hours. After 5 consecutive failures the schedule pauses itself and shows the reason. A successful run resets the count.
* **Stalled scans:** a scan with no progress for 20 minutes (e.g. a crashed worker) is marked failed. Errors in one schedule never stop the others.

**Change detection and resolution rules** (`scanner._apply_absence_rules`)

Every scan records what it concluded about each finding (`finding_changes`, shown on the scan detail page):
* **new**
* **changed**, with the old and new values of each changed field (name, handle, URL, description, avatar, publisher, links) and any risk-level change
* **recurring**
* **reappeared**
* **missing**
* **resolved**
* **unverified**

A finding counts as absent only when **its own source completed cleanly** in that scan: every query succeeded, or the search returned no results.

1. Each clean miss increments the finding's miss count. Below the threshold the finding is **missing** and stays in the review queue. When the count reaches the threshold (2 consecutive clean misses by default, configurable from 1 to 5) it is **resolved** ("no longer observed").
2. A failed, rate-limited, timed-out or **partial** source proves nothing. The finding is **unverified** for that scan and its miss count doesn't change.
3. CSV imports never count as absence. Scans of other sources don't affect the finding.
4. Seeing the finding again resets the count. A resolved finding reopens and is recorded as **reappeared**.

## 3. Database

* **Alembic migrations** (`backend/migrations/`, revision `0001` = baseline). The schema is brought up to date at startup:
  * an empty database runs `alembic upgrade head`;
  * an Alembic-managed database applies any pending revisions;
  * a database created before Alembic gets its missing tables and columns added in place, and is then stamped `head`.

  This upgrade path was verified on the existing development database, with all data kept. `tests/test_migrations.py`
  fails if the models and migrations ever drift apart. To change the schema, edit the models, then:

  ```bash
  cd backend
  .venv/Scripts/python -m alembic revision --autogenerate -m "describe the change"
  ```

  Review the generated file, then commit it.
* **SQLite** (default) is used for development and the default test run.
* **PostgreSQL 16** has been verified (2026-10-13, PostgreSQL 16.15). Create an empty database and set
  `SCAMSHIELD_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname`. Verified on it:
  * the full backend suite (228 passed, including 4 PostgreSQL-only checks);
  * the 11 live-source tests, including the full release workflow;
  * the additive migration path on an existing database;
  * the partial unique index that blocks duplicate active scans.

  Running the suite against PostgreSQL needs an **empty** database:

  ```bash
  SCAMSHIELD_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/scamshield_test .venv/Scripts/python -m pytest -q
  ```

  Testing on PostgreSQL found and fixed two time-zone bugs. On PostgreSQL, columns added by the migration step
  used `timestamp without time zone`, so times were shifted by the server's UTC offset; affected columns are now
  converted to `timestamptz` automatically on startup. Datetimes also came back in the database session's time
  zone; all datetimes are now normalised to UTC.
* All queries go through the SQLAlchemy ORM / expression API (parameterized).

---

## 4. Source integration status

| Source | Integration | Status in testing (2026-10-12) |
|---|---|---|
| **Bluesky** | Public AppView `app.bsky.actor.searchActors` — lexicon: no auth, `limit` 1–100. No published AppView quota; backs off on 429 and honours `Retry-After` / `RateLimit-*` when sent | ✅ Live — verified 2026-10-13 (live test suite) |
| **Mastodon** | `GET /api/v2/search?type=accounts&limit=40` on configured instances (default `mastodon.social`). Unauthenticated: accounts only, no `resolve`/`offset` (never sent). 300 req / 5 min per IP, tracked via `X-RateLimit-*` | ✅ Live — verified 2026-10-13 (live test suite) |
| **Apple App Store** | Apple's public iTunes Search API (`entity=software`), unauthenticated, documented by Apple. Apple asks for ~20 requests/minute; HTTP 403/429 is reported as *rate limited*. No developer-ID lookup is needed: results carry `artistId` and `bundleId` | ✅ Live — 140–146 candidates; one query timed out in one run and was reported as *partial*. Verified again 2026-10-13 (live app tests) |
| **Google Play** | `google-play-scraper` (unofficial page parser) + detail lookups for developer IDs, on a dedicated 4-thread pool with a 10 s socket timeout and a 6 h developer-details cache. The library disables TLS verification process-wide at import; ScamShield undoes that and routes its requests through a verified (certifi) context | ⚠️ Works, but **unofficial**; Play-only scan ~31 s cold / ~8 s with warm cache (2026-10-13, was ~62 s with timeouts); some results lack a package ID and are skipped and counted |
| **YouTube** | YouTube Data API v3 `search.list` (type=channel). Needs `SCAMSHIELD_YOUTUBE_API_KEY`. One search costs 100 of the default 10,000 daily quota units | ⚙️ Opt-in. Tested with mocked responses only: no API key was available, so it is **not verified live** |
| **Look-alike domains** (Certificate Transparency) | crt.sh JSON search for hostnames containing the brand, from certificates issued in the last 120 days. Domains are analysed as text and never visited | ⚙️ Opt-in. Tested with mocked responses. **crt.sh returned HTTP 502 throughout testing on 2026-10-13**, so it is not verified live. The opt-in live test fails with that real error |
| X, Instagram, Facebook, TikTok, Telegram | — | ❌ Not integrated: there is no permitted public search API without approved credentials (Telegram channel search needs a logged-in user session). Shown as “not integrated” in the UI. |
| Synthetic demo | Bundled fictional dataset | Demo brand only, labelled **Simulated** everywhere |
| CSV import | Analyst upload | Labelled **Imported** |

**Sources & Integrations page** (`/app/sources`, `backend/app/services/source_status.py`). Each integration in the registry shows:
* its platform and integration type (official public API, unofficial scraper, or synthetic dataset);
* its **state**: *Live*, *Simulated*, *Disabled*, or *Unavailable* (enabled, but the configuration is invalid or the latest evidence is a failure);
* its health;
* authentication and configuration status;
* the last successful request, the last error, the last attempted scan and the last connectivity test;
* its rate limit: the documented limit, the most recently observed quota headers, and when it was last rate-limited.

Every value comes from stored evidence: finished scan runs and recorded **connectivity tests** (`source_checks`, with history). A source with no evidence says **Not tested**. Nothing is assumed from configuration alone.
* **Connectivity test:** runs one real query ("news"), has a bounded time limit, and records the outcome: successful, no results, rate limited, timed out, unavailable, access denied, error, or invalid configuration.
* **Disabled sources:** a disabled source can still be tested before it is enabled. Testing never enables it, and a disabled source is never scanned.
* **Saving settings:** settings are validated first. The storefront must be a valid ISO 3166 country code, hostnames must be valid, and Google Play needs its library installed. Each newly added Mastodon instance must resolve to a public address and answer `GET /api/v2/instance` like a Mastodon server.
* **Permissions:** only owners can change source configuration.
* **Dashboard and sidebar:** these show the same registry state.

Each query records an outcome — **Successful**, **No results**, **Rate limited**, **Timed out**, **Unavailable**, **Access denied / auth required** or **Error** — and each source run reports `ok`, `empty`, `partial` or `failed` with the dominant failure reason. A rate-limited or access-denied source stops querying instead of retrying blindly. A timeout or 5xx response is retried once after a short delay, within the source's time budget. Auth and other 4xx errors are not retried. With several Mastodon instances, one failing instance marks the source *partial* and is named, rather than silently dropped.

Live verification (real network, opt-in): `SCAMSHIELD_LIVE_TESTS=1 .venv/Scripts/python -m pytest tests/test_live_sources.py` — real Bluesky and Mastodon queries, genuinely empty results, official-account exclusion on live data (`@bsky.app`, `@Mastodon@mastodon.social`), cross-instance de-duplication, an unreachable instance reported as unavailable, a Google Play query over verified TLS, an end-to-end live social scan, real App Store results run through the engine with the official PayPal app excluded by bundle ID, an end-to-end live App Store + Google Play scan, and the **full release workflow** (`test_release_end_to_end_workflow_live`): register → brand with official accounts and apps → live scan of all four sources → de-duplication → official exclusion → scoring → persisted evidence → review → CSV and evidence-report export → rescan and compare. All 11 passed on 2026-10-13, and again after the newest features were added. The 12th, `test_ct_domains_real_query`, fails with crt.sh's real outage (`ct_domains unavailable (HTTP 502)`) until that service is back. In the release run all four sources returned `ok`: 630 unique candidates, 7 official assets excluded, 159 findings (9 medium, 150 low, none high or critical for the brand's own fans and namesakes), and a second scan reported all 159 as recurring, with nothing resolved after one scan.

Honesty rules enforced in code:
* A failing source is marked failed/partial and **never** replaced with synthetic data.
* Synthetic data is available only to the demo brand (`400` for other brands).
* Findings are only marked “no longer observed” when their source completed *cleanly* in the scan;
  failed sources and CSV imports never resolve findings.
* Scans are periodic searches; the UI does not claim real-time streaming.

---

## 5. Detection engine (`backend/app/detection/`)

| Module | What it does |
|---|---|
| `normalize.py` | NFKC, case-fold, accent stripping, zero-width removal; **confusable skeletons** (Cyrillic/Greek homoglyphs, leetspeak, `rn→m`, `vv→w`, separators) |
| `variants.py` | Bounded search-term generation (≤ 8 per brand); detection of homoglyphs, spacing, added risky terms, typo distance (word-aligned windows) |
| `similarity.py` | Name, handle and **bundle/package ID** similarity: skeleton match, brand containment, normalized Levenshtein, typo windows (RapidFuzz). Package IDs ignore boilerplate segments (`com`, `app`, `android`…) and flag reuse of an official app's namespace (`com.brand.*` not on the allowlist) |
| `logo.py` | pHash + dHash with safe decoding; similarity requires both hashes to agree |
| `text.py` | TF-IDF (word 1–2-grams) cosine vs. brand description, keywords and descriptions of official listings found in the same scan; brand names removed first to avoid double counting |
| `urls.py` | Look-alike/brand-bearing domains, punycode, IP literals, shorteners, messaging hand-offs, abuse-prone TLDs, credential keywords — string analysis only, links are never fetched |
| `scam.py` | Scam indicator categories (giveaway, credential/wallet request, directed payment request, off-platform contact, support impersonation, urgency, phone, “official” claims); weak-only matches are capped below the corroboration threshold |
| `publisher.py` | App publisher mismatch by **publisher ID**; same official publisher = mitigating; developer display name alone is never trusted |
| `exclusion.py` | Official asset exclusion before scoring: platform+handle, account ID, canonical profile URL, Bluesky domain handles under official domains, Mastodon rel=me verified links, bundle/package ID, Apple track ID. Every exclusion is recorded (audit trail). |
| `scoring.py` | Grouped, weighted, corroboration-gated classification (below) |

**Scoring.** Signals are grouped into independent evidence groups — identity (name, handle → `max`), visual,
content, links, behaviour, provenance (apps only). Identity = max(name, handle, package ID). Score = 100 × Σ weight·group ÷ Σ weights *applicable to the
candidate type*; unavailable signals contribute 0 and are listed as “not evaluated”.
A candidate must pass a relevance gate (identity ≥ 0.70 or logo ≥ 0.85). Levels require corroboration:
`medium` ≥ 35 and 1 corroborating group, `high` ≥ 50 and 2, `critical` ≥ 55 and 2 including scam
behaviour. **Name similarity alone, or a different publisher alone, can only produce “low”.** Publisher mismatch is *supporting* evidence only: it adds to the corroboration count but an app needs at least one other corroborating group (logo, description, links or scam cues) before it can be rated medium or above — fan apps, resellers and namesakes routinely have a different developer and package ID. On live App Store data for PayPal, *PayPal Honey* (published by “Honey”) stays low for this reason. All weights and
thresholds are editable per organization (Settings → Detection). Scores are heuristic triage evidence, not
probabilities; every finding is labelled “review required”.

Calibration notes from live data: an early version let “AnyPal”, “PayPOS” and “Afterpay” match “PayPal” and
let generic “customer support / phone number” text corroborate. Both were fixed and are now covered by
regression tests (`TestLiveFalsePositiveRegressions`). On a live PayPal scan, medium-or-higher findings fell
from 8 to 2 after these fixes, with the official App Store and Google Play apps excluded by ID.

### Investigations (`backend/app/services/evidence.py`, `/app/investigations/[id]`)

The investigation page shows information in this order:
1. The finding: classification, risk, review status and “Why flagged?”.
2. **Observed facts**, copied as-is from the stored record. Each fact names the field it came from.
3. **Heuristic inferences**: the stored signal scores, grouped, with any corroboration marked.
4. **Shared observable indicators**.
5. A collapsed **Technical metadata** panel with raw source fields and hashes.

The side column shows the official assets used for comparison (logo, matched brand name, official apps or accounts on that platform, official domains), provenance with collection times and every observation, and the review history.
Everything shown comes from stored records. Nothing is fetched or generated when someone opens the page.

* **Decisions:** `confirm`, `mark_safe` (shown as *Mark legitimate*), `escalate` (*Further review*), `reopen`
  and `note`. The API enforces which status changes are allowed (`409` otherwise; empty notes return `422`).
  Every decision stores the user, the time, the note and the `from_status → to_status` change, so the
  history is a complete audit trail.
  Findings in *Further review* stay in the review queue and the open counts. Findings from another
  organization return `404`.
* **Shared indicators** (`GET /api/findings/{id}/related`): exact matches on the same URL, web domain,
  email address, phone number, messaging link (t.me/wa.me), handle on another platform, or developer ID.
  Values come only from stored fields. The brand's own domains and generic hosts (bit.ly, linktr.ee,
  app stores, …) don't count as shared domains. A match is presented as an observation, never as
  common ownership or a coordinated campaign.
* **Evidence report** (`GET /api/findings/{id}/report?format=html|json`): one downloadable file with the
  statement *“Potential impersonation — review required”*, observed facts, inferences, the official
  assets compared, shared indicators, provenance, observation history and review history. Synthetic
  records are marked SYNTHETIC. Analyst notes are HTML-escaped.

---

### Detection accuracy (Settings → Detection)

* **Analyst-labelled metrics** (`/api/evaluation`): ground truth is your analysts' decisions (*Confirmed* = impersonation,
  *Marked legitimate* = not). It shows:
  * precision, recall, F1 and the confusion matrix at each risk level;
  * a sweep of minimum scores from 0 to 100, with the best-F1 threshold;
  * per-source precision and recall at medium.

  Fewer than 20 labels is flagged as anecdotal. Synthetic demo decisions are excluded. These numbers can be optimistic, because analysts see the score before deciding.
* **Regression benchmark** (`app/evaluation/benchmark.py`): 26 hand-labelled synthetic cases run through the live engine.
  * **What it contains:** impersonations, legitimate look-alikes, official assets, and hard cases. The hard cases are a quiet impersonator, a fan contest that uses giveaway wording, a reseller app that copies the brand's description, and a parody account.
  * **Result at medium and above:** precision 0.83, recall 0.91. Official assets are always excluded.
  * **Known trade-offs:** the fan contest and the reseller app are flagged (false alarms), and the quiet impersonator stays low (a miss).
  * **As a guard:** `tests/test_evaluation.py` fails if precision drops below 0.8 or recall below 0.85.

  It guards against regressions; it does not measure real-world accuracy.

### Alerts (Settings → Notifications)

* **Per-user email alerts:**
  * new critical findings (on by default);
  * new high findings (off by default);
  * a source failing in two consecutive scans, or a schedule pausing itself;
  * an optional daily digest at a chosen local hour and time zone.
* **Organization webhook** (owners only): Slack-compatible JSON with a `text` field. The URL must be `https` and resolve to a public address, is stored server-side, and is only ever shown masked.
* **Delivery log:** every attempt is recorded with its real outcome: `sent`, `logged` (development without SMTP), `skipped` (no SMTP) or `failed`. "Send test" reports the true result.

### Takedowns (`/app/takedowns`, investigation page)

For a **confirmed** finding, open a case. ScamShield generates an evidence-based report for that platform's own reporting route: the App Store dispute form, Google's legal removal form, in-app reporting on Bluesky and YouTube, the hosting instance's moderators on Mastodon, or Safe Browsing and the registrar for domains.
* **Statuses:** draft → reported (needs a reference or note) → acknowledged → removed / rejected / withdrawn. Invalid transitions return `409`.
* **Re-checks:** later scans record whether the account or listing is *still visible*, *no longer observed* (two clean misses), or *seen again after removal*.
* **No automatic filing:** ScamShield never files or sends a report itself, and the UI asks analysts to check the reporting form is still current.

### Bulk triage and assignment

* **Bulk actions:** on Investigations, select findings and confirm, mark legitimate, send for further review, or assign/unassign them, up to 200 at a time. Each finding is checked on its own: an invalid item is reported without blocking the rest, and findings from other organizations come back as "not found".
* **Assignment:** set the assignee on the investigation page or in bulk. Only organization members can be assigned. Filters: *Assigned to me* and *Unassigned* on Investigations and the Review Queue.

### Possible campaigns (`/app/campaigns`)

* **Grouping rule:** findings are clustered when they share one strong indicator (phone, email, messaging link, developer ID or full URL) or two weaker ones (a web domain plus a handle on another platform).
* **Too-common values:** a value shared by more than 25 findings is ignored as meaningless.
* **Labelling:** each cluster is shown as *Possible campaign* with the values its members share, and an explicit note that sharing a value does not prove common ownership.

### Executive report and look-alike preview

* **Executive report** (Dashboard → *Executive report*): a print-ready HTML summary for 7, 30, 90 or 365 days. Save it as PDF from the browser. It covers new findings by level with a weekly chart, confirmed vs legitimate, review backlog, median time to decision, scan reliability, takedown outcomes, analyst-labelled accuracy and source health. Synthetic data is excluded and counted separately.
* **Look-alike preview** (brand form): shows the search terms that will be sent and illustrative look-alikes (homoglyphs, typos, added words, domains). Each example is marked with whether name matching alone would put it in review. These are generated examples, not observations.

### Brand autofill from a website (Configure → Brand Profiles → New brand)

Paste a brand's official website and press **Autofill**. ScamShield reads only the public page and fills the form with what the site itself declares:
* the name (site name or title) and the description;
* the website and its domains;
* the logo, taken from the site icon or share image and checked as a real image (at least 32 px, 2 MB max);
* linked social profiles (X, Bluesky, Mastodon via rel=me, Instagram, Facebook, YouTube, TikTok);
* App Store and Google Play links. App Store listings are looked up with Apple's public lookup API for the bundle ID, developer and developer ID.

It only fills empty fields and adds what it finds, and nothing is saved until you press Save. The result lists what was found and what was not, so nothing is guessed. Safety: https only, every redirect is re-checked to make sure it resolves to a public address, pages and images are size-limited, and requests are rate-limited (10 per 5 minutes per user). Each autofill is recorded in the audit log.

## 6. Security

* **Auth:** built into the FastAPI backend (no third-party identity provider). Argon2id password hashing;
  opaque 256-bit session tokens in `HttpOnly`, `SameSite=Lax` cookies (`Secure` in production); only SHA-256
  token hashes are stored; logout revokes the server session; password change/reset revokes other sessions;
  generic login errors; dummy-hash verification for unknown emails.
* **Sessions / remember me:** by default a browser-session cookie (no `Max-Age`) backed by a 12-hour server
  session; “Keep me signed in” issues a 30-day persistent cookie. A 401 for a request that carried a session
  cookie clears the stale cookie and returns `X-Session-State: expired`; the app then sends the user to
  `/signin?next=…&reason=expired`. Post-login redirects accept only `/app…` paths (no open redirects or
  loops). The Next.js middleware is a UX redirect only — every API call is authorized server-side.
* **Email verification:** a single-use, hashed, 48-hour token is issued on sign-up, invite acceptance and
  email change (bound to the address it was issued for). Unverified users see a banner with “Resend link”
  (3 per 10 minutes). Verification is informational and does not block sign-in.
* **Production setup you must complete:** configure `SCAMSHIELD_SMTP_*` so reset, verification and invite
  emails are delivered (without SMTP, development mode writes the links to the backend log and production
  reports email as unavailable); set `SCAMSHIELD_ENV=production` and serve over HTTPS so cookies get the
  `Secure` flag; set `SCAMSHIELD_FRONTEND_ORIGIN` to the public URL used in emailed links.
* **Rate limiting:** login (per IP and per IP+email), signup, reset request/confirm, password change,
  connection tests. In-process limiter — use a shared store (e.g. Redis) when running multiple replicas.
* **CSRF:** all state-changing `/api` requests require the `X-ScamShield-CSRF` header (cross-site requests
  cannot set it without a CORS preflight, which the API never grants).
* **Authorization:** enforced in FastAPI on every endpoint. Brands, scans and findings are fetched only through
  the caller's organization (cross-org access returns 404). The Next.js middleware is a UX redirect only.
* **Uploads:** logos limited to PNG/JPEG/WebP/GIF ≤ 2 MB, content verified with Pillow, decompression-bomb
  guard, re-encoded to PNG (strips metadata/payloads), SVG rejected. CSV imports ≤ 2 MB / 2,000 rows.
* **SSRF:** avatar/icon fetching is https-only, host-allowlisted (known CDNs + configured Mastodon instances),
  DNS-resolved with private/loopback/link-local rejection, manual redirect re-validation, streamed size cap,
  image content-type check. Profile links are never fetched.
* **CSV export** neutralizes spreadsheet formula injection. Every export (findings, scan history, review audit trail) is
  scoped to the caller's organization.
* **Two-factor authentication (TOTP, RFC 6238, standard library):**
  * setup re-checks the password, and the secret is shown only once;
  * after a correct password, login returns a 5-minute, single-use challenge limited to 5 attempts, with no session until a valid code is given;
  * codes can't be replayed;
  * 10 recovery codes are stored hashed and work once each;
  * turning 2FA off needs the password and a code.

  The TOTP secret is stored server-side in plain form (`cryptography` isn't installed and isn't hand-rolled), so protect database access accordingly.
* **Audit log** (Settings → Audit log, owners only, CSV export): who changed source settings, schedules, roles and invites, brands, detection or monitoring settings, the webhook, retention, takedowns or 2FA, and who exported data. Each event records the actor, IP and time. Secrets are never written to it.
* **Request IDs:** every response carries `X-Request-ID` (a well-formed upstream ID is honoured), and log lines include it. Unhandled errors return `500` with the request ID and no internal details.
* **Secrets in logs:** a log filter redacts configured secrets (Mastodon tokens, YouTube key, SMTP password) from every record. A test caught httpx logging full request URLs, which is why the YouTube key is sent in a header.
* **Health and metrics:**
  * `GET /api/health` is liveness;
  * `GET /api/health/ready` checks the database and returns 503 if it's unreachable;
  * `GET /api/metrics` (with `SCAMSHIELD_METRICS_TOKEN`) serves Prometheus counters and latency histograms per route template (never raw IDs), plus scans, open findings, failed notifications and scheduler heartbeat age.
* **Release security audit** (`tests/test_security_audit.py`) runs automatically against the full route table:
  * every route that takes an ID, called as another organization, returns 403, 404, 405 or 422 and never leaks data;
  * every collection endpoint excludes other organizations' records;
  * every private route returns 401 without a session;
  * every state-changing route returns 403 without the CSRF header.
* **Sessions:** users can list their own active sessions and sign out one or all others (`/api/auth/sessions`).
  Logout revokes the session on the server, so replaying an old cookie fails.
* **Secrets:** optional Mastodon tokens live only in server environment variables. They are never returned by
  the API and never logged, and error messages are redacted. `backend/.env` and `backend/data/` are git-ignored;
  only `.env.example` (no real secrets) is meant to be committed.
* Security headers on both apps; API responses `Cache-Control: no-store`.
* No compliance certification is claimed.

Privacy and retention assumptions are documented at `/privacy`; acceptable use at `/terms`.

---

### Settings, review queue and data management

* **Review Queue:** filters for brand (one or all), severity, source and review status, and a header showing
  outstanding work (open findings by severity, further-review count, oldest waiting, decisions in the last 7 days
  overall and by you). Keyboard shortcuts: `J`/`K` move, `C` confirm, `S` mark legitimate, `E` further review,
  `↵` open the investigation. Every decision is saved to the audit trail.
* **Settings → Account:** profile, email change, password change (revokes other sessions), and active sessions
  with "Sign out other sessions".
* **Settings → Organization:** members, roles and invites. Owners manage the team; analysts triage.
* **Settings → Monitoring:**
  * an overview of all schedules (each brand's schedule is edited on its Monitoring tab);
  * the enabled sources;
  * source limits, validated inline and on the server: queries per source (1 to 8), time budget per source
    (30 to 180 s) and logo images per scan (0 to 80);
  * the resolution threshold.

  Only owners can change these.
* **Settings → Data:**
  * per-organization counts;
  * CSV exports of findings, scan history and the review audit trail;
  * a scan-history retention policy (forever, 30, 90, 180 or 365 days). The scheduler applies it once a day, and "Delete now" requires typing `DELETE`.

  Retention removes old per-scan detail (source results, observations, change records and exclusion rows). It never removes findings, decisions or each brand's newest scan.
* **No notification preferences:** the product has no alert workflow (email is used only for verification, password reset and invites), so there are none to configure.

## 7. Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

**268 passed on SQLite, 12 live tests opt-in** (the PostgreSQL run of 228 passed predates the newest features; see section 9) (detection unit tests, source adapters with mocked HTTP, SSRF guards, auth & access control,
cross-organization isolation, brand validation & persistence, logo upload validation, demo scan end-to-end,
filtering/sorting, CSV export & injection guard, rescan comparisons new/changed/recurring/resolved,
safe-finding auto-reopen, scheduler, CSV import, source-failure isolation, settings, app monitoring: package-ID signal,
publisher-mismatch-is-not-proof rule, official bundle-ID exclusion, iTunes normalization, store failures with no fabricated results, app CSV export;
scheduling: DST-safe next-run maths, schedule persistence, pause/resume/disable, repeated scheduled scans with field-level
change detection, overlap skipping, a database-enforced single active scan, compare-and-set claims, a concurrency cap, failure back-off and
auto-pause, stalled-scan recovery, failed/partial sources treated as unverified, missing → resolved → reappeared, a configurable
threshold, history filters and pagination, legacy schedule migration; account and settings: review-queue filters and summary, sessions and logout-others, cross-user session isolation,
logout replay, password validation, monitoring limits (validation, persistence, applied to scans), owner-only changes,
retention preview, typed confirmation and purge that keeps findings, org-scoped exports; release security sweep (see
section 6); shared-hosting domains never make every subdomain official; integrations: registry "not tested" by default, connectivity success / empty / invalid configuration / timeout / rate limit,
observed quota headers, test history, disabled sources not scanned, config validation including live Mastodon-server checks and
private-address rejection, owner-only changes, secret tokens sent only to their instance and never exposed or logged, a single
transient retry, other sources continuing after a failure, dashboard reflecting real source state; investigations: facts and inferences match the stored record, comparison assets, provenance, status transitions and
audit trail, invalid transitions, cross-org 404s, shared indicators, indicator extraction, HTML/JSON evidence reports).

```bash
cd frontend && npx tsc --noEmit && npm run build     # type-check, lint, production build
```

UI verification was done in a real browser against the running stack (sign-up, onboarding, demo brand,
scans with live progress, investigations, decisions, review-queue keyboard triage, brand form, sources
connection test, live PayPal scan).

**End-to-end browser tests (Playwright, Chromium)** — 74 tests across desktop, tablet (768 px) and mobile (Pixel 7), passing on two consecutive full runs:

```bash
cd frontend
npx playwright install chromium   # once
npm run e2e
```

The suite starts its own isolated stack (backend on :8001 with a fresh SQLite database in `frontend/.e2e/`,
frontend on :3001 with its own `.next-e2e` build dir) and uses only the synthetic demo brand, so it never touches
development data or the network. It covers sign-up (policy feedback, duplicate email), sign-in (validation, wrong
password, show/hide, remember-me cookie, redirect to the intended page), logout, expired sessions, demo scan →
dashboard, date and severity filters, keyboard review triage, the investigation workspace (evidence sections, further review → note → confirm → reopen
with audit trail, shared indicator, evidence report), social monitoring cards and
filters, app monitoring (official-vs-candidate comparison, signal breakdown, filters, filtered CSV export), brand creation with field errors and a logo, registry rule toggle and dry-run check, deletion,
cross-organization isolation, scheduled monitoring (a weekly Asia/Tokyo schedule; pause, resume and disable; an honest
"scheduler not running" notice), scan history filters, scan change details with field diffs and missing-vs-resolved, sources & integrations ("Not tested" honesty, disabling a source, inline config validation), review-queue filters and
further review, monitoring settings with inline validation, sessions, data exports and retention, the public site, and
responsive layouts: the mobile menu, and no horizontal overflow on 24 pages (every app page including brand, scan and
investigation detail pages, plus domains, campaigns, takedowns, notifications and audit log) at both tablet and mobile widths; accuracy panel, notification preferences and an honest test send, audit log, takedown case lifecycle, bulk triage, campaigns, look-alike preview, and 2FA setup with two-step sign-in using real TOTP codes.

---

## 8. Demo procedure (≈ 5 minutes)

1. Start backend and frontend (section 1). Open http://localhost:3000 — landing page.
2. **Sign up** (or run `scripts/seed_demo.py` and sign in with the seed account).
3. On Overview choose **Load demo brand** → “Northvale Pay”, badged *Demo · synthetic data*.
4. Press **Scan now**: the top-bar popover shows real progress and per-source query counts.
5. Overview: 15 candidates, 4 official assets excluded, severity distribution, recent findings.
6. Open **N0rthvale Pay** (Investigations): homoglyph, 97% logo match, giveaway text, shortener link →
   *Critical — review required*. Walk through *Observed facts* (verbatim, labelled synthetic) vs *Heuristic
   inferences*, the official assets it was compared with, and the shared indicator: it links to the same
   domain as the look-alike wallet app. That is shown as an overlap, not as proof of common ownership.
   Use **Further review**, add a note, then **Confirm impersonation**. The review history shows each status
   change. Then use **Export report → Evidence report (HTML)**.
7. **Review Queue**: triage with `J`/`K`, `C` confirm, `S` mark legitimate.
8. Show false-positive controls: *Northvale Hiking Club* and *Northvale Pay Fans* stay **Low**;
   *Northvale Pay Business* (same official publisher ID) is Low; *Maya Okafor* is not retained.
9. Press **Scan now** three more times. The synthetic timeline adds a new account and changes the support account
   (now critical); the scan detail shows the old and new description. It then removes the giveaway account: that
   account is **Missing** after one clean scan and **Resolved** after the second. Then set a schedule on the brand's
   **Monitoring** tab (e.g. weekly, Mon and Thu at 09:00 in your time zone) and show the next runs, pause and resume.
   A finding marked legitimate reopens automatically when its listing changes.
10. **Brand Profiles → New brand**: create a real brand (e.g. PayPal with `paypal.com`, App Store bundle
    `com.yourcompany.PPClient` / publisher `283646712`, Google Play `com.paypal.android.p2pmobile` /
    developer `PayPal+Mobile`) and **Scan now** → live results from all four sources (~1–2 min), officials
    excluded by ID, honest partial statuses if a source times out.
11. **Sources & Integrations**: every source shows its state, last successful request, last error and quota. Run
    **Test connection** on one (a real query, recorded in its test history). Note the simulated demo adapter and the
    “not integrated” list.
12. **App Store Monitoring**: expand *Compare with official* on *Northvale Pay - Wallet Login* — developer, developer ID,
    package ID and icon side by side with the official app; **Export CSV** downloads the filtered app findings.
13. **Investigations → CSV** export with current filters.
14. **Settings → Data**: download the review audit trail and show the retention policy. **Settings → Account**: active
    sessions.

---

## 9. Known limitations

* Google Play depends on an unofficial scraper and can break without notice; Google may rate-limit it.
* Mastodon search covers only what the configured instances know about.
* Logo comparison requires a brand logo; the live PayPal example above was scanned without one.
* Team: invites are single-use 7-day links (emailed only if SMTP is configured) and accounts belong to one organization. Email verification is informational (it does not block sign-in).
* Rate limiting is shared through the database (best effort at the exact boundary under heavy concurrency). Scheduling
  works across processes, but there is no distributed task queue: manual scans run in the API process that received them.
* PostgreSQL 16 was verified on 2026-10-13, **before** Alembic and the features added afterwards (alerts, takedowns,
  2FA, audit log, bulk actions, new sources). Those were tested on SQLite only. The PostgreSQL-specific tests are
  in `tests/test_postgres.py`. Re-run the suite against PostgreSQL before deploying on it.
* **Docker** (`backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `.env.docker.example`) was written
  but **never built or run**: Docker isn't installed in the development environment. The compose file was only
  checked as valid YAML. Treat it as a starting point and test it before relying on it.
* **Next.js 16.4.0** (upgraded from 15.3.2). Type check, production build and all 74 browser tests pass on it. `next lint` was
  removed in Next 16, so linting now runs ESLint directly (`npm run lint`) with the native flat config. The newer React
  rules in that config report **39 code-quality findings** (mostly "setState inside an effect") that have not been
  refactored; they don't affect behaviour or the build.
* YouTube and Certificate Transparency domains are not verified live (no API key; crt.sh was down). See section 4.
* The TOTP secret is not encrypted at rest (see section 6).
* Heuristic scores are not calibrated probabilities. Live verification used public brands; there is no labelled
  ground-truth dataset, so precision and recall are not measured.
* Not production-ready by default. Production needs HTTPS, `SCAMSHIELD_ENV=production`, SMTP, a managed database
  with backups, a single scheduler worker, a shared rate-limit store if you run several API replicas, and a monitored
  process supervisor. See sections 2, 6 and "Scheduled monitoring".
* A clean install has been verified (2026-10-13), using a fresh `git clone`, a new virtualenv with `pip install -r requirements-dev.txt`
  from PyPI, and `npm ci` from the lockfile. Backend tests, type check, lint, production build and the browser suite
  passed from that checkout. On Windows, keep the checkout path short (for example `C:\src\scamshield`): scikit-learn's
  deeply nested files exceed the 260-character path limit unless Windows long-path support is enabled.
