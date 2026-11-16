# ACADLYTICS — deployment readiness

Status on 2026-11-16: **ready for a supervised staging deployment; not deployed anywhere.** Nothing
in this repository has been run on a cloud account. Docker working locally is not evidence that a
production deployment works; the items in §4 have to be provided and checked on the real host.

## 1. Environments

| | Local development | Staging | Production |
|---|---|---|---|
| Compose files | `docker-compose.yml` | `docker-compose.yml` + `docker-compose.prod.yml` | same as staging |
| `APP_ENV` | `development` | `production` | `production` |
| Secrets | `.env` in the repo folder (gitignored) | env file outside the repo, readable by the deploy user only | a secret manager or that env file; never the repo |
| `JWT_SECRET_KEY` | dev fallback allowed | **required**, unique, 48+ random characters | **required**, different from staging |
| PostgreSQL port | published on `localhost:55432` | not published | not published (or a managed database) |
| API / web ports | `0.0.0.0:8000` / `0.0.0.0:3001` | `127.0.0.1` only, behind the proxy | same |
| Cookies | `ACADLYTICS_INSECURE_COOKIES=1` (plain http) | Secure (HTTPS required) | Secure |
| Data | anything | **copy of production or synthetic only** — never mix fictional seed data with real marks | real marks |
| `FACULTY_DEFAULT_PASSWORD` | optional | empty | empty (administrators set passwords) |

The production override refuses to start when a secret is missing (verified: exit 1 naming
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `JWT_SECRET_KEY`,
`ACADLYTICS_ADMIN_EMAIL`), and the API itself refuses the development JWT secret under
`APP_ENV=production` (`core/config.py`, tested in `test_config.py`).

## 2. Starting a staging or production instance

```bash
# on the host, once: an env file outside the repository
umask 077
cat > /srv/acadlytics/acadlytics.env <<'EOF'
POSTGRES_USER=acadlytics
POSTGRES_PASSWORD=<long random>
POSTGRES_DB=acadlytics
JWT_SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
ACADLYTICS_ADMIN_EMAIL=<the administrator's institutional email>
ACADLYTICS_ADMIN_PASSWORD=<first start only; remove after the Administrator exists>
API_PORT=8000
WEB_PORT=3001
EOF

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file /srv/acadlytics/acadlytics.env up -d --build
```

Then put an HTTPS reverse proxy in front of `127.0.0.1:3001` (the web app; it forwards `/api/v1`
and the session routes to the API itself). Example (nginx):

```nginx
limit_req_zone $binary_remote_addr zone=signin:10m rate=10r/m;
server {
  listen 443 ssl http2;
  server_name acadlytics.example.edu;
  ssl_certificate     /etc/ssl/acadlytics/fullchain.pem;
  ssl_certificate_key /etc/ssl/acadlytics/privkey.pem;
  add_header Strict-Transport-Security "max-age=31536000" always;
  add_header X-Content-Type-Options nosniff always;
  add_header Referrer-Policy same-origin always;
  client_max_body_size 6m;                       # uploads are capped at 5 MB by the API
  location /api/session/login { limit_req zone=signin burst=5; proxy_pass http://127.0.0.1:3001; }
  location / {
    proxy_pass http://127.0.0.1:3001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 120s;                     # a 150-file TLP upload is processed synchronously
  }
}
```

Expose Swagger (`/docs` on the API) only on the private network, if at all; the proxy above does
not route to the API directly.

## 3. What the application already provides

| Area | State |
|---|---|
| Health | `GET /health` (API): database reachability and migration revision; Compose health check on it; web waits for a healthy API |
| Migrations | `alembic upgrade head` on every API start (idempotent); one head, `0008`; empty-database upgrade verified |
| First account | Created once from `ACADLYTICS_ADMIN_*`; no built-in passwords anywhere |
| Containers | API runs as uid 1000 (`appuser`), web as `node`; slim/alpine bases; no secrets baked into images |
| Reproducible builds | `backend/constraints.txt` pins the tested Python versions; `package-lock.json` + `npm ci` for the web |
| Upload limits | 5 MB, 5,000 rows, 200 columns, 150 files per TLP upload; enforced in the API |
| Sign-in throttle | 10 failures / 15 min per account → 429 (per process) |
| Errors | One JSON envelope; unhandled errors logged with stack trace server-side, generic message to the client |
| Startup/shutdown | uvicorn handles SIGTERM gracefully; transactions are per request, so a stop mid-request rolls back |

## 4. What the host must provide (not in the repository)

| Item | Why | Minimum |
|---|---|---|
| HTTPS termination | Session cookies are Secure in production; tokens must not cross plain HTTP | nginx/Caddy/cloud LB with a valid certificate, HSTS |
| Backups | Marks are the institution's record | nightly `pg_dump -Fc`, kept off the host, encrypted; **test a restore** before go-live (procedure in `LOCAL_DEMO_GUIDE.md`) |
| Proxy rate limit | The in-app throttle is per process and per account | e.g. the `limit_req` above on `/api/session/login` |
| Log collection | Container logs only go to stdout | ship `docker compose logs` to the institution's log store; alert on 5xx |
| Error monitoring | No Sentry/OTel hook is wired in | optional; add at the FastAPI app factory if wanted |
| Database | Single PostgreSQL 16 container with a named volume | or a managed PostgreSQL 16 with automated backups; then drop the `db` service |
| Updates | Base images and dependencies age | rebuild monthly; refresh `constraints.txt` deliberately and run the suite |
| Access to the host | Anyone with Docker access can read the database | limit to administrators |

## 5. Known operational limits

- **Scale is unmeasured.** Timings in `TESTING_AND_VERIFICATION.md` are single requests on small
  data (tens of students). The design target is one department (~800 students, ~40 faculty); no
  load test has been run. Run one on staging with a realistic copy before go-live.
- **Synchronous processing.** Large TLP uploads are parsed in the request (no queue). Fine at the
  design scale; set proxy timeouts accordingly.
- **One API process.** Horizontal scaling needs the throttle moved to shared storage (or relied on
  at the proxy) — nothing else in the API keeps per-process state.
- **No password-reset email.** Administrators/HODs reset passwords in *People*.

## 6. Staging checklist

Work through [`STAGING_CHECKLIST.md`](STAGING_CHECKLIST.md) on a staging host first: secrets,
HTTPS, scheduled and off-host backups, a restore drill, log collection and alerts, a load test
(`scripts/load_test.py`, read-only) and the functional suites — each with the command that proves
it and a sign-off line.

## 7. Go-live checklist

- [ ] Env file created outside the repo with unique secrets; `.env` from development not copied
- [ ] `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` passes on the host
- [ ] HTTPS proxy in place; `http://` redirects; certificate valid
- [ ] Administrator signs in over HTTPS; `ACADLYTICS_ADMIN_PASSWORD` removed from the env file
- [ ] Database port not reachable from outside (`nc -z host 5432` fails)
- [ ] Backup job runs; one restore tested into a scratch database
- [ ] `scripts/e2e_live.py` and `scripts/verify_live.py` pass against a **staging** copy (never production: they create data)
- [ ] `npm run test:e2e` passes against staging
- [ ] Load test at the expected class sizes on staging
- [ ] Git-history rewrite pushed, or explicitly declined (`GIT_HISTORY_REWRITE.md`)
- [ ] `STAGING_CHECKLIST.md` completed and signed off
