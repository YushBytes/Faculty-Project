"""Operational commands.

    python -m app.cli bootstrap            # first start: sign-in accounts only (no-op later)
    python -m app.cli create-admin --email admin@example.edu --name "Admin"
    python -m app.cli seed-demo            # the 97-section SRM demo institution (empty DB only)
    python -m app.cli seed-demo --minimal  # the small analytics fixture (contract C11)

The password is read from ACADLYTICS_ADMIN_PASSWORD or prompted for (never an argument,
so it does not land in shell history).
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
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    with get_session_factory()() as session:
        try:
            user = UserService(session).create_user(data)
        except AppError as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Created administrator {user.email} ({user.id})")
    return 0


def seed_srm_command(sections: int, demo_dir: str | None) -> int:
    from app.core.config import Environment, get_settings
    from app.demo import srm

    if get_settings().app_env is Environment.PRODUCTION:
        print("Refusing to load demo data in production.", file=sys.stderr)
        return 2
    if demo_dir:
        from pathlib import Path

        srm.DEMO_DIR = Path(demo_dir)
    password = os.environ.get("ACADLYTICS_DEMO_PASSWORD", "Demo@2026pass")
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
    print(f"Password for every account: {password}")
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
    password = os.environ.get("ACADLYTICS_DEMO_PASSWORD", "Demo@2026pass")
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
    print(f"Accounts (password: {password}):")
    for email, role in report.users.items():
        print(f"  {role:<8} {email}")
    print("Embedded patterns (21CSC201J / A1):")
    for number, label in report.patterns.items():
        print(f"  {number}  {label}")
    return 0


def bootstrap_command() -> int:
    from app.bootstrap import BootstrapError, bootstrap

    with get_session_factory()() as session:
        try:
            created = bootstrap(session)
        except BootstrapError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if created:
        print("Empty platform: created the sign-in accounts (password: ACADLYTICS_INITIAL_PASSWORD")
        print("or Demo@2026pass). Everything else comes from uploaded TLP reports.")
        for email, role in created:
            print(f"  {role:<14} {email}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Create the sign-in accounts on an empty database")
    admin = sub.add_parser("create-admin", help="Create an ADMIN user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    seed = sub.add_parser(
        "seed-demo",
        help="Load the SRM demo institution into an empty database "
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
