"""Operational commands.

    python -m app.cli bootstrap            # first start: the Administrator only (no-op later)
    python -m app.cli create-admin --email admin@example.edu --name "Admin"

Development only (fictional data; refused in production and on a non-empty database; never run
automatically; needs ACADLYTICS_DEMO_PASSWORD):

    python -m app.cli seed-demo            # the 97-section fictional institution
    python -m app.cli seed-demo --minimal  # the small analytics fixture (contract C11)

Passwords are read from the environment (ACADLYTICS_ADMIN_PASSWORD) or prompted for, never
taken as an argument, so they do not land in shell history.
"""

import argparse
import getpass
import os
import sys

from pydantic import ValidationError

import app.db.models  # noqa: F401  (register every table so foreign keys resolve)
from app.core.errors import AppError
from app.db.session import get_session_factory
from app.modules.users.models import Role
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


def create_admin(email: str, name: str) -> int:
    password = os.environ.get("ACADLYTICS_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    try:
        data = UserCreate(email=email, full_name=name, password=password, role=Role.ADMIN)
    except ValidationError as exc:
        # Never echo the submitted values: one of them is the password.
        for error in exc.errors(include_input=False):
            print(f"Invalid {'.'.join(map(str, error['loc']))}: {error['msg']}", file=sys.stderr)
        return 2
    with get_session_factory()() as session:
        try:
            user = UserService(session).create_user(data)
        except AppError as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Created administrator {user.email} ({user.id})")
    return 0


def _demo_password() -> str | None:
    password = os.environ.get("ACADLYTICS_DEMO_PASSWORD")
    if not password or len(password) < 8:
        print(
            "Set ACADLYTICS_DEMO_PASSWORD (8+ characters) for the fictional demo accounts.",
            file=sys.stderr,
        )
        return None
    return password


def seed_srm_command(sections: int, demo_dir: str | None) -> int:
    from app.core.config import Environment, get_settings
    from app.demo import srm

    if get_settings().app_env is Environment.PRODUCTION:
        print("Refusing to load demo data in production.", file=sys.stderr)
        return 2
    if demo_dir:
        from pathlib import Path

        srm.DEMO_DIR = Path(demo_dir)
    password = _demo_password()
    if password is None:
        return 2
    print(f"Seeding the SRM demo institution ({sections} sections) ...")
    with get_session_factory()() as session:
        try:
            report = srm.seed_srm(session, password=password, sections=sections)
        except srm.SeedError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(
        f"Done in {report.seconds}s: {report.sections} sections, {report.students} students, "
        f"{report.faculty} faculty, {report.offerings} classes, {report.results} results, "
        f"{report.imports} TLP imports, {report.interventions} interventions."
    )
    print("Password for every account: the value of ACADLYTICS_DEMO_PASSWORD")
    for email, role in list(report.accounts.items())[:12]:
        print(f"  {role:<20} {email}")
    print(f"  ... and faculty1..faculty100@{srm.DOMAIN}")
    if report.demo_files:
        print(f"TLP upload demo files: {srm.DEMO_DIR}")
    return 0


def seed_demo_command() -> int:
    from app.core.config import Environment, get_settings
    from app.seed import SeedError, seed_demo

    if get_settings().app_env is Environment.PRODUCTION:
        print("Refusing to load demo data in production.", file=sys.stderr)
        return 2
    password = _demo_password()
    if password is None:
        return 2
    with get_session_factory()() as session:
        try:
            report = seed_demo(session, password=password)
        except SeedError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        session.commit()
    print(f"Demo data loaded: {report.students} students, {report.results} results.")
    print("Offerings:")
    for offering in report.offerings:
        print(f"  {offering}")
    print("Accounts (password: ACADLYTICS_DEMO_PASSWORD):")
    for email, role in report.users.items():
        print(f"  {role:<8} {email}")
    print("Embedded patterns (21CSC201J / A1):")
    for number, label in report.patterns.items():
        print(f"  {number}  {label}")
    return 0


def bootstrap_command() -> int:
    from app.bootstrap import BootstrapError, admin_password_from_env, bootstrap, needs_admin

    with get_session_factory()() as session:
        try:
            created = bootstrap(session)
        except (BootstrapError, AppError) as exc:
            print(getattr(exc, "message", str(exc)), file=sys.stderr)
            return 1
        missing = not created and needs_admin(session)
    for email, role in created:
        print(f"Created the {role} account {email} (password: ACADLYTICS_ADMIN_PASSWORD).")
    if missing and not admin_password_from_env():
        # Not fatal: the API still starts, but nobody can sign in until an admin exists.
        print(
            "No Administrator account exists and ACADLYTICS_ADMIN_PASSWORD is not set. Set it in "
            ".env and restart, or run: python -m app.cli create-admin --email <email> --name "
            "<name>",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Create the Administrator when none exists")
    admin = sub.add_parser("create-admin", help="Create an ADMIN user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    seed = sub.add_parser(
        "seed-demo",
        help="Development only: load a fictional institution into an empty database "
        "(password from ACADLYTICS_DEMO_PASSWORD)",
    )
    seed.add_argument("--minimal", action="store_true", help="the small C11 analytics fixture")
    seed.add_argument("--sections", type=int, default=97)
    seed.add_argument("--demo-dir", default=os.environ.get("ACADLYTICS_DEMO_DIR"))
    args = parser.parse_args(argv)
    if args.command == "bootstrap":
        return bootstrap_command()
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "seed-demo":
        if args.minimal:
            return seed_demo_command()
        return seed_srm_command(args.sections, args.demo_dir)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
