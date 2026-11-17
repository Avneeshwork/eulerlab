"""Polynomial autoregression deviation.

Source: Cohen, G. (2023). Intraday trading of cryptocurrencies using polynomial auto
regression. AIMS Mathematics 8(4): 9782-9794. DOI 10.3934/math.2023493.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _plan


def _poly_fit_next(values: Sequence[float], degree: int = 2) -> float | None:
    """Where a degree-2 least-squares fit says the next point should sit.

    Cohen (2023) fits a polynomial autoregression to recent minute closes and
    trades the gap between price and that line. Solved by normal equations on a
    tiny system rather than pulling in numpy: the window is dozens of points and
    a dependency for a 3x3 solve would cost more than it saves.
    """
    n = len(values)
    if n < degree + 2:
        return None
    xs = list(range(n))
    # Normal equations for a degree-2 fit: sums of x^k up to x^4.
    powers = [sum(x**k for x in xs) for k in range(2 * degree + 1)]
    targets = [sum((x**k) * y for x, y in zip(xs, values, strict=True)) for k in range(degree + 1)]
    size = degree + 1
    matrix = [
        [float(powers[row + col]) for col in range(size)] + [float(targets[row])]
        for row in range(size)
    ]

    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            return None
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for row in range(size):
            if row == col:
                continue
            factor = matrix[row][col] / matrix[col][col]
            for k in range(col, size + 1):
                matrix[row][k] -= factor * matrix[col][k]
    coeffs = [matrix[i][size] / matrix[i][i] for i in range(size)]
    return float(sum(c * (n**i) for i, c in enumerate(coeffs)))


def par_deviation(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """Price above a polynomial fit of recent closes, by more than a buffer.

    Cohen fits a polynomial autoregression to intraday closes and takes a long
    when `P_i > Pol_i + delta`, short when below. The buffer exists to suppress
    the false entries a bare crossing generates; his best Bitcoin result used
    67-minute bars, so this is a shorter-horizon variant of the same rule.
    """
    if len(window) < rules.ou_lookback + 2:
        return Rejected("warmup")
    closes = [c.close for c in window[-rules.ou_lookback :]]
    fit = _poly_fit_next(closes)
    if fit is None or fit <= 0:
        return Rejected("no fit")

    signal = window[-1]
    buffer = fit * (rules.min_risk_pct / 100.0)
    if signal.close <= fit + buffer:
        return Rejected("inside the buffer", f"{(signal.close / fit - 1) * 100:.3f}%")

    return _plan(signal=signal, entry=signal.close, stop=fit, rules=rules, equity=equity)


SIGNALS = (
    CryptoSignal(
        "par_deviation",
        "Polynomial autoregression deviation",
        "paper",
        "Cohen, G. (2023). Intraday trading of cryptocurrencies using polynomial "
        "auto regression. AIMS Mathematics 8(4): 9782-9794. DOI 10.3934/math.2023493",
        "Net profit 15.58% on Bitcoin using 67-minute bars against -44.8% buy-and-hold, "
        "over six months of out-of-sample trading",
        (
            "Fit a degree-2 least-squares curve to the last 60 minute closes.",
            "Project it one bar forward to get the expected price.",
            "Go long when the close exceeds that projection by a buffer.",
            "Stop at the projection line itself.",
        ),
        par_deviation,
    ),
)
