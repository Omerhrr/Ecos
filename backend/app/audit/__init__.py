"""Audit domain (plan §44 — Security and Audit).

Every important operation should be auditable: who changed a product, who
changed a price, who approved a refund or settlement, which AI operator made
a recommendation and who approved its action.

Two layers:

1. BLANKET  — an HTTP middleware records every mutating request
   (POST/PATCH/PUT/DELETE) with actor, role, method, path, IP and status.
2. DEPTH    — sensitive endpoints call `audit.record(...)` with BEFORE/AFTER
   snapshots and a semantic action (`product.price_changed`,
   `settlement.executed`, `ai.run_approved`, ...).

Both write the same row shape:

    actor · action · timestamp · object · previous state · new state
    · source · authorization context
"""
