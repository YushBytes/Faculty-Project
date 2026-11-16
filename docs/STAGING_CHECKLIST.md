# ACADLYTICS — staging deployment checklist

Prepared 2026-11-16. **Nothing has been deployed.** This is the list to work through on a staging
host before any production decision; each item has the command or check that proves it, and a
box to tick with the date and who checked it. Background and the production configuration are in
[`DEPLOYMENT_READINESS.md`](DEPLOYMENT_READINESS.md).

Staging rules: it runs the production configuration (`docker-compose.yml` +
`docker-compose.prod.yml`); its data is **synthetic or a restored copy of production**, never
fictional seed data mixed with real marks; its secrets are **different from production**.

## 0. Host

- [ ] Linux host with Docker Engine + Compose v2, a DNS name (e.g. `acadlytics-staging.<institution>`), ports 80/443 open, nothing else exposed
- [ ] Only administrators can use Docker on the host (`getent group docker`)
- [ ] Clock synchronised (`timedatectl` shows NTP active) — tokens and logs depend on it
- [ ] The repository checked out at the exact commit being staged (`git rev-parse HEAD` recorded here: ____________)

## 1. Secrets

- [ ] Env file outside the repository, owner-only: `install -m 600 /dev/null /srv/acadlytics/staging.env`
- [ ] Contents (all newly generated, none copied from development or production):
      `POSTGRES_USER`, `POSTGRES_PASSWORD` (24+ random), `POSTGRES_DB`, `JWT_SECRET_KEY`
      (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), `ACADLYTICS_ADMIN_EMAIL`,
      `ACADLYTICS_ADMIN_PASSWORD` (first start only)
