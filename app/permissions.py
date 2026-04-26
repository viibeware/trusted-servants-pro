# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-module role gating.

Each module on the Settings → Modules tab stores a single
``required_role`` string. The helper here decides whether a given user
satisfies that requirement. Roles are NOT a strict hierarchy — frontend
editors aren't a strict subset of editors — so the matrix is enumerated
explicitly rather than computed.
"""

# Display label + ordering for the dropdown. Insertion order is the
# rendered order; first item is the "broadest" tier.
ROLE_TIERS = [
    ("viewer",          "All signed-in users"),
    ("editor",          "Editors and admins"),
    ("frontend_editor", "Frontend editors and admins"),
    ("admin",           "Admins only"),
]
ROLE_TIER_KEYS = {k for k, _ in ROLE_TIERS}


def user_meets_role(user, required):
    """True if ``user``'s role satisfies ``required``. Anonymous users
    always fail; an unknown ``required`` value is treated as the
    strictest tier (admin)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if required == "viewer":
        return True  # any signed-in user
    if required == "editor":
        return role in ("admin", "editor")
    if required == "frontend_editor":
        return role in ("admin", "frontend_editor")
    if required == "admin":
        return role == "admin"
    # Unknown requirement → fail closed.
    return role == "admin"
