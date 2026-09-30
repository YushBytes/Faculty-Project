# ACADLYTICS — Import Format

How marks get from a faculty spreadsheet into `assessment_results`. Owner: Agent 1.
Implementation: `backend/app/modules/imports/` (engine: `validation.py`, a pure function).

## Workflow

```
1. GET  /api/v1/offerings/{id}/imports/template        .xlsx with every assessment column
   GET  /api/v1/assessments/{id}/import/template       .xlsx for one assessment
2. POST /api/v1/offerings/{id}/imports                 multipart "file"  -> 201 + preview
   POST /api/v1/assessments/{id}/import                (single assessment)
3. GET  /api/v1/imports/{batch}/preview?only=all|issues|errors
4. POST /api/v1/imports/{batch}/fix       {"fixes":[{"row":5,"column":"CT1","value":"0"}]}
   POST /api/v1/imports/{batch}/exclude   {"rows":[7,9],"excluded":true}
   POST /api/v1/imports/{batch}/mapping   {"mappings":{"Cycle Test II":"<assessment id>"}}
                                          ("ignore" drops a column, null = automatic)
5. POST /api/v1/imports/{batch}/confirm   -> {"created","updated","unchanged",...}
   POST /api/v1/imports/{batch}/discard
   GET  /api/v1/imports                   history (scoped)
```

- Nothing is written to results before **confirm**. Steps 3–4 revalidate the whole sheet and
  return the new preview each time.
- **Confirm** revalidates against current data and refuses (422, every blocking error listed in
  `error.details`) while any error remains. It then writes results, audit rows for overwritten
  values, the batch state, and runs the analytics recompute hook — all in **one transaction**.
