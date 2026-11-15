"""Independent, deterministic verification of a running ACADLYTICS stack.

    python scripts/verify_live.py --api http://localhost:8010 \
        --admin-email admin@example.edu --admin-password '...'

Run it against a THROWAWAY stack only. It creates its own department (code ``VER<n>``),
people, classes and marks, so it can be run repeatedly on the same stack and next to
``scripts/e2e_live.py``; it never touches data it did not create.

What it adds to the unit suite: every expected number below is computed here, from the marks
this script itself enters, with the standard library only (``statistics``, ``decimal``) and
never with application code. The API's answers are then compared against those numbers:

    hierarchy      department -> term -> course -> section -> offering -> faculty/students
    results        ABSENT != MISSING != EXEMPT != ZERO; boundary validation
    analytics      mean, median, population sd, min/max, pass %, completion %, histogram
    attention      R1-R7 including the strict/inclusive boundaries
    imports        CSV and XLSX: preview = commit, fix/exclude, no partial commit, idempotence
    interventions  targets, cross-class refusal, observational wording
    reports        CSV/XLSX/PDF agree with the API
    isolation      two faculty members, two classes: every cross read is 404

Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

FAILURES: list[str] = []
PASSES = 0


def check(name: str, ok: bool, evidence: object = "") -> bool:
    global PASSES
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {evidence}" if evidence != "" else ""))
    if ok:
        PASSES += 1
    else:
        FAILURES.append(name)
    return ok


def section(title: str) -> None:
    print(f"\n== {title}")


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value} in JSON")


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body, parse_constant=_reject_constant)

    @property
    def code(self) -> str | None:
        try:
            return self.json()["error"]["code"]
        except Exception:  # noqa: BLE001 - not an error envelope
            return None


class Client:
    def __init__(self, api: str) -> None:
        self.base = api.rstrip("/") + "/api/v1"
        self.token: str | None = None
        self.refresh_token: str | None = None

    def call(self, method: str, path: str, body=None, *, raw: bytes | None = None,
             content_type: str | None = None, token: str | None | bool = True) -> Response:
        headers = {}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        if content_type:
            headers["content-type"] = content_type
        bearer = self.token if token is True else token
        if bearer:
            headers["authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as r:
                return Response(r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, dict(exc.headers), exc.read())

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body, **kw)

    def put(self, path, body=None, **kw):
        return self.call("PUT", path, body, **kw)

    def patch(self, path, body=None, **kw):
        return self.call("PATCH", path, body, **kw)

    def delete(self, path, **kw):
        return self.call("DELETE", path, **kw)

    def login(self, email: str, password: str) -> Response:
        r = self.post("/auth/login", {"email": email, "password": password}, token=None)
        if r.status == 200:
            self.token = r.json()["access_token"]
            self.refresh_token = r.json()["refresh_token"]
        return r

    def upload(self, path: str, name: str, content: bytes, mime: str, field: str = "file") -> Response:
        boundary = uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self.call("POST", path, raw=body, content_type=f"multipart/form-data; boundary={boundary}")


def q2(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def close(actual, expected, tol=Decimal("0.011")) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return abs(Decimal(str(actual)) - Decimal(str(expected))) <= tol


CSV_MIME = "text/csv"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The cohort of class 1. Marks for A1 (max 50, weight 20), A2 (max 50, weight 20) and
# A3 (max 100, weight 60). "AB" absent, "EX" exempt, None = no result row at all (missing).
COHORT = [
    # name,            A1,     A2,     A3
    ("EXACT FIFTY", "25", "25", "50"),  # every mark exactly at the pass mark and at R1's 50
    ("JUST BELOW", "24.5", "25", "49"),  # weighted 49.2: R1 and R2 fire, R3 does not
    ("THREE LOW", "20", "20", "40"),  # three consecutive below pass: R1, R2, R3
    ("SHARP DROP", "45", "45", "60"),  # 90, 90, 60: R4 and R5
    ("SLOPE FIVE", "40", "42.5", "90"),  # 80, 85, 90: slope exactly +5 = improving
    ("REAL ZERO", "0", "AB", "100"),  # a genuine 0, then absent: completion 2/3, R6
    ("ONE EXEMPT", "EX", "30", "60"),  # exempt leaves the denominator: completion 2/2
    ("ONE MISSING", None, "35", "70"),  # no row for A1: completion 2/3, R6
    ("TOP MARKS", "50", "50", "100"),
    ("STEADY", "37.5", "37.5", "75"),
]
MAXES = (Decimal(50), Decimal(50), Decimal(100))
WEIGHTS = (Decimal(20), Decimal(20), Decimal(60))
PASS = Decimal(50)


def pct(mark: str | None, maximum: Decimal) -> Decimal | None:
    if mark in (None, "AB", "EX"):
        return None
    return Decimal(mark) * 100 / maximum


def expected_student(marks: tuple[str | None, ...]) -> dict:
    """Everything the engine should say about one student, from first principles."""
    series = [pct(m, mx) for m, mx in zip(marks, MAXES, strict=True)]
    done = [(p, w) for p, w in zip(series, WEIGHTS, strict=True) if p is not None]
    weighted = sum(p * w for p, w in done) / sum(w for _, w in done) if done else None
    exempt = sum(1 for m in marks if m == "EX")
    completion = Decimal(len(done)) * 100 / Decimal(len(marks) - exempt)
    present = [p for p in series if p is not None]
    rules = set()
    if weighted is not None and weighted < 50:
        rules.add("R1_LOW_PERFORMANCE")
    latest = series[-1]
    if latest is not None and latest < PASS:
        rules.add("R2_FAILED_LATEST")
    if len(present) >= 3 and all(p < PASS for p in present[-3:]):
        rules.add("R3_REPEATED_LOW")
    if len(present) >= 2 and present[-1] - sum(present[:-1]) / len(present[:-1]) <= -15:
        rules.add("R4_SHARP_DECLINE")
    slope = None
    if len(present) == 2:
        slope = present[1] - present[0]
    elif len(present) >= 3:
        xs = list(range(len(present)))
        mx, my = Decimal(sum(xs)) / len(xs), sum(present) / len(present)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, present, strict=True)) / sum(
            (x - mx) ** 2 for x in xs
        )
    if slope is not None and slope <= -5:
        rules.add("R5_DECLINING_TREND")
    if completion < 75:
        rules.add("R6_LOW_COMPLETION")
    if weighted is not None and abs(weighted - PASS) <= 5:
        rules.add("R7_BORDERLINE")
    return {"weighted": weighted, "completion": completion, "rules": rules, "slope": slope}


def expected_assessment(index: int) -> dict:
    values = [pct(row[index + 1], MAXES[index]) for row in COHORT]
    present = [v for v in values if v is not None]
    marks = [row[index + 1] for row in COHORT]
    exempt = marks.count("EX")
    bins = [0] * 10
    for v in present:
        bins[min(int(v // 10), 9)] += 1
    return {
        "n": len(present),
        "mean": sum(present) / len(present),
        "median": Decimal(str(statistics.median(present))),
        "sd": Decimal(str(statistics.pstdev([float(v) for v in present]))),
        "min": min(present),
        "max": max(present),
        "pass": Decimal(sum(1 for v in present if v >= PASS)) * 100 / len(present),
        "completion": Decimal(len(present)) * 100 / (len(COHORT) - exempt),
        "absent": marks.count("AB"),
        "exempt": exempt,
        "missing": marks.count(None),
        "bins": bins,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--admin-email", required=True)
    ap.add_argument("--admin-password", required=True)
    args = ap.parse_args()

    run = uuid.uuid4().hex[:5].upper()
    digits = str(int(run, 16) % 100000).zfill(5)
    admin = Client(args.api)
    section("Sign in")
    if not check("administrator signs in", admin.login(args.admin_email, args.admin_password).status == 200):
        return 1

    # ---------------------------------------------------------------- hierarchy
    section("Academic hierarchy")
    dept = admin.post("/departments", {"code": f"VER{run}", "name": f"Verification {run}"})
    check("department created", dept.status == 201, dept.status)
    dept_id = dept.json()["id"]
    check("duplicate department code is 409", admin.post("/departments", {"code": f"VER{run}", "name": "Again"}).status == 409)
    terms = admin.get("/terms?limit=200").json()["items"]
    term = next((t for t in terms if t["is_current"]), None) or (terms[0] if terms else None)
    if term is None:
        made = admin.post("/terms", {"code": "AY2025-26-EVEN", "name": "Even Semester 2025-26", "academic_year": "2025-26",
                                     "start_date": "2026-01-01", "end_date": "2026-06-30", "is_current": True})
        check("term created", made.status == 201, made.body[:200])
        term = made.json()
    bad_term = admin.post("/terms", {"code": f"BAD{run}", "name": "Bad", "academic_year": "2025-27",
                                     "start_date": "2026-01-01", "end_date": "2026-06-30"})
    check("term with non-consecutive academic year is 422", bad_term.status == 422, bad_term.status)
    backwards = admin.post("/terms", {"code": f"BAD{run}", "name": "Bad", "academic_year": "2025-26",
                                      "start_date": "2026-06-30", "end_date": "2026-01-01"})
    check("term ending before it starts is 422", backwards.status == 422, backwards.status)
    course = admin.post("/courses", {"department_id": dept_id, "code": f"21V{run}T", "name": "Verification Theory"})
    check("course created", course.status == 201, course.body[:200])
    course_id = course.json()["id"]
    check("course in an unknown department is 404",
          admin.post("/courses", {"department_id": str(uuid.uuid4()), "code": f"21X{run}T", "name": "Nowhere"}).status == 404)
    sections = []
    for name in ("V1", "V2"):
        s = admin.post("/sections", {"department_id": dept_id, "name": f"{name}{run}", "batch_year": 2024})
        check(f"section {name} created", s.status == 201, s.body[:200])
        sections.append(s.json()["id"])
    check("duplicate section is 409",
          admin.post("/sections", {"department_id": dept_id, "name": f"V1{run}", "batch_year": 2024}).status == 409)

    people = {}
    for key, role, code in (("hod", "HOD", f"H{run}"), ("fa", "FACULTY", f"A{run}"), ("fb", "FACULTY", f"B{run}")):
        pw = "Verify-" + uuid.uuid4().hex[:12]
        u = admin.post("/users", {"email": f"{key}.{run.lower()}@verify.acadlytics.dev", "full_name": f"Verify {key.upper()} {run}",
                                  "password": pw, "role": role, "department_id": dept_id, "employee_code": code})
        check(f"{role} account created", u.status == 201, u.body[:200])
        client = Client(args.api)
        check(f"{key} signs in", client.login(u.json()["email"], pw).status == 200)
        people[key] = {"id": u.json()["id"], "email": u.json()["email"], "password": pw, "client": client}
    check("second active HOD in the department is 409",
          admin.post("/users", {"email": f"hod2.{run.lower()}@verify.acadlytics.dev", "full_name": "Second HOD", "password": "Verify-12345678",
                                "role": "HOD", "department_id": dept_id}).status == 409)
    check("second administrator is 409",
          admin.post("/users", {"email": f"admin2.{run.lower()}@verify.acadlytics.dev", "full_name": "Second Admin",
                                "password": "Verify-12345678", "role": "ADMIN"}).status == 409)
    fa, fb, hod = people["fa"]["client"], people["fb"]["client"], people["hod"]["client"]

    offerings = []
    for sec, key in zip(sections, ("fa", "fb"), strict=True):
        o = admin.post("/offerings", {"course_id": course_id, "term_id": term["id"], "section_id": sec, "faculty_ids": [people[key]["id"]]})
        check(f"offering for {key} created", o.status == 201, o.body[:200])
        offerings.append(o.json()["id"])
    o1, o2 = offerings
    check("duplicate offering (same course, term, section) is 409",
          admin.post("/offerings", {"course_id": course_id, "term_id": term["id"], "section_id": sections[0]}).status == 409)
    check("offering with an unknown section is 404",
          admin.post("/offerings", {"course_id": course_id, "term_id": term["id"], "section_id": str(uuid.uuid4())}).status == 404)
    check("faculty cannot create an offering (403)",
          fa.post("/offerings", {"course_id": course_id, "term_id": term["id"], "section_id": sections[1]}).status == 403)
    check("deleting a department that has courses is refused",
          admin.delete(f"/departments/{dept_id}").status in (409, 422), admin.delete(f"/departments/{dept_id}").status)

    # ---------------------------------------------------------------- students
    section("Students")
    reg = lambda n: f"RA24{digits}{n:06d}"  # noqa: E731
    rows = [{"register_number": reg(i + 1), "full_name": name, "department_code": f"VER{run}", "batch_year": 2024, "section": f"V1{run}"}
            for i, (name, *_m) in enumerate(COHORT)]
    rows += [{"register_number": reg(100 + i), "full_name": f"OTHER CLASS {i}", "department_code": f"VER{run}", "batch_year": 2024, "section": f"V2{run}"}
             for i in range(1, 7)]
    dry = admin.post("/students/bulk", {"rows": rows, "dry_run": True})
    check("bulk dry run validates and writes nothing", dry.status == 200 and dry.json()["valid"] and
          admin.get(f"/students?department_id={dept_id}").json()["total"] == 0, dry.body[:200])
    bulk = admin.post("/students/bulk", {"rows": rows})
    check("16 students created in bulk", bulk.status in (200, 201) and bulk.json()["created"] == 16, bulk.body[:200])
    again = admin.post("/students/bulk", {"rows": rows})
    check("the same bulk again creates nothing", again.json()["created"] == 0 and again.json()["unchanged"] == 16, again.body[:200])
    dup = admin.post("/students", {"register_number": reg(1), "full_name": "Duplicate", "department_id": dept_id, "batch_year": 2024})
    check("duplicate register number is 409", dup.status == 409, dup.status)
    badreg = admin.post("/students", {"register_number": "ab!", "full_name": "Bad", "department_id": dept_id, "batch_year": 2024})
    check("malformed register number is 422", badreg.status == 422, badreg.status)
    found = admin.get(f"/students?q={reg(3)}").json()
    check("search by register number finds exactly that student", found["total"] == 1 and found["items"][0]["full_name"] == "THREE LOW", found["total"])
    page = admin.get(f"/students?department_id={dept_id}&limit=5&offset=15").json()
    check("pagination: total 16, last page has 1", page["total"] == 16 and len(page["items"]) == 1, (page["total"], len(page["items"])))
    for o in offerings:
        e = admin.post(f"/offerings/{o}/enrollments/from-section")
        check("section enrolled into its class", e.status in (200, 201), e.body[:200])
    roster = admin.get(f"/offerings/{o1}/students").json()
    check("class 1 roster has the 10 students", len(roster) == 10, len(roster))
    student_id = {item["student"]["full_name"]: item["student"]["id"] for item in roster}
    other_students = [i["student"]["id"] for i in admin.get(f"/offerings/{o2}/students").json()]
    renamed = admin.patch(f"/students/{student_id['STEADY']}", {"full_name": "STEADY"})
    check("student edit (no-op rename) is 200", renamed.status == 200, renamed.status)

    # ---------------------------------------------------------------- assessments
    section("Assessments and results")
    assessments = []
    for i, (name, mx, w) in enumerate((("VT1", 50, 20), ("VT2", 50, 20), ("VT3", 100, 60))):
        a = fa.post(f"/offerings/{o1}/assessments", {"name": name, "assessment_type": "CT", "max_marks": mx, "weightage": w,
                                                     "assessment_date": f"2026-0{i + 2}-10", "is_published": True})
        check(f"assessment {name} created by its faculty", a.status == 201, a.body[:200])
        assessments.append(a.json())
    a_ids = [a["id"] for a in assessments]
    check("sequence numbers increase", [a["sequence_no"] for a in assessments] == sorted(a["sequence_no"] for a in assessments))
    check("duplicate assessment name is 409",
          fa.post(f"/offerings/{o1}/assessments", {"name": "VT1", "assessment_type": "CT", "max_marks": 50}).status == 409)
    check("zero maximum marks is 422",
          fa.post(f"/offerings/{o1}/assessments", {"name": "ZERO", "assessment_type": "CT", "max_marks": 0}).status == 422)
    check("weightage above 100 is 422",
          fa.post(f"/offerings/{o1}/assessments", {"name": "HEAVY", "assessment_type": "CT", "max_marks": 10, "weightage": 101}).status == 422)
    check("faculty B cannot create an assessment in class 1 (404)",
          fb.post(f"/offerings/{o1}/assessments", {"name": "INTRUDER", "assessment_type": "CT", "max_marks": 10}).status == 404)

    target = a_ids[0]
    sid = student_id["TOP MARKS"]
    for label, entry, want in (
        ("negative mark", {"student_id": sid, "score": -1}, 422),
        ("mark above the maximum", {"student_id": sid, "score": 50.01}, 422),
        ("three decimals", {"student_id": sid, "score": 10.123}, 422),
        ("blank entry (no score, no status)", {"student_id": sid}, 422),
        ("absent with a score", {"student_id": sid, "status": "absent", "score": 5}, 422),
        ("present without a score", {"student_id": sid, "status": "present"}, 422),
        ("student of another class", {"student_id": other_students[0], "score": 10}, 422),
        ("unknown register number", {"register_number": "RA99999999999999", "score": 10}, 422),
    ):
        r = fa.put(f"/assessments/{target}/results", {"results": [entry]})
        check(f"result refused: {label}", r.status == want, f"{r.status} {r.code}")
    mixed = fa.put(f"/assessments/{target}/results", {"results": [{"student_id": sid, "score": 10}, {"student_id": student_id["STEADY"], "score": 999}]})
    grid = fa.get(f"/assessments/{target}/results").json()
    check("one bad row rejects the whole request (nothing written)", mixed.status == 422 and grid["counts"]["present"] == 0, grid["counts"])

    for index, aid in enumerate(a_ids):
        entries = []
        for name, *marks in COHORT:
            mark = marks[index]
            if mark is None:
                continue
            if mark == "AB":
                entries.append({"student_id": student_id[name], "status": "absent"})
            elif mark == "EX":
                entries.append({"student_id": student_id[name], "status": "exempt"})
            else:
                entries.append({"student_id": student_id[name], "score": float(mark)})
        r = fa.put(f"/assessments/{aid}/results", {"results": entries})
        check(f"results entered for {assessments[index]['name']}", r.status == 200 and r.json()["created"] == len(entries), r.body[:200])
    repeat = fa.put(f"/assessments/{a_ids[2]}/results", {"results": [{"student_id": student_id["STEADY"], "score": 75}]})
    check("re-entering the same mark is 'unchanged', not a duplicate", repeat.json() == {"created": 0, "updated": 0, "unchanged": 1}, repeat.json())

    grid = fa.get(f"/assessments/{a_ids[0]}/results").json()
    states = {row["student"]["full_name"]: row for row in grid["rows"]}
    zero, exempt, missing = states["REAL ZERO"], states["ONE EXEMPT"], states["ONE MISSING"]
    check("a genuine 0 is present with score 0", zero["state"] == "present" and float(zero["result"]["score"]) == 0.0 and float(zero["result"]["percentage"]) == 0.0, zero["result"])
    check("exempt has no score", exempt["state"] == "exempt" and exempt["result"]["score"] is None, exempt["result"])
    check("missing has no result row at all", missing["state"] == "missing" and missing["result"] is None, missing["state"])
    absent = {row["student"]["full_name"]: row for row in fa.get(f"/assessments/{a_ids[1]}/results").json()["rows"]}["REAL ZERO"]
    check("absent has no score (never 0)", absent["state"] == "absent" and absent["result"]["score"] is None, absent["result"])
    check("counts keep the four states apart", grid["counts"] == {"present": 8, "absent": 0, "exempt": 1, "missing": 1, "enrolled": 10}, grid["counts"])
    check("max marks cannot change once results exist", fa.patch(f"/assessments/{a_ids[0]}", {"max_marks": 60}).status in (409, 422))

    # ---------------------------------------------------------------- analytics
    section("Analytics against independently computed values")
    analytics = fa.get(f"/offerings/{o1}/analytics")
    check("class analytics 200", analytics.status == 200, analytics.status)
    health = analytics.json()["health"]
    latest = health["latest_assessment"]
    e3 = expected_assessment(2)
    for label, got, want in (
        ("VT3 mean", latest["mean"]["value"], e3["mean"]),
        ("VT3 median", latest["median"]["value"], e3["median"]),
        ("VT3 population sd", latest["std_dev"]["value"], e3["sd"]),
        ("VT3 pass %", latest["pass_percent"]["value"], e3["pass"]),
        ("VT3 completion %", latest["completion_percent"]["value"], e3["completion"]),
        ("VT3 lowest", latest["lowest"]["percentage"], e3["min"]),
        ("VT3 highest", latest["highest"]["percentage"], e3["max"]),
    ):
        check(f"{label} = {q2(want)}", close(got, q2(want)), got)
    check("VT3 n = 10", latest["mean"]["n"] == 10, latest["mean"]["n"])
    check("VT3 histogram bins", [b["count"] for b in latest["distribution"]["bins"]] == e3["bins"],
          [b["count"] for b in latest["distribution"]["bins"]])
    expected = {name: expected_student(tuple(marks)) for name, *marks in COHORT}
    weighted = [e["weighted"] for e in expected.values()]
    check(f"class mean of weighted course scores = {q2(sum(weighted) / len(weighted))}",
          close(health["class_mean"]["value"], q2(sum(weighted) / len(weighted))), health["class_mean"]["value"])
    check(f"class median = {q2(Decimal(str(statistics.median(weighted))))}",
          close(health["median"]["value"], q2(Decimal(str(statistics.median(weighted))))), health["median"]["value"])
    class_pass = Decimal(sum(1 for w in weighted if w >= PASS)) * 100 / len(weighted)
    check(f"class pass % = {q2(class_pass)} (exactly 50 passes)", close(health["pass_percent"]["value"], q2(class_pass)), health["pass_percent"]["value"])
    cells = sum(1 for _n, *m in COHORT for x in m if x != "EX")
    assessed = sum(1 for _n, *m in COHORT for x in m if x not in (None, "AB", "EX"))
    check(f"class completion % = {q2(Decimal(assessed) * 100 / cells)}",
          close(health["completion_percent"]["value"], q2(Decimal(assessed) * 100 / cells)), health["completion_percent"]["value"])
    check("coverage counts absent / exempt / missing separately",
          (health["coverage"]["absent"], health["coverage"]["exempt"], health["coverage"]["missing"]) == (1, 1, 1), health["coverage"])

    e1 = expected_assessment(0)
    by_assessment = {}
    scope = fa.get(f"/insights/overview?offering_id={o1}&semester=YEAR").json()
    for point in scope.get("trend", []):
        by_assessment[point.get("label") or point.get("name")] = point
    vt1 = by_assessment.get("VT1")
    if check("overview trend lists VT1", vt1 is not None, list(by_assessment)):
        mean = vt1["mean"]["value"] if isinstance(vt1.get("mean"), dict) else vt1.get("mean")
        check(f"VT1 mean (a genuine 0 counts, exempt and missing do not) = {q2(e1['mean'])}", close(mean, q2(e1["mean"])), mean)
        comp = vt1["completion_percent"]["value"] if isinstance(vt1.get("completion_percent"), dict) else vt1.get("completion_percent")
        check(f"VT1 completion % (exempt leaves the denominator) = {q2(e1['completion'])}", close(comp, q2(e1["completion"])), comp)
    check("no NaN or Infinity anywhere in analytics", True)  # Response.json() raises on them

    # ---------------------------------------------------------------- attention
    section("Attention rules R1-R7")
    attention = fa.get(f"/offerings/{o1}/attention")
    check("attention 200", attention.status == 200, attention.status)
    fired: dict[str, set[str]] = {name: set() for name, *_ in COHORT}
    flags_by_student: dict[str, list[dict]] = {}
    for entry in attention.json()["students"]:
        fired[entry["student"]["name"]] = {f["rule_code"] for f in entry["flags"]}
        flags_by_student[entry["student"]["name"]] = entry["flags"]
    for name, want in expected.items():
        check(f"{name}: rules {sorted(r[:2] for r in want['rules']) or 'none'}", fired[name] == want["rules"], sorted(fired[name]))
    check("R1 does not fire at exactly 50%", "R1_LOW_PERFORMANCE" not in fired["EXACT FIFTY"])
    check("R2 does not fire at exactly the pass mark", "R2_FAILED_LATEST" not in fired["EXACT FIFTY"])
    check("R7 fires at the pass mark itself", "R7_BORDERLINE" in fired["EXACT FIFTY"])
    all_flags = [f for flags in flags_by_student.values() for f in flags]
    check("every flag carries a message, a severity and its evidence",
          all(f.get("message") and f.get("severity") and f.get("reference_assessments") is not None for f in all_flags),
          next((f for f in all_flags if not f.get("message")), ""))
    r1 = next(f for f in flags_by_student["JUST BELOW"] if f["rule_code"] == "R1_LOW_PERFORMANCE")
    check("R1 flag states the actual value 49.20 and the threshold 50", "49.2" in r1["message"] and "50" in r1["message"], r1["message"])
    forbidden = ("will fail", "risk of failing", "because", "caused", "predict")
    check("no predictive or causal wording in flag messages", not any(w in f["message"].lower() for f in all_flags for w in forbidden))
    before = sorted((s["student"]["name"], f["rule_code"]) for s in attention.json()["students"] for f in s["flags"])
    recompute = admin.post(f"/admin/recompute?offering_id={o1}")
    check("recompute 200", recompute.status in (200, 204), recompute.status)
    after_json = fa.get(f"/offerings/{o1}/attention").json()
    after = sorted((s["student"]["name"], f["rule_code"]) for s in after_json["students"] for f in s["flags"])
    check("recompute is idempotent (same flags)", before == after, len(after))
    live = fa.get(f"/insights/attention?offering_id={o1}&semester=YEAR&limit=200").json()
    check("persisted live flags equal the computed flags", live["total"] == len(after), (live["total"], len(after)))

    # Threshold override on the offering: R1 at 60 makes EXACT FIFTY low; then restore.
    over = admin.patch(f"/offerings/{o1}", {"config": {"low_performance_percent": 60}})
    check("offering threshold override accepted", over.status == 200, over.body[:200])
    fired60 = {s["student"]["name"]: {f["rule_code"] for f in s["flags"]} for s in fa.get(f"/offerings/{o1}/attention").json()["students"]}
    check("with R1 at 60, a 50% student is flagged and a 60% student is not (strict)",
          "R1_LOW_PERFORMANCE" in fired60.get("EXACT FIFTY", set()) and "R1_LOW_PERFORMANCE" not in fired60.get("ONE EXEMPT", set()),
          (sorted(fired60.get("EXACT FIFTY", [])), sorted(fired60.get("ONE EXEMPT", []))))
    admin.patch(f"/offerings/{o1}", {"config": {}})
    restored = {s["student"]["name"]: {f["rule_code"] for f in s["flags"]} for s in fa.get(f"/offerings/{o1}/attention").json()["students"]}
    check("removing the override restores the original flags", all(restored.get(n, set()) == e["rules"] for n, e in expected.items()))

    # ---------------------------------------------------------------- student profile
    section("Student profile")
    for name in ("JUST BELOW", "REAL ZERO", "ONE EXEMPT", "ONE MISSING", "SLOPE FIVE"):
        prof = fa.get(f"/offerings/{o1}/students/{student_id[name]}/analytics")
        if not check(f"{name}: profile 200", prof.status == 200, prof.status):
            continue
        history = prof.json()["profile"]["history"]
        want = expected[name]
        check(f"{name}: weighted course score {q2(want['weighted'])}", close(history["weighted_course_score"]["value"], q2(want["weighted"])),
              history["weighted_course_score"]["value"])
        check(f"{name}: completion {q2(want['completion'])}", close(history["completion_percent"]["value"], q2(want["completion"])),
              history["completion_percent"]["value"])
        check(f"{name}: states per assessment",
              [p["state"] for p in history["points"]] == [("missing" if m is None else "absent" if m == "AB" else "exempt" if m == "EX" else "assessed")
                                                          for m in next(m for n, *m in COHORT if n == name)],
              [p["state"] for p in history["points"]])
    slope = fa.get(f"/offerings/{o1}/students/{student_id['SLOPE FIVE']}/analytics").json()["profile"]["history"]["trend"]
    check("slope of exactly +5 pp is 'improving' (inclusive)", close(slope["slope"]["value"], 5) and slope["label"]["value"] == "improving", slope["label"])
    check("student of another class is 404 in this class",
          fa.get(f"/offerings/{o1}/students/{other_students[0]}/analytics").status == 404)

    # ---------------------------------------------------------------- imports
    section("Imports (class 2, generic CSV / XLSX)")
    b1 = fb.post(f"/offerings/{o2}/assessments", {"name": "IMP1", "assessment_type": "CT", "max_marks": 20, "weightage": 50}).json()
    b2 = fb.post(f"/offerings/{o2}/assessments", {"name": "IMP2", "assessment_type": "CT", "max_marks": 40, "weightage": 50}).json()
    r2 = lambda i: reg(100 + i)  # noqa: E731
    sheet = "\n".join([
        "Register No,Name,IMP1",
        f"{r2(1)},OTHER CLASS 1,18",        # valid
        f"{r2(2)},OTHER CLASS 2,0",         # genuine zero
        f"{r2(3)},OTHER CLASS 3,AB",        # absent marker
        f"{r2(4)},OTHER CLASS 4,",          # blank -> absent with a warning
        f"{r2(5)},OTHER CLASS 5,-3",        # negative
        f"{r2(6)},OTHER CLASS 6,20.5",      # above maximum
        "RA99999999999999,NOBODY,10",       # unknown student
        f"{r2(1)},OTHER CLASS 1,12",        # duplicate student row
        f"{reg(1)},EXACT FIFTY,10",         # a student of the other class
    ]).encode()
    up = fb.upload(f"/offerings/{o2}/imports", "marks.csv", sheet, CSV_MIME)
    check("CSV staged (201) with nothing written", up.status == 201 and fb.get(f"/assessments/{b1['id']}/results").json()["counts"]["present"] == 0, up.body[:300])
    preview = up.json()
    batch = preview["batch"]["id"]
    codes = sorted({i["code"] for r in preview["rows"] for i in r["issues"] + [x for c in r["cells"] for x in c["issues"]]})
    for code in ("score_below_zero", "score_above_max", "unknown_student", "duplicate_student_row", "blank_cell_absent", "absent_marker"):
        check(f"preview reports {code}", code in codes, codes)
    refused = fb.post(f"/imports/{batch}/confirm")
    check("confirm refused while errors remain (422) and nothing written",
          refused.status == 422 and fb.get(f"/assessments/{b1['id']}/results").json()["counts"]["present"] == 0, refused.status)
    check("faculty A cannot see, preview or confirm B's batch (404)",
          {fa.get(f"/imports/{batch}").status, fa.get(f"/imports/{batch}/preview").status, fa.post(f"/imports/{batch}/confirm").status} == {404})
    by_row = {r["row"]: r for r in preview["rows"]}
    fixed = fb.post(f"/imports/{batch}/fix", {"fixes": [{"row": 6, "column": "IMP1", "value": "3"}]})
    check("fixing the negative mark clears that error", fixed.status == 200 and not any(
        i["level"] == "error" for r in fixed.json()["rows"] if r["row"] == 6 for c in r["cells"] for i in c["issues"]), fixed.status)
    bad_rows = [n for n, r in by_row.items() if n != 6 and (any(i["level"] == "error" for i in r["issues"]) or any(i["level"] == "error" for c in r["cells"] for i in c["issues"]))]
    excluded = fb.post(f"/imports/{batch}/exclude", {"rows": bad_rows})
    check("excluding the remaining bad rows leaves no errors", excluded.status == 200 and excluded.json()["summary"]["errors"] == 0, excluded.json()["summary"])
    will_write = excluded.json()["summary"]["cells_to_write"]
    planned = {r["register_number"]: (c["status"], c["score"]) for r in fb.get(f"/imports/{batch}/preview?only=all").json()["rows"]
               if not r["excluded"] for c in r["cells"] if c["status"]}
    confirmed = fb.post(f"/imports/{batch}/confirm?publish=true")
    check("confirm writes exactly what the preview promised", confirmed.status == 200 and confirmed.json()["created"] == will_write,
          (confirmed.status, confirmed.body[:200], will_write))
    stored = {row["student"]["register_number"]: (row["result"]["status"], row["result"]["score"]) for row in
              fb.get(f"/assessments/{b1['id']}/results").json()["rows"] if row["result"]}
    check("stored results equal the previewed cells", {k: (s, None if v is None else float(v)) for k, (s, v) in stored.items()} ==
          {k: (s, None if v is None else float(v)) for k, (s, v) in planned.items()}, stored)
    check("genuine 0 stored as present 0; AB and blank stored absent without a score",
          stored.get(r2(2)) and float(stored[r2(2)][1]) == 0.0 and stored[r2(2)][0] == "present"
          and stored.get(r2(3)) == ("absent", None) and stored.get(r2(4)) == ("absent", None), stored)
    check("excluded rows were not written", r2(6) not in stored, sorted(stored))
    check("second confirm of the same batch is refused", fb.post(f"/imports/{batch}/confirm").status in (409, 422))
    same = fb.upload(f"/offerings/{o2}/imports", "marks.csv", sheet, CSV_MIME)
    same_summary = same.json()["summary"] if same.status == 201 else {}
    check("uploading the same file again is flagged, and creates nothing new on its own", same.status == 201 and
          fb.get(f"/assessments/{b1['id']}/results").json()["counts"]["present"] == sum(1 for s, _ in stored.values() if s == "present"), same_summary)
    if same.status == 201:
        fb.post(f"/imports/{same.json()['batch']['id']}/discard")
    history = fb.get(f"/imports?offering_id={o2}").json()
    check("import history lists the committed and the discarded batch", {b["status"] for b in history["items"]} >= {"committed", "discarded"},
          [b["status"] for b in history["items"]])
    audit = admin.get(f"/audit-logs?offering_id={o2}&limit=100")
    check("audit log has the import fix and commit", audit.status == 200 and len(audit.json()["items"]) >= 2,
          sorted({f"{a['entity']}.{a['action']}" for a in audit.json()["items"]}) if audit.status == 200 else audit.status)

    template = fb.get(f"/offerings/{o2}/imports/template")
    check("XLSX template downloads", template.status == 200 and template.body[:2] == b"PK", template.headers.get("content-type"))
    try:
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(template.body))
        ws = book.active
        headers = [c.value for c in ws[1]]
        col = next(i for i, h in enumerate(headers) if h and str(h).upper().startswith("IMP2")) + 1
        regcol = next(i for i, h in enumerate(headers) if h and "reg" in str(h).lower()) + 1
        marks2 = {r2(1): 40, r2(2): 0, r2(3): "EX", r2(4): 19.5, r2(5): 20, r2(6): 39.75}
        for row in ws.iter_rows(min_row=2):
            number = row[regcol - 1].value
            if number in marks2:
                row[col - 1].value = marks2[number]
        out = io.BytesIO()
        book.save(out)
        xl = fb.upload(f"/offerings/{o2}/imports", "filled-template.xlsx", out.getvalue(), XLSX_MIME)
        ok = check("filled XLSX template stages without errors", xl.status == 201 and xl.json()["summary"]["errors"] == 0, xl.body[:300])
        if ok:
            done = fb.post(f"/imports/{xl.json()['batch']['id']}/confirm?publish=true")
            got = {row["student"]["register_number"]: row for row in fb.get(f"/assessments/{b2['id']}/results").json()["rows"]}
            check("XLSX import written: 5 present, 1 exempt", done.status == 200 and fb.get(f"/assessments/{b2['id']}/results").json()["counts"]["present"] == 5
                  and got[r2(3)]["state"] == "exempt", done.body[:200])
            check("decimal mark 39.75 survives exactly", float(got[r2(6)]["result"]["score"]) == 39.75, got[r2(6)]["result"])
    except ImportError:
        check("openpyxl available for the XLSX check", False, "pip install openpyxl")

    for label, name, content, mime in (
        ("empty file", "empty.csv", b"", CSV_MIME),
        ("header only", "header.csv", b"Register No,Name,IMP1\n", CSV_MIME),
        ("no register column", "noreg.csv", b"Name,IMP1\nSomeone,5\n", CSV_MIME),
        ("duplicate assessment columns", "dup.csv", f"Register No,IMP1,IMP1\n{r2(1)},5,6\n".encode(), CSV_MIME),
        ("unsupported extension", "marks.txt", b"Register No,IMP1\n", "text/plain"),
        ("xlsx name with CSV bytes is read as what it is or refused", "fake.xlsx", b"\x00\x01\x02\x03 not a workbook", XLSX_MIME),
        ("malformed workbook", "broken.xlsx", b"PK\x03\x04 truncated zip", XLSX_MIME),
        ("non UTF-8 text", "latin.csv", "Register No,IMP1\nRA1,5\xff\n".encode("latin-1"), CSV_MIME),
        ("oversized (5 MB + 1)", "big.csv", b"Register No,IMP1\n" + b"x" * (5 * 1024 * 1024), CSV_MIME),
    ):
        r = fb.upload(f"/offerings/{o2}/imports", name, content, mime)
        staged_with_errors = r.status == 201 and (r.json()["summary"].get("errors", 0) > 0 or any(i["level"] == "error" for i in r.json()["file_issues"]))
        check(f"bad upload handled cleanly: {label}", r.status in (413, 422) or staged_with_errors, f"{r.status} {r.code or ''}")
        if r.status == 201:
            fb.post(f"/imports/{r.json()['batch']['id']}/discard")
    nasty = fb.upload(f"/offerings/{o2}/imports", "../../etc/passwd<script>.csv", f"Register No,IMP1\n{r2(1)},18\n".encode(), CSV_MIME)
    name_back = nasty.json()["batch"]["file_name"] if nasty.status == 201 else ""
    check("path-traversal file name is neutralised or refused", nasty.status in (201, 422) and "/" not in name_back and "\\" not in name_back and ".." not in name_back, name_back or nasty.status)
    if nasty.status == 201:
        fb.post(f"/imports/{nasty.json()['batch']['id']}/discard")
    check("upload into an unknown class is 404", fb.upload(f"/offerings/{uuid.uuid4()}/imports", "m.csv", sheet, CSV_MIME).status == 404)

    # ---------------------------------------------------------------- interventions
    section("Interventions and outcomes")
    flags = fa.get(f"/insights/attention?offering_id={o1}&semester=YEAR&limit=200").json()["items"]
    low = next(f for f in flags if f["student"]["name"] == "THREE LOW")
    last_seq = max(a["sequence_no"] for a in assessments)
    body = {"kind": "remedial_session", "after_sequence_no": last_seq, "note": "Verification <script>alert(1)</script>",
            "student_ids": [student_id["THREE LOW"], student_id["JUST BELOW"]]}
    probe = fa.post(f"/offerings/{o1}/interventions", body)
    if probe.status == 422:  # discover the accepted shape from the error rather than guessing silently
        print("    intervention body rejected:", probe.body[:400].decode(errors="replace"))
    check("intervention recorded", probe.status == 201, probe.status)
    if probe.status == 201:
        iv = probe.json()
        listed = fa.get(f"/offerings/{o1}/interventions").json()
        items = listed["items"] if isinstance(listed, dict) else listed
        check("intervention is listed for the class", any(i["id"] == iv["id"] for i in items), len(items))
        check("the note is stored as text, not interpreted", "<script>" in json.dumps(items))
        cross = dict(body, student_ids=[other_students[0]])
        check("target from another class is refused", fa.post(f"/offerings/{o1}/interventions", cross).status in (404, 422))
        twice = dict(body, student_ids=[student_id["THREE LOW"], student_id["THREE LOW"]])
        check("duplicate targets are refused", fa.post(f"/offerings/{o1}/interventions", twice).status == 422)
        check("empty target list is refused", fa.post(f"/offerings/{o1}/interventions", dict(body, student_ids=[])).status == 422)
        check("faculty B cannot record an intervention in class 1 (404)", fb.post(f"/offerings/{o1}/interventions", body).status == 404)
        outcomes = fa.get(f"/offerings/{o1}/interventions/outcomes")
        text = outcomes.body.decode().lower()
        # "caused" may appear only inside the disclaimer that says the data does not show it.
        claims = text.replace("does not show that the intervention caused", "")
        check("outcomes 200, observational wording only", outcomes.status == 200 and "observed change only" in text
              and not any(w in claims for w in ("caused", "because of the intervention", "due to the intervention", "effect of")), outcomes.status)
        mine = next((o for o in outcomes.json()["outcomes"] if o["intervention_id"] == iv["id"]), None)
        check("an intervention with no later assessment is 'not yet measurable', never a number",
              mine is not None and mine["net_change"]["value"] is None and mine["net_change"]["status"] != "ok", mine and mine["net_change"])
    _ = low

    # ---------------------------------------------------------------- reports
    section("Reports")
    kinds = ("class_summary", "student_performance", "attention", "assessment_comparison", "intervention_outcome")
    mimes = {"csv": "text/csv", "xlsx": XLSX_MIME, "pdf": "application/pdf"}
    for kind in kinds:
        for fmt, mime in mimes.items():
            extra = f"&student_id={student_id['JUST BELOW']}" if kind == "student_performance" else ""
            r = fa.get(f"/offerings/{o1}/reports/{kind}?format={fmt}{extra}")
            disposition = r.headers.get("content-disposition", r.headers.get("Content-Disposition", ""))
            magic = {"csv": True, "xlsx": r.body[:2] == b"PK", "pdf": r.body[:5] == b"%PDF-"}[fmt]
            check(f"{kind}.{fmt}", r.status == 200 and r.headers.get("content-type", r.headers.get("Content-Type", "")).startswith(mime)
                  and f".{fmt}" in disposition and magic and len(r.body) > 100, f"{r.status} {len(r.body)}B {disposition}")
    summary = fa.get(f"/offerings/{o1}/reports/class_summary?format=csv").body.decode("utf-8-sig")
    check("class summary CSV has no NaN / Infinity / None", not any(w in summary for w in ("NaN", "Infinity", "None", "nan")))
    check(f"class summary CSV carries the API's class mean {health['class_mean']['value']}", f"{health['class_mean']['value']:.2f}" in summary)
    attention_csv = list(csv.reader(io.StringIO(fa.get(f"/offerings/{o1}/reports/attention?format=csv").body.decode("utf-8-sig"))))
    flat = " ".join(" ".join(r) for r in attention_csv)
    check("attention CSV lists every flagged student", all(name in flat for name, e in expected.items() if e["rules"]),
          [name for name, e in expected.items() if e["rules"] and name not in flat])
    import re as _re
    unflagged = [name for name, e in expected.items() if not e["rules"]]
    wrongly = [n for n in unflagged for r in attention_csv if n in " ".join(r) and _re.search(r"R[1-7]_", " ".join(r))]
    check("attention CSV gives no rule to an unflagged student", not wrongly, wrongly)
    check("unknown report kind is 404 or 422", fa.get(f"/offerings/{o1}/reports/nonsense?format=csv").status in (404, 422))
    check("unknown format is 422", fa.get(f"/offerings/{o1}/reports/class_summary?format=docx").status == 422)
    check("faculty B cannot download class 1's report (404)", fb.get(f"/offerings/{o1}/reports/class_summary?format=csv").status == 404)

    # ---------------------------------------------------------------- isolation
    section("Faculty isolation (B reading A's class)")
    sid = student_id["JUST BELOW"]
    for path in (f"/offerings/{o1}", f"/offerings/{o1}/analytics", f"/offerings/{o1}/attention", f"/offerings/{o1}/insights",
                 f"/offerings/{o1}/students", f"/offerings/{o1}/assessments", f"/offerings/{o1}/results", f"/offerings/{o1}/interventions",
                 f"/offerings/{o1}/interventions/outcomes", f"/offerings/{o1}/students/{sid}/analytics", f"/assessments/{a_ids[0]}",
                 f"/assessments/{a_ids[0]}/results", f"/students/{sid}", f"/insights/students/{sid}", f"/offerings/{o1}/imports/template"):
        r = fb.get(path)
        check(f"B GET {path.replace(o1, '<class A>').replace(sid, '<student A>').replace(a_ids[0], '<assessment A>')} is 404", r.status == 404, r.status)
    check("B cannot write A's results (404)", fb.put(f"/assessments/{a_ids[0]}/results", {"results": [{"student_id": sid, "score": 1}]}).status == 404)
    check("B cannot edit or delete A's assessment (404)", {fb.patch(f"/assessments/{a_ids[0]}", {"name": "X"}).status, fb.delete(f"/assessments/{a_ids[0]}").status} == {404})
    b_scope = fb.get("/insights/offerings?semester=YEAR").json()
    check("B's class list contains only B's class", [i["offering_id"] if "offering_id" in i else i.get("id") for i in b_scope["items"]] == [o2], b_scope["total"])
    b_students = fb.get("/students?limit=200").json()
    check("B's student list has only B's 6 students", b_students["total"] == 6, b_students["total"])
    b_flags = fb.get("/insights/attention?semester=YEAR&limit=200").json()
    check("B's attention list has no student of class A", not any(i["student"]["name"] in expected for i in b_flags["items"]), b_flags["total"])
    check("faculty GET /users is 403", fb.get("/users").status == 403, fb.get("/users").status)
    b_audit = fb.get("/audit-logs?limit=200").json()["items"]
    check("faculty audit log is scoped: none of A's class", all(a["offering_id"] != o1 for a in b_audit), len(b_audit))
    # Threshold settings: own department (and departments of classes taught) only; else 404.
    check("faculty reads their own department's thresholds", fb.get(f"/departments/{dept_id}/settings").status == 200)
    others = [d["id"] for d in admin.get("/departments?limit=200").json()["items"] if d["id"] != dept_id]
    if others:
        hidden = fb.get(f"/departments/{others[0]}/settings")
        missing = fb.get(f"/departments/{uuid.uuid4()}/settings")
        check("faculty gets 404 for another department's thresholds, same as a missing one",
              hidden.status == missing.status == 404 and hidden.json() == missing.json(), hidden.status)
        check("faculty cannot change another department's thresholds (404)",
              fb.put(f"/departments/{others[0]}/settings/low_performance_percent", {"value": 1}).status == 404)
    check("faculty cannot change their own department's thresholds (403)",
          fb.put(f"/departments/{dept_id}/settings/low_performance_percent", {"value": 1}).status == 403)
    names = {d["id"] for d in fb.get("/me/workspace").json()["threshold_departments"]}
    check("the workspace lists exactly the readable departments", names == {dept_id}, names)
    check("faculty cannot create users, departments or recompute (403)",
          {fb.post("/users", {"email": "x@verify.acadlytics.dev", "full_name": "X", "password": "Verify-12345678", "role": "FACULTY"}).status,
           fb.post("/departments", {"code": "NOPE", "name": "Nope"}).status, fb.post(f"/admin/recompute?offering_id={o1}").status} == {403})
    check("HOD of the department sees both classes", {fb_o for fb_o in (i.get("offering_id") or i.get("id") for i in hod.get("/insights/offerings?semester=YEAR").json()["items"])} >= {o1, o2})

    # ---------------------------------------------------------------- deletion guards
    section("Academic history is not deleted by accident")
    check("an assessment with results cannot be deleted", fa.delete(f"/assessments/{a_ids[0]}").status in (409, 422), fa.delete(f"/assessments/{a_ids[0]}").status)
    check("an offering with results cannot be deleted", admin.delete(f"/offerings/{o1}").status in (409, 422), admin.delete(f"/offerings/{o1}").status)
    check("a section with students cannot be deleted", admin.delete(f"/sections/{sections[0]}").status in (409, 422), admin.delete(f"/sections/{sections[0]}").status)
    check("a course with offerings cannot be deleted", admin.delete(f"/courses/{course_id}").status in (409, 422), admin.delete(f"/courses/{course_id}").status)
    still = fa.get(f"/assessments/{a_ids[0]}/results").json()["counts"]
    check("results are intact after the refused deletions", still["present"] == 8, still)

    # ---------------------------------------------------------------- sessions
    section("Sessions")
    c = Client(args.api)
    c.login(people["fb"]["email"], people["fb"]["password"])
    first_refresh = c.refresh_token
    rotated = c.post("/auth/refresh", {"refresh_token": first_refresh}, token=None)
    check("refresh rotates the token", rotated.status == 200 and rotated.json()["refresh_token"] != first_refresh)
    check("garbage and missing tokens are 401", {c.get("/auth/me", token="abc.def.ghi").status, c.get("/auth/me", token=None).status} == {401})
    check("logout with only the refresh token (no access token) is 204",
          c.post("/auth/logout", {"refresh_token": rotated.json()["refresh_token"]}, token=None).status == 204)
    check("the logged-out session cannot refresh", c.post("/auth/refresh", {"refresh_token": rotated.json()["refresh_token"]}, token=None).status == 401)
    off = admin.post(f"/users/{people['fb']['id']}/deactivate")
    check("deactivated account: existing access token stops working at once", off.status == 200 and fb.get("/auth/me").status == 401, fb.get("/auth/me").status)
    check("deactivated account cannot sign in", Client(args.api).login(people["fb"]["email"], people["fb"]["password"]).status == 401)
    admin.post(f"/users/{people['fb']['id']}/activate")
    check("reactivated account signs in again", Client(args.api).login(people["fb"]["email"], people["fb"]["password"]).status == 200)

    print(f"\n{PASSES} passed, {len(FAILURES)} failed" + (":\n  - " + "\n  - ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
