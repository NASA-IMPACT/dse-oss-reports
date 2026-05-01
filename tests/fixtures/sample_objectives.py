"""Tiny synthetic OBJECTIVES dict shaped like the real auto-generated _objectives_data.py.

Two PIs, three objectives total, with intentional structural variety:

- pi-26.1 has one closed and one open objective; one repo appears in both (cross-objective)
- pi-26.2 has one objective with two contributors and two repos
- One contributor (``alice``) appears in both PIs (cross-PI dedupe coverage)
"""

SAMPLE_OBJECTIVES = {
    "pi-26.1": [
        {
            "issue_number": 101,
            "title": "Sample PI 26.1 Objective A",
            "state": "closed",
            "contributors": [("Alice Example", "alice")],
            "repos": [("acme", "widget")],
        },
        {
            "issue_number": 102,
            "title": "Sample PI 26.1 Objective B",
            "state": "open",
            "contributors": [("Bob Example", "bob")],
            "repos": [("acme", "widget"), ("acme", "gizmo")],
        },
    ],
    "pi-26.2": [
        {
            "issue_number": 103,
            "title": "Sample PI 26.2 Objective C",
            "state": "open",
            "contributors": [("Alice Example", "alice"), ("Carol Example", "carol")],
            "repos": [("acme", "gizmo"), ("globex", "doohickey")],
        },
    ],
}

SAMPLE_PI_DATES = {
    "pi-26.1": ("20251019", "20260117"),
    "pi-26.2": ("20260118", "20260425"),
}
