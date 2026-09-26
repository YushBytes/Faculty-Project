"""Agent 2: analytics, attention/segmentation, interventions and reports.

One sub-package per module, same layering as app/modules/: router -> service -> repository.
Read academic data through the platform services/repositories, never by re-querying
platform tables ad hoc, so access rules (faculty scope, PII) stay enforced in one place.
"""
