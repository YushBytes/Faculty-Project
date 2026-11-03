# Security

ACADLYTICS holds student marks. A defect that exposes a student's results to someone outside the
faculty member's or coordinator's remit is treated as a security issue, not a bug.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on the repository), or contact the maintainers directly.

Include what you did, what you expected, what happened, and the smallest reproduction you have.
A report that lets us reproduce the problem is worth far more than one that describes it.

## Scope we care about most

- **Access-control escape.** Any way for one role to read or change academic data outside its
  scope, as defined in [`README.md` §1](README.md) — a faculty member reaching another section, a
  coordinator reaching another course, anyone reaching another department.
- **Session handling.** Anything that exposes a refresh token to page scripts, prevents token
  rotation, or lets an access token outlive its window.
- **Import pipeline.** A crafted upload that writes marks without a confirm step, bypasses the
  validation checks, or escapes the file parsers.
- **Report exports.** A generated report that leaks identifiers it should not carry; exports are
  deliberately limited to academic identifiers.

## Deployment expectations

These are enforced or assumed by the application, and a deployment that breaks them is insecure
regardless of the code:

- `APP_ENV=production` requires `JWT_SECRET_KEY` of at least 32 random characters. The
  application refuses to start with the development fallback.
- `ACADLYTICS_INITIAL_PASSWORD` must be set in production; the first accounts are not created
  with a default password there.
- `FACULTY_DEFAULT_PASSWORD` sets the initial password for faculty logins created from uploaded
  reports. Change it from the documented default and require a reset on first sign-in.
- Serve over HTTPS. The session cookie drops its `Secure` flag only when
  `ACADLYTICS_INSECURE_COOKIES=1`, which exists for local demos over plain HTTP and must never be
  set on a deployed instance.
- Never commit a real `.env`. It is gitignored; `.env.example` is the tracked template.

## Credentials in this repository

The passwords documented in the README and `.env.example` are development defaults for an empty
local database. They are not secrets, and they are not what a deployment should run with.
