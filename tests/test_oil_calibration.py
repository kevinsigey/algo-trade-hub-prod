"""Picker v2 calibration map (spec 2026-11-09, option A): bucketed
frequencies with pseudocount shrinkage, monotone, walk-forward pure,
with the preregistered shrinkage/identity fallbacks below the floors."""

from datetime import UTC, datetime, timedelta

from tradehub.oil_calibration import CalSample, apply_map, fit_map, pairs_before

C0 = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)


def _batch(prob: float, hits: int, n: int, close: datetime) -> list[CalSample]:
    return [CalSample(prob, True, close)] * hits + [CalSample(prob, False, close)] * (n - hits)


def _spread(specs, events: int = 50) -> list[CalSample]:
    """Distribute (prob, hits, n) specs round-robin over `events` hourly closes."""
    closes = [C0 + timedelta(hours=i) for i in range(events)]
    out: list[CalSample] = []
    for prob, hits, n in specs:
        rows = _batch(prob, hits, n, C0)
        for i, row in enumerate(rows):
            out.append(CalSample(row.prob, row.hit, closes[i % events]))
    return out


def test_empty_and_tiny_histories_are_the_identity():
    m = fit_map([])
    assert m.kind == "identity" and apply_map(m, 0.73) == 0.73
    m = fit_map(_batch(0.6, 2, 3, C0))
    assert m.kind == "identity" and m.version.startswith("oilcal-identity")


def test_a_middling_history_uses_shrinkage_toward_the_base_rate():
    # 100 rows (below the 1,000-row bucket floor): stated 0.8 realizes 0.6,
    # stated 0.2 realizes 0.2 -> base 0.4, least-squares slope 0.6 by hand.
    samples = _batch(0.8, 30, 50, C0) + _batch(0.2, 10, 50, C0 + timedelta(hours=1))
    m = fit_map(samples)
    assert m.kind == "shrinkage"
    assert apply_map(m, 0.8) == 0.64  # pulled down toward the base rate
    assert apply_map(m, 0.2) == 0.28  # pulled up toward it
    assert m.version.startswith("oilcal-shrink-")


def test_bucket_values_carry_the_pseudocount_shrinkage():
    # 500 rows stated 0.45 realizing 30% + 500 stated 0.65 realizing 70%,
    # spread over 50 events = 1,000 rows, above both bucket floors.
    m = fit_map(_spread([(0.45, 150, 500), (0.65, 350, 500)]))
    assert m.kind == "buckets" and m.n_rows == 1000 and m.n_events == 50
    # bucket [0.6, 0.7): (350 + 20*0.65) / 520, untouched by pooling.
    assert apply_map(m, 0.65) == round(363 / 520, 6)
    # bucket [0.4, 0.5) alone would be (150 + 20*0.45) / 520 = 0.3058, but
    # the empty bucket before it anchors at its centre 0.35 and violates
    # monotonicity, so PAVA pools the two: (7 + 159) / 540.
    assert apply_map(m, 0.45) == round(166 / 540, 6)
    # piecewise-linear between the knots, clamped outside them
    assert apply_map(m, 0.45) < apply_map(m, 0.5) < apply_map(m, 0.55) == 0.55
    assert apply_map(m, 0.01) == 0.05  # the empty first bucket anchors at its centre
    assert m.version.startswith("oilcal-buckets10-k20-thru") and m.version.endswith("-n1000")


def test_the_map_is_monotone_even_when_raw_buckets_are_not():
    # The 0.45 bucket realizes 0.69 while the 0.55 bucket realizes 0.214:
    # PAVA pools the violators to their weighted mean, 0.452.
    m = fit_map(_spread([(0.45, 336, 480), (0.55, 96, 480), (0.85, 34, 40)]))
    assert apply_map(m, 0.45) == apply_map(m, 0.55) == 0.452
    grid = [apply_map(m, p / 100) for p in range(0, 101, 5)]
    assert grid == sorted(grid)


class _Q:
    """A supa fake shaped like the real journal store's reads: eq/in_
    filters, one order column per call, inclusive range pages."""

    def __init__(self, rows):
        self.rows, self.filters, self.in_filters, self._range = rows, {}, {}, None

    def select(self, *_a, **_k):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.in_filters[key] = set(values)
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def execute(self):
        data = [r for r in self.rows
                if all(r.get(k) == v for k, v in self.filters.items())
                and all(r.get(k) in vs for k, vs in self.in_filters.items())]
        if self._range is not None:
            data = data[self._range[0]:self._range[1] + 1]
        return type("R", (), {"data": data})()


def test_load_samples_reads_the_live_versions_settled_rows():
    from tradehub.oil_calibration import load_samples

    forecasts = [
        {"id": 1, "target": "KXWTIH-26NOV0913-T88.5", "probability": 0.7,
         "forecaster": "oil_wti_hourly", "forecaster_version": "wti-hourly-v4-hl-shadow"},
        {"id": 2, "target": "KXWTIH-26NOV0913-T89.5", "probability": 0.3,
         "forecaster": "oil_wti_hourly", "forecaster_version": "wti-hourly-v4-hl-shadow"},
        {"id": 3, "target": "KXWTIH-26NOV0913-T90.5", "probability": 0.2,
         "forecaster": "oil_wti_hourly", "forecaster_version": "wti-hourly-v4-hl-shadow"},
        {"id": 4, "target": "KXWTIH-26NOV0913-T91.5", "probability": 0.9,
         "forecaster": "oil_wti_hourly", "forecaster_version": "wti-hourly-v1"},
    ]
    settlements = [{"target": "KXWTIH-26NOV0913-T88.5", "outcome": 1},
                   {"target": "KXWTIH-26NOV0913-T89.5", "outcome": 0}]

    class _Supa:
        def table(self, name):
            return _Q(forecasts if name == "journal_forecasts" else settlements)

    samples = load_samples(_Supa())
    # The unsettled row and the other version's row are both excluded;
    # outcomes arrive as ints from fetch_settlements and become hits.
    assert [(s.prob, s.hit) for s in samples] == [(0.7, True), (0.3, False)]
    assert all(s.event_close.hour == 13 for s in samples)  # 13:00 Eastern close


def test_pairs_before_is_strict_and_the_fit_reports_its_training_through():
    samples = _batch(0.6, 5, 10, C0) + _batch(0.6, 5, 10, C0 + timedelta(hours=1))
    assert pairs_before(samples, C0) == []
    kept = pairs_before(samples, C0 + timedelta(hours=1))
    assert len(kept) == 10 and all(s.event_close == C0 for s in kept)
    m = fit_map(kept)
    assert m.through == C0  # a freeze never trains on its own event or later ones
