"""Formatting helpers used across the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd


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


def dt(value: object) -> str:
    if value is None:
        return "-"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return "-"
    return parsed.strftime("%Y-%m-%d %H:%M")


def mode_badge(mode: str | None) -> str:
    normalized = (mode or "unknown").strip().lower()
    if normalized == "mock":
        return "MOCK"
    if normalized == "real":
        return "REAL API"
    if normalized == "offline_replay":
        return "OFFLINE REPLAY"
    return normalized.upper()
