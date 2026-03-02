"""Formatting helpers used across the Streamlit dashboard."""

from __future__ import annotations


def pct(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.{digits}f}%"


def score(value: float | int | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def ms(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f} ms"


def as_int(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}"


def delta_label(delta: float, positive_is_good: bool = True) -> str:
    if abs(delta) < 1e-9:
        return "unchanged"

    improved = delta > 0 if positive_is_good else delta < 0
    return "improved" if improved else "worsened"
