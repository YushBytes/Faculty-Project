"""Report and export tests.

Pure like the analytics suite: a report is built from an in-memory snapshot and serialised to
bytes, so nothing here needs a database. The cross-format tests are the point — they read the
same value out of CSV, XLSX and PDF and compare.
"""
