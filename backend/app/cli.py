"""Operational commands.

    python -m app.cli create-admin --email admin@example.edu --name "Admin"
    python -m app.cli seed-demo            # synthetic demo data, empty database only

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create an ADMIN user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    sub.add_parser(
        "seed-demo",
        help="Load the synthetic demo dataset into an empty database "
        "(password from ACADLYTICS_DEMO_PASSWORD)",
    )
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "seed-demo":
        return seed_demo_command()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
