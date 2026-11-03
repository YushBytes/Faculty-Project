import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.users.models import Role

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EmployeeCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9-]+$"
    ),
]
Designation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Upper bound keeps Argon2 input reasonable; lower bound per NIST SP 800-63B.
Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: FullName
    password: Password
    role: Role
    department_id: uuid.UUID | None = None
    employee_code: EmployeeCode | None = None
    designation: Designation | None = None


class UserUpdate(BaseModel):
    """Partial update. ``password`` is an administrator reset and revokes the user's sessions."""

    model_config = ConfigDict(extra="forbid")

    full_name: FullName | None = None
    role: Role | None = None
    password: Password | None = None
    department_id: uuid.UUID | None = None
    employee_code: EmployeeCode | None = None
    designation: Designation | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    department_id: uuid.UUID | None
    employee_code: str | None = None
    designation: str | None = None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
