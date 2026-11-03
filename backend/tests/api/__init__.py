"""API tests.

These exercise the analytics endpoints without PostgreSQL: the platform read sits behind one
dependency, so it is substituted and everything above it — routing, auth, scope behaviour,
serialisation and error mapping — runs for real.
"""