- A staged batch expires after **24 hours**. Only the uploader, or someone who can administer the
  offering (ADMIN, the department's HOD), may fix, map, exclude, confirm or discard it. Anyone who
  can view the offering may upload and see history.
- Row numbers everywhere are **spreadsheet row numbers** (header = row 1 unless blank rows precede it).

## SRM TLP reports and multi-file uploads

`POST /api/v1/tlp-uploads` (multipart `files`, optional `course_id` / `term_id` / `offering_id`)
accepts up to 150 TLP5 reports at once. For each file the title block (`Test Name`, `Academic
Year`, `Component Max. Mark`, `course(name) handled by faculty(id)`) and summary block (`Total
strength`, `Total absentees`, ranges) are parsed; the file is routed to the course's offering in
that term whose ACTIVE enrolments contain most of its register numbers (at least half, and
strictly more than any other), and to the assessment named by `Test Name` (`FJ-II` = `FJ-2`).
Title-block checks: `course_mismatch`, `term_mismatch`, `wrong_assessment`, `max_mismatch` and
`summary_mismatch` are errors; `faculty_mismatch` and an absentee count that differs are warnings.
`GET /tlp-uploads/{group}` returns every staged file's status; `POST /tlp-uploads/{group}/confirm`
confirms each confirmable file in its own transaction and publishes its assessment.

## Accepted files

- `.xlsx` (first sheet), UTF-8 `.csv` (comma, semicolon or tab), or an SRM TLP-format text
  `.pdf`. The type is detected from the file bytes, not the name; `.xls`, other PDFs, zips and
  non-UTF-8 text are rejected.
- At most 5 MB, 5000 data rows, 200 columns. The header row is the first row naming a register
  number column (else the first non-blank row); title rows above it and the summary block below the
  table ("Total strength", ranges, signatures) are kept as metadata, never read as students. Fully blank data rows are skipped and reported as info.
- Every cell is read as a **raw string**. Nothing is converted to a number until validation, and
  nothing is ever converted to 0.

## Sheet layouts (detected automatically)

**Wide** — one row per student, one column per assessment (what the template produces):

| Register No | Name | CT1 (max 50) | CT2 | FT1 | Remarks |
|---|---|---|---|---|---|
| RA2511003010001 | Aarav Sharma | 45 | 38.5 | | |
| RA2511003010002 | Diya Iyer | AB | 40 | EX | |

**Long** — one row per (student, assessment); chosen when the sheet has an assessment-name column
*and* a score column:

| Register No | Student Name | Assessment | Score | Max Score | Percentage | Status |
|---|---|---|---|---|---|---|
| RA2511003010001 | Aarav Sharma | CT1 | 45 | 50 | 90 | |
| RA2511003010002 | Diya Iyer | CT1 | | 50 | | absent |

### Column recognition

Headers are compared case-insensitively with punctuation ignored (`Reg. No` = `reg_no`).

| Role | Accepted headers |
|---|---|
| Register number (required) | register number, register no, reg no, regno, registration number/no, roll no/number |
| Name (optional, checked) | name, full name, student name |
| Long: assessment | assessment, assessment name, exam, test, component |
| Long: score | score, marks, mark, marks obtained, obtained, score obtained |
| Long: max | max score, max marks, max, out of, total marks, maximum |
| Long: percentage | percentage, percent, pct, perc |
| Long: status | status, attendance status |
| Ignored | s no, sl no, serial no, sr no, email, section, department, batch, program, remarks, total, grade, result, rank, attendance, cgpa, gpa, date, course, offering |
| Wide: anything else | an **assessment column**, matched to an assessment of the offering by name |

Assessment names match ignoring case, spaces and punctuation and any max annotation:
`CT1`, `ct 1`, `CT-1`, `CT1 (max 50)`, `CT1 /50`, `CT1 out of 50` all mean `CT1`. A max stated
in the header must equal the assessment's `max_marks`. A column matching no assessment, or more
than one, is an error until mapped or ignored — the system never guesses.

For a single-assessment import, a lone `Score` / `Marks` column maps to that assessment.

### Cell values

| Cell | Stored as | Level |
|---|---|---|
| number (≤ 2 decimals, 0 ≤ x ≤ max) | `present`, score = x | — |
| blank | `absent`, score NULL — **never 0** | warning `blank_cell_absent` |
| `AB`, `A`, `ABS`, `ABSENT`, `-`, `--` | `absent`, score NULL | info `absent_marker` |
| `EX`, `EXEMPT`, `EXEMPTED` | `exempt`, score NULL | info `exempt_marker` |
| anything else | not stored | error `invalid_number` |

To record a real **0** for a blank cell, fix it explicitly (`POST /imports/{id}/fix` with
`"value": "0"`); every fix is written to the audit log with the uploaded value.

Long sheets may add a status column (`present`/`P`, `absent`/`AB`/…, `exempt`/`EX`): a status
of absent/exempt with a score, or present without one, is an error. A percentage, if given, must be
0–100 and within 0.5 of `100 × score / max`.

## Validation codes

Errors block confirm; warnings and info are shown and left to the faculty member.

| Code | Level | Scope | Meaning |
|---|---|---|---|
| `unsupported_file` | error | file | not .xlsx / UTF-8 .csv (rejected at upload) |
| `missing_identity_column` | error | file | no register-number column (rejected at upload) |
| `ambiguous_identity_column` | error | file | two register-number columns (rejected at upload) |
| `duplicate_header` | error | file | the same header twice (rejected at upload) |
| `malformed_header` | error | file | a column has values but no header (rejected at upload) |
| `no_assessment_columns` | error | file | wide sheet without any assessment column |
| `no_score_column` | error | file | long sheet without a score column |
| `missing_assessment_definition` | error | column / cell | name matches no assessment of the offering |
| `ambiguous_column` | error | column / cell | name matches several assessments |
| `duplicate_assessment_column` | error | column | two columns feed the same assessment |
| `max_mismatch` | error | column / cell | stated max ≠ assessment max |
| `wrong_assessment` | error | column / cell | single-assessment import contains another assessment |
| `missing_register_number` | error | row | blank register number |
| `unknown_student` | error | row | register number not in the student register |
| `not_enrolled` | error | row | student not enrolled in this offering |
| `dropped_student` | error | cell | new result for a dropped or inactive student |
| `duplicate_student_row` | error | row / cell | same student (wide) or student+assessment (long) twice — every copy flagged |
| `conflicting_identity` | error | row | the name belongs to *another* student of the offering |
| `invalid_number` | error | cell | not a number or a recognised status |
| `too_many_decimals` | error | cell | more than 2 decimal places |
| `score_below_zero` | error | cell | score < 0 |
| `score_above_max` | error | cell | score > assessment max |
| `impossible_percentage` | error | cell | percentage outside 0–100, without a score, or inconsistent |
| `invalid_status` | error | cell | unrecognised status word |
| `conflicting_status` | error | cell | status contradicts the score |
| `missing_score` | error | cell | status present but score blank |
| `missing_assessment_name` | error | cell | long sheet row without an assessment name |
| `blank_cell_absent` | warning | cell | blank recorded as absent |
| `name_mismatch` | warning | row | name differs from the register (similarity < 0.8) |
| `missing_from_file` | warning | file | enrolled students with no row (their results are untouched) |
| `will_overwrite` | warning | file | existing results will change (old values audited) |
| `duplicate_file` | warning | file | this exact file was already imported into the offering |
| `absent_marker`, `exempt_marker` | info | cell | marker recognised |
| `empty_rows_skipped` | info | file | blank rows skipped |

A column-level error blocks the whole import (every cell of that column is unreliable); a row
error blocks that row; a cell error blocks that cell. Excluded rows are not validated.

## Preview summary

`total_rows, excluded_rows, rows_with_errors, matched_students, not_found, not_enrolled,
duplicates, blank_cells, absent_markers, exempt_markers, exceeds_max, invalid_values,
missing_students, will_create, will_update, unchanged, cells_to_write, errors, warnings, infos,
can_confirm`. Each cell carries `raw` (uploaded), `value` (after fixes), `fixed`, `status`, `score`,
`change` (`create` / `update` / `unchanged`) and its issues.

## Student import (separate, simpler)

`POST /api/v1/students/import` (ADMIN / HOD, file) and `POST /api/v1/students/bulk` (JSON) upsert
students by register number: columns register number, name, department code, batch year,
optional email and section. All rows are validated first; any error means nothing is written.
`dry_run=true` validates only.
