# ACADLYTICS — Data Model

PostgreSQL 16, SQLAlchemy 2.x models under `backend/app/modules/*/models.py`, all registered in
`backend/app/db/models.py`. Owner of these tables: Agent 1 (Agent 2 adds its own tables — attention
flags, interventions — in its modules and the next migration numbers).

IDs are UUID (`gen_random_uuid()`), timestamps `timestamptz`. Constraint names follow the fixed
convention `pk_/uq_/ck_/fk_/ix_<table>_...`. Money-like exact numbers (marks, percentages) are
`NUMERIC`, never float.

## Migrations (one linear chain)

| Rev | Contents |
|---|---|
| `0001` | baseline |
| `0002` | `users` (role enum), `refresh_tokens` |
| `0003` | `departments`, `academic_terms`, `courses`, `sections`, `course_offerings`, `offering_faculty`, `users.department_id` |
| `0004` | `students`, `student_section_history`, `enrollments` |
| `0005` | `assessments`, `assessment_results`, `settings`, `audit_logs`; `pass_percent`, `config` on offerings |
| `0006` | `import_batches`; `assessment_results.import_batch_id` |

Next free revision id: **`0007`**. `tests/test_migrations.py` fails on two heads, on a failed
down/up round trip, or when models and migrations differ.

## Tables

```
departments ─┬─< courses ──────┐
             ├─< sections ─────┼─< course_offerings >── academic_terms
             ├─< users         │        │ ├─< offering_faculty >── users
             ├─< students      │        │ ├─< enrollments >── students
             └─< settings      │        │ ├─< assessments ─< assessment_results >── students
                               │        │ └─< import_batches ─< (assessment_results.import_batch_id)
audit_logs (actor → users, offering → course_offerings)
```

### Identity

| Table | Columns | Rules |
|---|---|---|
| `users` | email, full_name, password_hash (Argon2id), role `ADMIN\|HOD\|FACULTY`, is_active, department_id, last_login_at | email unique and stored lower-case; HOD must have a department |
| `refresh_tokens` | user_id, token_hash (SHA-256), family_id, expires_at, revoked_at, replaced_by_id | raw tokens never stored; a replayed token revokes its family |

### Academic structure

| Table | Columns | Rules |
|---|---|---|
| `departments` | code, name | code unique, upper-case |
| `academic_terms` | code, name, academic_year (`2026-27`), start_date, end_date, is_current | end > start; at most one current term (partial unique index) |
| `courses` | department_id, code, name, credits | code unique, upper-case |
| `sections` | department_id, name, batch_year, program | unique (department, batch_year, name) |
| `course_offerings` | course_id, term_id, section_id, **pass_percent** (default 50), **config** JSONB object | unique (course, term, section); the unit of teaching and of data access |
| `offering_faculty` | offering_id, user_id, assigned_at | PK (offering, user); drives faculty scope |
| `settings` | department_id, key, value JSONB, updated_by_id | unique (department, key); key `^[A-Za-z0-9_.-]{1,100}$` |

### Students

| Table | Columns | Rules |
|---|---|---|
| `students` | register_number, full_name, email, department_id, batch_year, current_section_id, is_active, deactivated_at | register number `^[A-Z0-9]{5,20}$`, unique; email unique, lower-case |
| `student_section_history` | student_id, section_id, started_at, ended_at | exactly one open entry (ended_at NULL) per student |
| `enrollments` | offering_id, student_id, status `ACTIVE\|DROPPED`, enrolled_at, dropped_at | unique (offering, student); dropping keeps the row |

Historical correctness: a result belongs to (student, assessment → offering). Moving a student to a
new section changes `current_section_id` and the history only; old enrolments and results are
never rewritten.

### Assessments and results (source of truth for analytics)

| Table | Columns | Rules |
|---|---|---|
| `assessments` | offering_id, name, assessment_type `CT\|FT\|QUIZ\|ASSIGNMENT\|LAB\|INTERNAL\|OTHER`, assessment_date, max_marks NUMERIC(6,2), weightage NUMERIC(5,2), sequence_no, is_published, created_by_id | name unique per offering case-insensitively; unique (offering, sequence_no); max > 0; weightage 0–100 |
| `assessment_results` | **PK (student_id, assessment_id)**, score NUMERIC(6,2) NULL, status `present\|absent\|exempt`, max_marks_snapshot, source `manual\|import`, import_batch_id, recorded_by_id, recorded_at, updated_at | CHECK `(status = 'present') = (score IS NOT NULL)`; CHECK `0 ≤ score ≤ max_marks_snapshot`; index on assessment_id |

- Assessment names are **rows**, never columns — there is no `ct1`/`ct2` column anywhere.
- **Missing** = no row. **absent / exempt** = row with NULL score. The database makes it
  impossible to store 0 for absent or exempt, or a NULL for present.
- `max_marks` is locked once an assessment has results; `max_marks_snapshot` records the max each
  result was entered against.
- There is **no question / topic / marks-by-question layer** (DECISION-1); a test asserts those
  tables do not exist.

### Imports and audit

| Table | Columns | Rules |
|---|---|---|
| `import_batches` | offering_id, assessment_id, status `previewed\|committed\|discarded`, file_name, file_type, file_sha256, file_format `wide\|long`, sheet_name, headers, rows (raw strings), column_mapping, fixes, excluded_rows, summary, total_rows, uploaded_by_id, committed_at/by, expires_at | committed_at set exactly when committed |
| `audit_logs` | actor_id, entity, entity_id, action, old_value, new_value, offering_id, created_at | append-only; written in the same transaction as the change |

Audited: result updates and deletions (old + new values), import fixes and confirmations, user
role/department changes, password resets, user and student (de)activation, settings changes.
Secrets are never written to the audit log.
