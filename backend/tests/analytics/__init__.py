"""Analytics tests.

Everything under here is a **pure** test: no database, no HTTP client, no fixtures from the
root ``conftest.py``. That is deliberate and is itself part of the design — if a test in
this package ever needs a session, the formula it covers has reached into the database and
the layering in ``app/modules/analytics`` has been broken.

Layout::

    canonical.py   one rich, hand-computed cohort (the policy end to end)
    builders.py    small scenario builders, one awkward condition each
    test_*.py      one module per core module
"""
