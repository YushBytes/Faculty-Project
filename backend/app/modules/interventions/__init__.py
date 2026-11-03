"""Intervention persistence (dependency D5).

Stores what a faculty member did and why. The Phase 6 engine
(:mod:`app.modules.analytics.core.interventions`) remains the only thing that *measures* what
happened afterwards: no outcome is stored, because an outcome changes every time a new
assessment lands and a stored copy would immediately disagree with the engine.
"""
