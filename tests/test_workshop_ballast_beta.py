"""Step 12 (product item 4): the ballast claim must be falsifiable.

"Loses less than SPY on SPY's down days" passes by definition for any
low-beta asset -- a fifth of SPY and four fifths cash cushions exactly
as much as its beta says, with no skill in it. The claim is now judged
against an equal-beta SPY-plus-cash mix: the idea must cushion MORE
than a mechanical mix with the same beta to SPY (beta clipped to
[0, 1], the cash leg earning 0). The statistic, the holds rule and the
sign-flip terms all use the mix, so the critic's live ruler (which
delegates to engine._claim) tightens with the backtest.
"""

import numpy as np

from tradehub.workshop import engine

MASK = np.ones(60, dtype=bool)


def _spy(n=60):
    out = np.full(n, 0.01)
    out[1::2] = -0.01
    return out


def test_mechanical_low_beta_no_longer_passes():
    s = _spy()
    r = 0.2 * s                      # exactly a 20/80 SPY/cash mix, no alpha
    holds, value, label = engine._claim("ballast", r, s, s, MASK)
    assert holds is False            # the old rule passed this by definition
    assert abs(value) < 1e-9         # cushions exactly the mix's amount: 0
    assert "equal-beta" in label


def test_real_cushion_beyond_beta_passes():
    s = _spy()
    r = 0.2 * s + 0.0005             # same beta, a little better every day
    holds, value, _ = engine._claim("ballast", r, s, s, MASK)
    assert holds is True
    assert value > 0.04              # ~+0.05% per down day beyond the mix


def test_levered_beta_is_clipped_to_the_mix_bar():
    s = _spy()
    r = 2.0 * s                      # beta 2 clips to 1: the bar is SPY itself
    holds, value, _ = engine._claim("ballast", r, s, s, MASK)
    assert holds is False
    assert value < 0


def test_signflip_terms_match_the_claim_statistic():
    s = _spy()
    r = 0.2 * s + 0.0005
    _holds, value, _ = engine._claim("ballast", r, s, s, MASK)
    terms = engine._signflip_terms("ballast", r, s, s)
    assert abs(float(np.mean(terms)) * 100 - value) < 1e-9


def test_mechanical_mix_with_drift_and_noise_never_holds():
    # Claude's review of the step-12 PR: with SPY drifting +0.0008/day
    # plus noise, a mechanical 20/80 series could land a few float ulps
    # above its own mix and "hold" on rounding alone (171 of 500 random
    # series held under the bare comparison). The epsilon in the holds
    # rule must keep every one of them out.
    rng = np.random.default_rng(20261119)
    for _ in range(200):
        s = 0.0008 + rng.normal(0.0, 0.01, 250)
        r = 0.2 * s                  # the mix itself, no cushion in it
        holds, _value, _label = engine._claim(
            "ballast", r, s, s, np.ones(250, dtype=bool))
        assert holds is False


def test_rising_on_down_days_still_passes():
    s = _spy()
    r = np.where(s < 0, 0.002, -0.003)   # up when SPY falls, down harder otherwise
    # Overall growth is negative, so the (mine > mix and total > 0) branch
    # cannot be what passes this: the independent mine > 0 allowance is
    # the branch under test (CodeRabbit's note on the step-12 PR).
    assert float(np.prod(1 + r) - 1) < 0
    holds, value, _ = engine._claim("ballast", r, s, s, MASK)
    assert holds is True
    assert value > 0
