"""Read-only load test for a STAGING copy of ACADLYTICS (standard library only).

    python scripts/load_test.py --web https://staging.example.edu --users 40 --minutes 5 \
        --accounts accounts.csv

`accounts.csv` (keep it out of the repository) has one `email,password` per line: real staging
faculty/HOD accounts, one per simulated user, reused round-robin. Each simulated user signs in
once through the web app's session route (a successful sign-in never trips the throttle), then
loops over what a teacher does on a normal day:

    overview -> class analytics -> attention -> one student -> class report (CSV)

for the classes their workspace lists, with a short think time. Nothing is written.

It prints per-endpoint request counts, error rate and latency percentiles (p50 / p95 / p99 /
max) and exits 1 if the error rate or p95 exceeds the limits you pass. Agree the limits before
the run (docs/STAGING_CHECKLIST.md, section 6); the defaults are a starting point, not a
measured target.
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

LOCK = threading.Lock()
TIMES: dict[str, list[float]] = defaultdict(list)
ERRORS: dict[str, int] = defaultdict(int)


def record(name: str, ms: float, ok: bool) -> None:
    with LOCK:
        TIMES[name].append(ms)
        if not ok:
            ERRORS[name] += 1


class User:
    def __init__(self, web: str, email: str, password: str) -> None:
        self.web = web.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.token = ""
        self.email, self.password = email, password

    def call(self, name: str, path: str, body: dict | None = None) -> bytes | None:
        headers = {"content-type": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.web + path, data=data, headers=headers)
        start = time.perf_counter()
        try:
            with self.opener.open(request, timeout=60) as response:
                payload = response.read()
            record(name, (time.perf_counter() - start) * 1000, True)
            return payload
        except (urllib.error.URLError, TimeoutError):
            record(name, (time.perf_counter() - start) * 1000, False)
            return None

    def sign_in(self) -> bool:
        payload = self.call(
            "sign-in", "/api/session/login", {"email": self.email, "password": self.password}
        )
        if payload is None:
            return False
        self.token = json.loads(payload)["access_token"]
        return True


def session(web: str, email: str, password: str, deadline: float, think: float) -> None:
    user = User(web, email, password)
    if not user.sign_in():
        return
    workspace = user.call("workspace", "/api/v1/me/workspace")
    if workspace is None:
        return
    offerings = [t["offering_id"] for t in json.loads(workspace)["teaching"]]
    if not offerings:
        listed = user.call("offerings", "/api/v1/insights/offerings?semester=YEAR")
        offerings = [o["id"] for o in json.loads(listed or b'{"items":[]}')["items"]][:5]
    while time.time() < deadline:
        user.call("overview", "/api/v1/insights/overview?semester=YEAR")
        if offerings:
            offering = random.choice(offerings)
            user.call("class-analytics", f"/api/v1/offerings/{offering}/analytics")
            user.call("attention", f"/api/v1/offerings/{offering}/attention")
            roster = user.call("roster", f"/api/v1/offerings/{offering}/students")
            students = json.loads(roster or b"[]")
            if students:
                student = random.choice(students)["student"]["id"]
                user.call("student", f"/api/v1/offerings/{offering}/students/{student}/analytics")
            user.call("report-csv", f"/api/v1/offerings/{offering}/reports/class_summary?format=csv")
        time.sleep(random.uniform(0.5, 1.5) * think)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", required=True)
    ap.add_argument("--accounts", required=True, help="CSV of email,password (not in the repo)")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--think", type=float, default=2.0, help="seconds between page views")
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--max-p95-ms", type=float, default=2000)
    args = ap.parse_args()

    with open(args.accounts, newline="", encoding="utf-8") as handle:
        accounts = [(row[0].strip(), row[1]) for row in csv.reader(handle) if len(row) >= 2]
    if not accounts:
        print("No accounts in the CSV.", file=sys.stderr)
        return 2
    deadline = time.time() + args.minutes * 60
    print(f"{args.users} users for {args.minutes} min against {args.web} ...")
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        futures = []
        for n in range(args.users):
            email, password = accounts[n % len(accounts)]
            futures.append(pool.submit(session, args.web, email, password, deadline, args.think))
            time.sleep(0.2)  # ramp up
    # A simulated user that crashed must fail the run, not vanish from the numbers.
    crashed = [f.exception() for f in futures if f.exception() is not None]
    for exc in crashed[:3]:
        print(f"simulated user crashed: {type(exc).__name__}: {exc}", file=sys.stderr)

    total = sum(len(v) for v in TIMES.values())
    errors = sum(ERRORS.values())
    print(f"\n{'endpoint':<16}{'n':>7}{'err':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}   ms")
    worst_p95 = 0.0
    for name in sorted(TIMES):
        values = TIMES[name]
        p95 = percentile(values, 0.95)
        if name != "sign-in":
            worst_p95 = max(worst_p95, p95)
        print(
            f"{name:<16}{len(values):>7}{ERRORS[name]:>6}{statistics.median(values):>9.0f}"
            f"{p95:>9.0f}{percentile(values, 0.99):>9.0f}{max(values):>9.0f}"
        )
    rate = errors / total if total else 1.0
    print(f"\n{total} requests, error rate {rate:.2%}, worst p95 (excluding sign-in) {worst_p95:.0f} ms")
    if crashed:
        print(f"{len(crashed)} of {args.users} simulated users crashed")
    ok = not crashed and total > 0 and rate <= args.max_error_rate and worst_p95 <= args.max_p95_ms
    print("PASS" if ok else "FAIL", f"(limits: error rate <= {args.max_error_rate:.0%}, p95 <= {args.max_p95_ms:.0f} ms)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
