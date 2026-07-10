from proofcheck.concurrency import ordered_map, resolve_workers


def test_resolve_workers_semantics():
    # Nothing (or one item) to do -> always sequential.
    assert resolve_workers(0, 0) == 1
    assert resolve_workers(8, 1) == 1
    # Explicit request is honoured but never exceeds the item count.
    assert resolve_workers(4, 100) == 4
    assert resolve_workers(64, 3) == 3
    # 1 forces sequential even with many items.
    assert resolve_workers(1, 100) == 1
    # Auto (0) picks at least one worker and never more than the items.
    auto = resolve_workers(0, 100)
    assert 1 <= auto <= 100


def test_ordered_map_preserves_order_sequential():
    assert ordered_map(lambda x: x * x, range(6), workers=1) == [0, 1, 4, 9, 16, 25]


def test_ordered_map_preserves_order_parallel():
    # Even with many workers and out-of-order completion, results stay in input order.
    items = list(range(50))
    result = ordered_map(lambda x: x + 1, items, workers=8)
    assert result == [x + 1 for x in items]


def test_ordered_map_empty_and_single():
    assert ordered_map(str, [], workers=8) == []
    assert ordered_map(str, [42], workers=8) == ["42"]
