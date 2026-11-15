"""No credential is hard-coded in anything that runs or configures the application.

Two built-in passwords once shipped in this repository (see docs/SECURITY_AUDIT.md). This
guards against the same mistake in any form: a password, secret or token written as a literal in
runtime code, Compose files or the env template. Tests and fixtures are out of scope: they
legitimately carry throwaway passwords for throwaway databases.

The two known development fallbacks are listed explicitly; production refuses the first and
`docker-compose.prod.yml` requires a real value for both.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCANNED = [
    *sorted((ROOT / "backend" / "app").rglob("*.py")),
    *sorted((ROOT / "backend" / "alembic").rglob("*.py")),
    *sorted(
        p for d in ("app", "components", "lib") for p in (ROOT / "frontend" / d).rglob("*.ts*")
    ),
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.prod.yml",
    ROOT / ".env.example",
    ROOT / "backend" / "Dockerfile",
    ROOT / "frontend" / "Dockerfile",
]

NAME = r"(?P<name>[\w.-]*(?:password|passwd|secret|token|api[_-]?key)[\w.-]*)"
# Code: the name assigned or defaulted to a QUOTED literal (annotations and docstrings are not).
CODE = re.compile(
    NAME + r"""["']?\s*(?::\s*[\w\[\]|. ]+?)?\s*(?:=|:)\s*["'](?P<value>[^"'\s]{6,})["']""", re.I
)
# Configuration: NAME=value, NAME: value, or a ${NAME:-value} default.
CONFIG = re.compile(NAME + r"""(?::-|\s*[=:]\s*["']?)(?P<value>[^\s"'${}]{6,})""", re.I)

ALLOWED = {
    # The development JWT fallback; the API refuses to start with it when APP_ENV=production.
    ("DEV_JWT_SECRET", "dev-only-insecure-secret-change-me-0123456789abcdef"),
    ("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me-0123456789abcdef"),
    # .env.example placeholder, rejected by nothing but useless to an attacker.
    ("JWT_SECRET_KEY", "change-me-to-a-long-random-secret-at-least-32-chars"),
    # Local Compose database default; never published in production (docker-compose.prod.yml
    # requires POSTGRES_PASSWORD and does not expose the port).
    ("POSTGRES_PASSWORD", "acadlytics"),
    # The JWT "type" claim value, not a credential.
    ("ACCESS_TOKEN_TYPE", "access"),
}

NOT_A_VALUE = re.compile(
    r"(?i)^(current-password|new-password|password|text|hidden|bearer|refresh_token|access_token)$"
)


def _findings() -> list[str]:
    found = []
    for path in SCANNED:
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")):
                continue
            pattern = CODE if path.suffix in (".py", ".ts", ".tsx") else CONFIG
            for match in pattern.finditer(line):
                name, value = match.group("name"), match.group("value")
                if (name.upper(), value) in {(n.upper(), v) for n, v in ALLOWED}:
                    continue
                if NOT_A_VALUE.match(value):
                    continue
                found.append(f"{path.relative_to(ROOT)}:{number}: {name} = {value[:3]}…")
    return found


def test_the_scan_covers_the_runtime() -> None:
    assert any(p.name == "config.py" for p in SCANNED)
    assert any(p.name == "docker-compose.prod.yml" for p in SCANNED)
    assert sum(1 for p in SCANNED if p.suffix in (".ts", ".tsx")) > 20


def test_no_literal_credentials_in_runtime_code_or_configuration() -> None:
    assert _findings() == []


@pytest.mark.parametrize(
    ("pattern", "line"),
    [
        ("code", 'ADMIN_PASSWORD = "Winter2026!"'),
        ("code", 'password: str = "Faculty1234"'),
        ("code", 'const apiKey = "sk-live-0123456789"'),
        ("config", "      FACULTY_DEFAULT_PASSWORD: ${FACULTY_DEFAULT_PASSWORD:-Faculty1234}"),
        ("config", "DB_PASSWORD=hunter2hunter2"),
    ],
)
def test_the_pattern_catches_a_hardcoded_credential(pattern: str, line: str) -> None:
    match = (CODE if pattern == "code" else CONFIG).search(line)
    assert match is not None and not NOT_A_VALUE.match(match.group("value")), line


@pytest.mark.parametrize(
    "line",
    [
        "    password_hash: Mapped[str] = mapped_column(String(255))",
        "- Passwords: Argon2id (argon2-cffi defaults).",
        "Password = Annotated[str, Field(min_length=8)]",
        'password=os.environ.get("ACADLYTICS_ADMIN_PASSWORD")',
        '<input type="password" autoComplete="current-password" />',
    ],
)
def test_names_and_types_are_not_flagged(line: str) -> None:
    match = CODE.search(line)
    assert match is None or NOT_A_VALUE.match(match.group("value")), line
