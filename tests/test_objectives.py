from dse_oss_reports.objectives import (
    get_all_contributors,
    get_all_repos,
    get_contributors_for_pi,
    get_repos_for_pi,
    get_repos_x_contributors_for_pi,
)


def test_get_repos_for_pi_returns_distinct_sorted_repos(sample_objectives):
    # pi-26.1: obj 101 has [(acme, widget)]; obj 102 has [(acme, widget), (acme, gizmo)]
    # → distinct sorted: [(acme, gizmo), (acme, widget)]
    assert get_repos_for_pi(sample_objectives, "pi-26.1") == [
        ("acme", "gizmo"),
        ("acme", "widget"),
    ]


def test_get_repos_for_pi_returns_empty_for_unknown_pi(sample_objectives):
    assert get_repos_for_pi(sample_objectives, "pi-99.9") == []


def test_get_contributors_for_pi_returns_distinct_sorted_by_name(sample_objectives):
    # pi-26.2: obj 103 has [(Alice, alice), (Carol, carol)]
    assert get_contributors_for_pi(sample_objectives, "pi-26.2") == [
        ("Alice Example", "alice"),
        ("Carol Example", "carol"),
    ]


def test_get_contributors_for_pi_dedupes_across_objectives(sample_objectives):
    # pi-26.1: obj 101 has Alice, obj 102 has Bob → both, distinct, sorted by name
    assert get_contributors_for_pi(sample_objectives, "pi-26.1") == [
        ("Alice Example", "alice"),
        ("Bob Example", "bob"),
    ]


def test_get_repos_x_contributors_for_pi_pairs_within_each_objective_only(sample_objectives):
    # pi-26.1:
    #   obj 101: contributors=[alice], repos=[(acme, widget)]
    #     → (acme, widget, alice)
    #   obj 102: contributors=[bob], repos=[(acme, widget), (acme, gizmo)]
    #     → (acme, widget, bob), (acme, gizmo, bob)
    # NOT (acme, gizmo, alice) — alice only appears in obj 101 which only has widget.
    # This is the key behavior that distinguishes this helper from a cartesian product.
    assert get_repos_x_contributors_for_pi(sample_objectives, "pi-26.1") == [
        ("acme", "gizmo", "bob"),
        ("acme", "widget", "alice"),
        ("acme", "widget", "bob"),
    ]


def test_get_repos_x_contributors_for_pi_full_cartesian_within_a_single_objective(
    sample_objectives,
):
    # pi-26.2 has one objective (103) with [alice, carol] × [(acme, gizmo), (globex, doohickey)]
    assert get_repos_x_contributors_for_pi(sample_objectives, "pi-26.2") == [
        ("acme", "gizmo", "alice"),
        ("acme", "gizmo", "carol"),
        ("globex", "doohickey", "alice"),
        ("globex", "doohickey", "carol"),
    ]


def test_get_all_repos_dedupes_across_pis(sample_objectives):
    # Across both PIs: widget (pi-26.1), gizmo (both PIs), doohickey (pi-26.2)
    assert get_all_repos(sample_objectives) == [
        ("acme", "gizmo"),
        ("acme", "widget"),
        ("globex", "doohickey"),
    ]


def test_get_all_contributors_dedupes_across_pis(sample_objectives):
    # Alice appears in both PIs, Bob in pi-26.1, Carol in pi-26.2 — distinct, sorted by name
    assert get_all_contributors(sample_objectives) == [
        ("Alice Example", "alice"),
        ("Bob Example", "bob"),
        ("Carol Example", "carol"),
    ]
