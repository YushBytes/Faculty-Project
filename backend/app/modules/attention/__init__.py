"""Attention-flag persistence (dependency D6).

The analytics engine remains the source of truth: :mod:`app.modules.analytics.core.attention`
decides what fires. This module only *materialises* that verdict, so a flag's history survives
a recompute (PROJECT_CONTEXT D6) and an intervention can point at the evidence that prompted
it. Nothing here evaluates a rule.
"""
