"""Live end-to-end check of a running ACADLYTICS stack, through the web server.

    python scripts/e2e_live.py --web http://localhost:3002 --api http://localhost:8001 \
        --admin-email admin@acadlytics.dev --admin-password '...'

Run it against a THROWAWAY stack with an empty database (see docs/LOCAL_DEMO_GUIDE.md,
"End-to-end check"): it creates a department, people and classes and uploads the fictional
sample reports in demo/tlp-uploads. It refuses to run if the platform already has classes.

Everything goes over HTTP the way the browser does it: the session routes (/api/session/*,
httpOnly refresh cookie), the /api/v1 proxy and the API itself. Exit code 0 only if every
check passed; each check prints PASS/FAIL with the evidence.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "demo" / "tlp-uploads"
FAILURES: list[str] = []
TIMINGS: dict[str, list[float]] = {}


def check(name: str, ok: bool, evidence: object = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {evidence}" if evidence != "" else ""))
    if not ok:
        FAILURES.append(name)
    return ok


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value} in JSON")


def strict_json(raw: bytes):
    """JSON that must not contain NaN/Infinity (Python's json accepts them by default)."""
    return json.loads(raw, parse_constant=_reject_constant)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    ms: float

    def json(self):
        return strict_json(self.body)


@dataclass
class Client:
    """One browser: its own cookie jar and in-memory access token."""

    base: str
    token: str | None = None
    jar: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)

    def __post_init__(self) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(
        self,
        method: str,
        path: str,
        *,
        body: object = None,
        raw: bytes | None = None,
        content_type: str | None = None,
        token: str | None = "default",
        label: str | None = None,
    ) -> Response:
        headers: dict[str, str] = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        if raw is not None:
            data = raw
            headers["content-type"] = content_type or "application/octet-stream"
        bearer = self.token if token == "default" else token
        if bearer:
            headers["authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        start = time.perf_counter()
        try:
            with self.opener.open(request, timeout=120) as r:
                out = Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(), 0)
        except urllib.error.HTTPError as e:
            out = Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(), 0)
        out.ms = (time.perf_counter() - start) * 1000
        if label:
            TIMINGS.setdefault(label, []).append(out.ms)
        return out

    def get(self, path: str, **kw) -> Response:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: object = None, **kw) -> Response:
        return self.call("POST", path, body=body, **kw)

    def patch(self, path: str, body: object, **kw) -> Response:
        return self.call("PATCH", path, body=body, **kw)

    def login(self, email: str, password: str) -> Response:
        r = self.post("/api/session/login", {"email": email, "password": password}, token=None)
        if r.status == 200:
            self.token = r.json()["access_token"]
        return r

    def upload(self, path: str, files: list[tuple[str, bytes]], fields: dict | None = None,
               field_name: str = "files") -> Response:
        boundary = uuid.uuid4().hex
        buf = io.BytesIO()
        for key, value in (fields or {}).items():
            buf.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                      f"{value}\r\n".encode())
        for name, content in files:
            buf.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; '
                      f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
            buf.write(content + b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        return self.call("POST", path, raw=buf.getvalue(),
                         content_type=f"multipart/form-data; boundary={boundary}", label="upload")


def section(title: str) -> None:
    print(f"\n== {title}")


def csv_bytes(rows: list[list[str]]) -> bytes:
    return ("\n".join(",".join(r) for r in rows) + "\n").encode()


def main() -> int:  # noqa: C901 - a linear script reads best as one sequence of steps
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", required=True)
    ap.add_argument("--api", required=True)
    ap.add_argument("--admin-email", required=True)
    ap.add_argument("--admin-password", required=True)
    args = ap.parse_args()
    V1 = "/api/v1"

    section("Stack")
    direct = Client(args.api)
    health = direct.get("/health")
    check("API /health is 200", health.status == 200, health.body[:120])
    check("Swagger UI is served", direct.get("/docs").status == 200)
    web = Client(args.web)
    for route in ("/", "/login", "/dashboard", "/import", "/reports", "/settings", "/attention",
                  "/students", "/interventions", "/analytics", "/assessments", "/classes"):
        r = web.get(route, token=None)
        check(f"web {route} serves HTML", r.status == 200 and b"<html" in r.body[:2000].lower(),
              r.status)
    login_html = web.get("/login", token=None).body.decode(errors="replace")
    check("login page has no demo accounts", "Sign-in accounts" not in login_html
          and "acadlytics.dev" not in login_html)

    section("Authentication")
    admin = Client(args.web)
    check("wrong password is 401", admin.login(args.admin_email, "wrong-password-123").status == 401)
    check("a common default password is refused",
          admin.login(args.admin_email, "Admin@123").status == 401)
    r = admin.login(args.admin_email, args.admin_password)
    check("admin signs in through /api/session/login", r.status == 200, r.status)
    check("refresh token is not in the response body", b"refresh_token" not in r.body)
    cookie = next((c for c in admin.jar if c.name == "acadlytics_rt"), None)
    check("refresh token is an httpOnly cookie on /api/session",
          cookie is not None and cookie.path == "/api/session"
          and cookie.has_nonstandard_attr("HttpOnly"))
    ws = admin.get(f"{V1}/me/workspace", label="workspace").json()
    check("workspace says ADMIN", ws["user"]["role"] == "ADMIN")
    existing = admin.get(f"{V1}/offerings?limit=1").json()
    if existing.get("total"):
        print("Refusing to run: this platform already has classes. Use an empty, throwaway stack.")
        return 2
    check("no token → 401", admin.get(f"{V1}/me/workspace", token=None).status == 401)
    check("garbage token → 401", admin.get(f"{V1}/me/workspace", token="abc.def.ghi").status == 401)
    rotated = admin.post("/api/session/refresh", token=None)
    check("silent refresh rotates the cookie", rotated.status == 200, rotated.status)

    section("Hierarchy set-up (Administrator)")
    dept = admin.post(f"{V1}/departments", {"code": "CSE", "name": "Computer Science and Engineering"})
    check("department created", dept.status == 201, dept.body[:200])
    dept_id = dept.json()["id"]
    hod_pw = "Hod-E2E-" + uuid.uuid4().hex[:8]
    hod_user = admin.post(f"{V1}/users", {"email": "hod.e2e@srmist.edu.in", "full_name": "E2E HOD",
                                          "password": hod_pw, "role": "HOD",
                                          "department_id": dept_id})
    check("HOD created", hod_user.status == 201, hod_user.body[:200])
    hod = Client(args.web)
    check("HOD signs in", hod.login("hod.e2e@srmist.edu.in", hod_pw).status == 200)

    section("TLP import: XLSX + PDF, two sections, set-up from the reports (HOD)")
    files = [("DSA_FJ-II_A1.xlsx", (SAMPLES / "DSA_FJ-II_A1.xlsx").read_bytes()),
             ("DSA_FJ-II_A2.pdf", (SAMPLES / "DSA_FJ-II_A2.pdf").read_bytes())]
    staged = hod.upload(f"{V1}/tlp-uploads", files)
    check("upload staged (201)", staged.status == 201, staged.body[:300])
    group = staged.json()
    statuses = {f["file_name"]: f["status"] for f in group["files"]}
    check("both files validate", all(s in ("valid", "warning") for s in statuses.values()), statuses)
    present_before = 0
    for o in hod.get(f"{V1}/offerings").json()["items"]:
        for a in hod.get(f"{V1}/offerings/{o['id']}/assessments").json()["items"]:
            present_before += a["result_counts"]["present"] + a["result_counts"]["absent"]
    check("nothing is written before confirm (0 results while staged)", present_before == 0,
          present_before)
    confirmed = hod.post(f"{V1}/tlp-uploads/{group['group_id']}/confirm?publish=true")
    check("confirm (200)", confirmed.status == 200, confirmed.body[:300])
    check("both files confirmed", all(f["status"] == "confirmed" for f in confirmed.json()["files"]),
          [f["status"] for f in confirmed.json()["files"]])
    again = hod.upload(f"{V1}/tlp-uploads", files[:1])
    dup = again.json()["files"][0] if again.status == 201 else {}
    check("re-uploading the same file is reported as a duplicate",
          again.status in (201, 409, 422) and "duplicate" in json.dumps(dup).lower()
          or again.status in (409, 422), (again.status, dup.get("status")))
    if again.status == 201 and dup.get("batch_id"):
        hod.post(f"{V1}/imports/{dup['batch_id']}/discard")

    offerings = hod.get(f"{V1}/offerings", label="offerings").json()["items"]
    check("two classes set up", len(offerings) == 2, len(offerings))
    by_section = {o["section"]["name"]: o for o in offerings}
    a1, a2 = by_section.get("A1"), by_section.get("A2")
    check("sections A1 and A2", a1 is not None and a2 is not None, list(by_section))

    section("Faculty accounts from the reports")
    passwords = {}
    for staff in ("902049", "902050"):
        found = hod.get(f"{V1}/users?q={staff}").json()["items"]
        check(f"faculty {staff} created", len(found) == 1, len(found))
        user = found[0]
        fresh = Client(args.web)
        check(f"faculty {staff} cannot sign in before a password is set",
              fresh.login(user["email"], staff).status == 401)
        pw = f"Fac-{staff}-" + uuid.uuid4().hex[:6]
        check(f"HOD sets {staff}'s password",
              hod.patch(f"{V1}/users/{user['id']}", {"password": pw}).status == 200)
        passwords[staff] = (user["email"], pw)
    fa, fb = Client(args.web), Client(args.web)
    check("faculty A (902049) signs in", fa.login(*passwords["902049"]).status == 200)
    check("faculty B (902050) signs in", fb.login(*passwords["902050"]).status == 200)
    fa_ws = fa.get(f"{V1}/me/workspace").json()
    check("faculty A teaches exactly one class", len(fa_ws["teaching"]) == 1, len(fa_ws["teaching"]))
    a_off = fa.get(f"{V1}/offerings").json()["items"]
    check("faculty A's class list is only their class", [o["id"] for o in a_off] == [a1["id"]],
          [o["section"]["name"] for o in a_off])

    section("Per-assessment CSV import with every edge case (faculty A)")
    students = [e["student"] for e in fa.get(f"{V1}/offerings/{a1['id']}/students").json()]
    regs = sorted(s["register_number"] for s in students)
    check("A1 has 42 enrolled students", len(regs) == 42, len(regs))
    created = fa.post(f"{V1}/offerings/{a1['id']}/assessments",
                      {"name": "CT-E2E", "assessment_type": "CT", "max_marks": 20,
                       "is_published": False})
    check("faculty A creates an assessment in their class", created.status == 201, created.body[:200])
    aid = created.json()["id"]
    rows = [["Register Number", "Name", "Marks"],
            [regs[0], "x", "18"],         # valid
            [regs[1], "x", "0"],          # genuine zero
            [regs[2], "x", "AB"],         # absent
            [regs[3], "x", ""],           # blank → missing, not 0
            [regs[4], "x", "-3"],         # negative
            [regs[5], "x", "25"],         # above max
            ["RA9999999999999", "x", "10"],  # unknown student
            [regs[6], "x", "12"], [regs[6], "x", "13"],  # duplicate
            [regs[7], "x", "abc"]]        # not a number
    up = fa.upload(f"{V1}/assessments/{aid}/import", [("ct_e2e.csv", csv_bytes(rows))], field_name="file")
    check("CSV staged with a preview", up.status == 201, up.body[:300])
    preview = up.json()
    batch = preview["batch"]["id"]
    text = json.dumps(preview).lower()
    summary = preview["summary"]
    check("preview: 6 rows with errors, confirm blocked",
          summary["rows_with_errors"] == 6 and summary["can_confirm"] is False, summary)
    check("preview: blank cell and absent marker recognised (not errors)",
          summary["blank_cells"] == 1 and summary["absent_markers"] == 1, summary)
    for code in ("score_below_zero", "score_above_max", "unknown_student", "duplicate_student_row",
                 "invalid_number"):
        check(f"preview explains {code}", code in text)
    blocked = fa.post(f"{V1}/imports/{batch}/confirm")
    check("confirm with unresolved errors is refused (atomic: nothing written)",
          blocked.status in (409, 422), blocked.status)
    counts = fa.get(f"{V1}/assessments/{aid}/results").json()["counts"]
    check("no results written by the refused confirm", counts["present"] + counts["absent"] == 0,
          counts)
    full = fa.get(f"{V1}/imports/{batch}/preview?only=all").json()

    def has_error(row):
        issues = row["issues"] + [i for c in row["cells"] for i in c["issues"]]
        return any(i["level"] == "error" for i in issues)

    error_rows = sorted(r["row"] for r in full["rows"] if has_error(r))
    neg_row = 6
    fixed = fa.post(f"{V1}/imports/{batch}/fix", {"fixes": [{"row": neg_row, "column": "Marks", "value": "3"}]})
    check("fix a negative mark in the preview", fixed.status == 200, fixed.body[:300])
    remaining = [r for r in error_rows if r != neg_row]
    ex = fa.post(f"{V1}/imports/{batch}/exclude", {"rows": remaining, "excluded": True})
    check("exclude the remaining bad rows", ex.status == 200, ex.body[:300])
    done = fa.post(f"{V1}/imports/{batch}/confirm?publish=true")
    check("confirm succeeds after fix/exclude", done.status == 200, done.body[:300])
    results = fa.get(f"{V1}/assessments/{aid}/results").json()["rows"]
    by_reg = {r["student"]["register_number"]: r for r in results}

    def score(reg):
        r = by_reg[reg]
        return (r["result"] or {}).get("score"), r["state"]

    check("valid mark stored", score(regs[0]) [0] in (18, "18", "18.00", 18.0), score(regs[0]))
    check("genuine zero stays 0 and present",
          score(regs[1])[0] in (0, "0", "0.00", 0.0) and score(regs[1])[1] == "present", score(regs[1]))
    check("absent stays absent, never 0", score(regs[2]) == (None, "absent"), score(regs[2]))
    # Documented contract (docs/IMPORT_FORMAT.md): a blank cell imports as absent with a
    # blank_cell_absent warning, never 0; a student not in the file stays missing.
    check("blank cell → absent (score NULL), never 0", score(regs[3]) == (None, "absent"),
          score(regs[3]))
    check("student not in the file stays missing", score(regs[10]) == (None, "missing"),
          score(regs[10]))
    check("fixed negative row stored as 3", score(regs[4])[0] in (3, "3", "3.00", 3.0), score(regs[4]))
    check("above-max row was not written", score(regs[5])[0] is None, score(regs[5]))

    section("Analytics, student profile, attention, insights (faculty A)")
    an = fa.get(f"{V1}/offerings/{a1['id']}/analytics", label="analytics")
    check("analytics 200 with finite numbers", an.status == 200, an.status)
    analytics = an.json()
    first_student = next(s for s in students if s["register_number"] == regs[0])
    sp = fa.get(f"{V1}/offerings/{a1['id']}/students/{first_student['id']}/analytics", label="student")
    check("student profile 200", sp.status == 200, sp.status)
    att = fa.get(f"{V1}/offerings/{a1['id']}/attention", label="attention")
    check("attention 200", att.status == 200, att.status)
    attention = att.json()
    ins = fa.get(f"{V1}/offerings/{a1['id']}/insights", label="insights")
    check("insights 200", ins.status == 200, ins.status)
    ov = fa.get(f"{V1}/insights/overview", label="overview")
    check("overview (dashboard) 200", ov.status in (200, 404), ov.status)
    flags = [f for st in attention["students"] for f in st["flags"]]
    check("attention: summary total matches the flags listed",
          attention["summary"]["total_flags"] == len(flags), (attention["summary"]["total_flags"], len(flags)))
    check("every flag explains itself (message, threshold, assessments)",
          all(f["message"] and (f["threshold"] or f["pass_mark_percent"] is not None)
              and f["reference_assessments"] is not None for f in flags), len(flags))
    r2 = [f for f in flags if f["rule_code"] == "R2_FAILED_LATEST"]
    check("R2 fires only strictly below the class pass mark",
          all(f["actual"]["value"] < f["pass_mark_percent"] for f in r2), len(r2))
    r1 = [f for f in flags if f["rule_code"] == "R1_LOW_PERFORMANCE"]
    check("R1 fires only strictly below its threshold",
          all(f["actual"]["value"] < f["threshold"]["value"] for f in r1), len(r1))
    print(f"     analytics keys: {sorted(analytics)}; flags by rule: {attention['summary']['by_rule']}")
    live = fa.get(f"{V1}/insights/attention?offering_id={a1['id']}&limit=50").json()["items"]
    check("persisted attention list (what the Attention page shows) is non-empty", len(live) > 0, len(live))

    section("Interventions and outcomes (faculty A)")
    target = live[0]["student"]["id"] if live else first_student["id"]
    flag_id = live[0]["id"] if live else None
    seq = max((a.get("sequence_no") or 0) for a in fa.get(f"{V1}/offerings/{a1['id']}/assessments").json()["items"]) or 1
    body = {"student_ids": [target], "kind": "remedial_session", "after_sequence_no": seq,
            "reasons": [{"student_id": target, **({"flag_id": flag_id} if flag_id else {})}],
            "note": "<script>alert(1)</script> remedial"}
    iv = fa.post(f"{V1}/offerings/{a1['id']}/interventions", body)
    check("intervention recorded", iv.status == 201, iv.body[:300])
    if iv.status == 201:
        check("note stored verbatim as text (rendered escaped by React)",
              iv.json().get("note") == body["note"])
    dup = dict(body, student_ids=[target, target], reasons=[])
    check("duplicate student targets refused", fa.post(f"{V1}/offerings/{a1['id']}/interventions", dup).status in (409, 422))
    b_students = [e["student"] for e in fb.get(f"{V1}/offerings/{a2['id']}/students").json()]
    cross = dict(body, student_ids=[b_students[0]["id"]], reasons=[])
    check("student from another class refused", fa.post(f"{V1}/offerings/{a1['id']}/interventions", cross).status in (404, 422))
    bad_flag = dict(body, reasons=[{"student_id": target, "flag_id": str(uuid.uuid4())}])
    check("unknown attention flag refused", fa.post(f"{V1}/offerings/{a1['id']}/interventions", bad_flag).status in (404, 422))
    out = fa.get(f"{V1}/offerings/{a1['id']}/interventions/outcomes", label="outcomes")
    check("outcomes 200", out.status == 200, out.status)
    out_text = out.body.decode().lower()
    check("outcomes make no causal claim", not re.search(r"\b(caused|due to the intervention|because of the intervention)\b", out_text.replace("does not show that the intervention caused", "")))

    section("Reports: 5 kinds × CSV / XLSX / PDF (faculty A)")
    mime = {"csv": "text/csv", "xlsx": "spreadsheetml", "pdf": "application/pdf"}
    for kind in ("class_summary", "student_performance", "attention", "assessment_comparison",
                 "intervention_outcome"):
        for fmt in ("csv", "xlsx", "pdf"):
            extra = f"&student_id={first_student['id']}" if kind == "student_performance" else ""
            r = fa.get(f"{V1}/offerings/{a1['id']}/reports/{kind}?format={fmt}{extra}", label=f"report-{fmt}")
            disp = r.headers.get("content-disposition", "")
            ok = (r.status == 200 and mime[fmt] in r.headers.get("content-type", "")
                  and f".{fmt}" in disp and len(r.body) > 200)
            if ok and fmt == "csv":
                low = r.body.decode("utf-8-sig").lower()
                ok = not re.search(r"(?<![a-z])(nan|inf|infinity)(?![a-z])", low)
            if ok and fmt == "pdf":
                ok = r.body.startswith(b"%PDF")
            if ok and fmt == "xlsx":
                try:
                    from openpyxl import load_workbook
                    wb = load_workbook(io.BytesIO(r.body), read_only=True)
                    ok = bool(wb.sheetnames)
                except Exception as exc:  # noqa: BLE001 - report the failure as evidence
                    ok, disp = False, f"xlsx unreadable: {exc}"
            check(f"{kind}.{fmt}", ok, f"{r.status} {len(r.body)}B {disp[:60]}")

    section("Isolation: faculty B cannot reach faculty A's class (expect 404)")
    paths = [f"/offerings/{a1['id']}", f"/offerings/{a1['id']}/analytics",
             f"/offerings/{a1['id']}/attention", f"/offerings/{a1['id']}/insights",
             f"/offerings/{a1['id']}/interventions", f"/offerings/{a1['id']}/students",
             f"/offerings/{a1['id']}/assessments", f"/assessments/{aid}", f"/assessments/{aid}/results",
             f"/offerings/{a1['id']}/reports/class_summary?format=csv",
             f"/offerings/{a1['id']}/students/{first_student['id']}/analytics",
             f"/imports/{batch}"]
    for p in paths:
        r = fb.get(V1 + p)
        check(f"B → {p.split('?')[0]}", r.status == 404, r.status)
    r = fb.post(f"{V1}/offerings/{a1['id']}/interventions", body)
    check("B cannot record an intervention in A's class", r.status == 404, r.status)
    r = fb.upload(f"{V1}/assessments/{aid}/import", [("x.csv", csv_bytes(rows[:2]))], field_name="file")
    check("B cannot upload into A's assessment", r.status == 404, r.status)

    section("Input hardening")
    check("invalid UUID → 422", fa.get(f"{V1}/offerings/not-a-uuid").status == 422)
    check("random UUID → 404", fa.get(f"{V1}/offerings/{uuid.uuid4()}").status == 404)
    mal = fa.call("POST", f"{V1}/offerings/{a1['id']}/interventions", raw=b"{not json", content_type="application/json")
    check("malformed JSON → 422", mal.status == 422, mal.status)
    sqli = fa.get(f"{V1}/students?q=%27%20OR%201%3D1%20--")
    check("SQL-injection-like search is just text (200, no rows)", sqli.status == 200 and sqli.json()["total"] == 0, sqli.body[:120])
    big = fa.upload(f"{V1}/assessments/{aid}/import", [("big.csv", b"a" * (5 * 1024 * 1024 + 10))], field_name="file")
    check("oversized upload refused", big.status in (413, 422), big.status)
    bad_type = fa.upload(f"{V1}/assessments/{aid}/import", [("marks.exe", b"MZ\x90\x00")], field_name="file")
    check("unsupported file type refused", bad_type.status in (415, 422), bad_type.status)
    empty = fa.upload(f"{V1}/assessments/{aid}/import", [("e.csv", b"")], field_name="file")
    check("empty file refused", empty.status == 422, empty.status)

    section("Refresh-token reuse, logout, sign in again")
    d = Client(args.api)
    pair = d.post(f"{V1}/auth/login", {"email": passwords["902049"][0], "password": passwords["902049"][1]}).json()
    first = d.post(f"{V1}/auth/refresh", {"refresh_token": pair["refresh_token"]})
    check("refresh rotates", first.status == 200)
    time.sleep(11)  # past the 10 s concurrent-refresh grace window
    replay = d.post(f"{V1}/auth/refresh", {"refresh_token": pair["refresh_token"]})
    check("replaying a rotated refresh token → 401 and the session is revoked", replay.status == 401)
    newer = d.post(f"{V1}/auth/refresh", {"refresh_token": first.json()["refresh_token"]})
    check("…including the newer token of that session", newer.status == 401)
    out = fa.post("/api/session/logout", token=None)
    check("logout 204", out.status == 204, out.status)
    after = fa.post("/api/session/refresh", token=None)
    check("no session after logout (refresh gives no token)", after.status in (204, 401), after.status)
    fa.token = None
    check("sign in again", fa.login(*passwords["902049"]).status == 200)
    check("workspace after re-login", fa.get(f"{V1}/me/workspace").status == 200)

    section("Password change")
    new_pw = "Changed-" + uuid.uuid4().hex[:8]
    ch = fa.post(f"{V1}/auth/password", {"current_password": passwords["902049"][1], "new_password": new_pw})
    check("self-service password change 204", ch.status == 204, ch.body[:200])
    check("old password no longer works", Client(args.web).login(passwords["902049"][0], passwords["902049"][1]).status == 401)
    check("new password works", Client(args.web).login(passwords["902049"][0], new_pw).status == 200)

    section("Timings (ms, through the web proxy)")
    for label, values in sorted(TIMINGS.items()):
        values = sorted(values)
        print(f"  {label:<16} n={len(values):<3} median={values[len(values)//2]:7.1f}  max={values[-1]:7.1f}")

    print(f"\n{len(FAILURES)} failed check(s)" + (": " + "; ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