- [ ] Config refuses to start without them: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /dev/null config` → exits 1 naming the missing variables
- [ ] With them: `... --env-file /srv/acadlytics/staging.env config` shows `APP_ENV: production`, no published database port, api and web on `127.0.0.1`
- [ ] After the Administrator has signed in once, remove `ACADLYTICS_ADMIN_PASSWORD` from the env file and restart; sign-in still works
- [ ] `FACULTY_DEFAULT_PASSWORD` is empty
- [ ] Secrets are not in shell history (`HISTCONTROL=ignorespace` or an editor was used) and not in any ticket or chat

## 2. HTTPS

- [ ] Reverse proxy (nginx or Caddy) in front of `127.0.0.1:3001` with a valid certificate (Let's Encrypt or the institution's CA); config from `DEPLOYMENT_READINESS.md` §2
- [ ] `curl -sI http://<host>/` → 301/308 to `https://`
- [ ] `curl -sI https://<host>/login` → 200 with `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`
- [ ] Certificate valid, full chain: `openssl s_client -connect <host>:443 -servername <host> </dev/null | grep -E "Verify return code: 0"`; TLS 1.2+ only
- [ ] Sign in through `https://` in a browser: the `acadlytics_rt` cookie is `Secure; HttpOnly; SameSite=Strict; Path=/api/session` (browser dev tools → Application → Cookies)
- [ ] Over plain `http://` (if reachable at all) nobody stays signed in — expected, the cookie is Secure
- [ ] The API (`:8000`) and PostgreSQL (`:5432`) are not reachable from another machine: `nc -zv <host> 8000` and `nc -zv <host> 5432` fail
- [ ] Swagger (`/docs`) not reachable from outside (the proxy does not route to the API)
- [ ] Proxy sign-in rate limit active: 20 rapid POSTs to `/api/session/login` from one address → some 503/429 from the proxy (`limit_req`)
- [ ] Certificate renewal scheduled and tested (`certbot renew --dry-run` or Caddy's automatic renewal)

## 3. Scheduled backups

- [ ] Backup script on the host (not in the repository), e.g. `/srv/acadlytics/backup.sh`:
  ```sh
  #!/bin/sh
  set -eu
  stamp=$(date +%F-%H%M)
  out=/srv/acadlytics/backups/acadlytics-$stamp.dump
  docker compose -f /srv/acadlytics/app/docker-compose.yml -f /srv/acadlytics/app/docker-compose.prod.yml \
    --env-file /srv/acadlytics/staging.env exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$out"
  pg_restore --list "$out" > /dev/null          # the dump is readable
  find /srv/acadlytics/backups -name '*.dump' -mtime +14 -delete
  ```
- [ ] Scheduled nightly (cron or a systemd timer), e.g. `15 2 * * * /srv/acadlytics/backup.sh >> /var/log/acadlytics-backup.log 2>&1`
- [ ] Backups copied off the host (institution backup storage), **encrypted** (e.g. `age`/`gpg`), access limited to administrators — the dumps contain student names and marks
- [ ] Retention agreed and written down (e.g. 14 nightly, 8 weekly, 12 monthly)
- [ ] A failed backup alerts someone (non-zero exit → email/chat via the log system)
- [ ] First scheduled run checked the next morning: file present, size plausible, `pg_restore --list` succeeds

## 4. Database restoration (drill)

Do this on staging before go-live, and again each term.

- [ ] Take the latest scheduled dump
- [ ] Restore into a scratch database:
  ```sh
  docker compose ... exec -T db psql -U "$POSTGRES_USER" -d postgres -c "create database acadlytics_restore owner $POSTGRES_USER"
  docker compose ... exec -T db pg_restore -U "$POSTGRES_USER" -d acadlytics_restore < acadlytics-<stamp>.dump
  ```
- [ ] Row counts of every table equal the source at dump time (the query used in `TESTING_AND_VERIFICATION.md` §6); `alembic_version` matches
- [ ] A **full** recovery rehearsal: stop the stack, point it at the restored database (or restore over a fresh volume), start, sign in, open a class — the figures match what was there before
- [ ] Time taken recorded: ______ minutes (this is the recovery time you can promise)
- [ ] Scratch database dropped afterwards

## 5. Log collection

- [ ] Container logs leave the host: Docker `json-file` with rotation (`max-size: 10m`, `max-file: 5` in `/etc/docker/daemon.json`) **and** a shipper (Vector, Fluent Bit, Promtail or the cloud agent) sending `facultyproject-*`/`acadlytics-*` container logs to the institution's log store
- [ ] Proxy access and error logs shipped too (they carry client addresses; the API sees only the web container)
- [ ] Retention and access agreed (logs contain email addresses and request paths, not marks or passwords)
- [ ] Alerts: any 5xx from the API; `/health` failing for 2 minutes (an external uptime check on `https://<host>/login` and an internal one on `127.0.0.1:8000/health`); disk above 80 %; backup failure; certificate expiring in < 14 days
- [ ] Check that no secret is logged: grep a day of logs for the admin email's password, `JWT_SECRET_KEY`, `refresh_token=` → nothing
- [ ] Optional: error monitoring (Sentry/OpenTelemetry) — not wired into the code today; decide whether to add it

## 6. Load testing

- [ ] Staging holds a realistic data set: a restored copy of production, or synthetic data at the expected scale (one department: ~800 students, ~12 sections, ~40 faculty, 6–10 assessments per class)
- [ ] Accept limits agreed **before** the run, e.g. error rate ≤ 1 %, p95 ≤ 2 s for page data, uploads of a 200-row file ≤ 5 s
- [ ] A CSV of staging accounts (outside the repository), then:
  ```sh
  python scripts/load_test.py --web https://<host> --accounts /secure/staging-accounts.csv \
      --users 40 --minutes 10 --max-error-rate 0.01 --max-p95-ms 2000
  ```
  (read-only: sign-in once per simulated user, then overview → class analytics → attention → a student → a CSV report, with think time)
- [ ] Repeat at 2× the expected concurrent users to see where it bends
- [ ] During the run: `docker stats` CPU/memory of api, web, db recorded; PostgreSQL connections (`select count(*) from pg_stat_activity`) recorded
- [ ] A TLP upload of a full section (and a batch of 10 files) timed during the run, by hand in the browser
- [ ] Results written into `TESTING_AND_VERIFICATION.md` (numbers, date, commit) — replacing "unmeasured"
- [ ] Anything over the limits: an issue with the slow endpoint and its query count, before go-live

## 7. Functional verification on staging

- [ ] `npm run test:e2e` with `E2E_WEB=https://<host>` against staging (creates its own `E2E…` department; remove it afterwards or reset staging)
- [ ] `python scripts/verify_live.py --api <API reachable from the test machine>` (creates its own `VER…` department)
- [ ] `scripts/e2e_live.py` only on an **empty** staging database (it refuses otherwise)
- [ ] Never run these against production — they create data

## 8. Sign-off

| Area | Checked by | Date | Notes |
|---|---|---|---|
| Secrets | | | |
| HTTPS | | | |
| Backups | | | |
| Restore drill | | | |
| Logs and alerts | | | |
| Load test | | | |
| Functional tests | | | |

Production is a separate decision after this sheet is complete.
