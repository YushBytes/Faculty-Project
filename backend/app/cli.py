"""Operational commands.

    python -m app.cli create-admin --email admin@example.edu --name "Admin"

The password is read from ACADLYTICS_ADMIN_PASSWORD or prompted for (never an argument,
so it does not land in shell history).
"""

import argparse
import getpass
import os
import sys

from pydantic import ValidationError

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create an ADMIN user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
