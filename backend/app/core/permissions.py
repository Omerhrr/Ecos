"""Role -> permission matrix (plan §43).

Permissions are `module:action` strings. Roles mirror the participant model:
- luxeen_admin : platform staff (Plannexis/Luxeen) — everything, all tenants
- owner        : operator organization owner — everything within their org
- admin        : senior operator staff — everything except user management
- manager      : runs catalog/orders/logistics/CRM/storefront/landing pages
- agent        : front-line sales — CRM + order intake + reads
- viewer       : read-only analyst access

Tenant isolation note: permissions gate *what* a role may do; scoping gates
*which rows* it may touch. Rows carrying org_id are filtered by the caller's
org unless the caller is platform staff.
"""

from __future__ import annotations

READ_PERMISSIONS = [
    "supply:read",
    "catalog:read",
    "orders:read",
    "logistics:read",
    "payments:read",
    "finance:read",
    "settlements:read",
    "crm:read",
    "storefront:read",
    "landing_pages:read",
    "marketing:read",
    "returns:read",
    "ai_harness:read",
    "procurement:read",
    "warehouse:read",
    "analytics:read",
]

ALL_PERMISSIONS = READ_PERMISSIONS + [
    "supply:write",
    "catalog:write",
    "orders:write",
    "logistics:write",
    "payments:write",
    "settlements:write",
    "crm:write",
    "storefront:write",
    "landing_pages:write",
    "marketing:write",
    "returns:write",
    "ai_harness:write",
    "ai_harness:approve",
    "procurement:write",
    "warehouse:write",
    "identity:manage",
]

_ROLE_OPS_WRITE = [
    "catalog:write", "orders:write", "logistics:write",
    "crm:write", "storefront:write", "landing_pages:write",
    "marketing:write", "returns:write", "warehouse:write",
]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "luxeen_admin": list(ALL_PERMISSIONS),
    "owner": list(ALL_PERMISSIONS),
    "admin": [p for p in ALL_PERMISSIONS if p != "identity:manage"],
    "manager": list(READ_PERMISSIONS) + _ROLE_OPS_WRITE,
    "agent": [
        "catalog:read", "orders:read", "orders:write", "logistics:read",
        "crm:read", "crm:write", "storefront:read",
        "landing_pages:read", "marketing:read",
        "returns:read", "returns:write", "analytics:read",
        "warehouse:read",
    ],
    "viewer": list(READ_PERMISSIONS),
}


def permissions_for_role(role: str) -> list[str]:
    return list(ROLE_PERMISSIONS.get(role, []))
