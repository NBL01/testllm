import re


def normalize_answer(value: str | None) -> str:
    """Normalize free-text answers for stable comparison and reporting."""
    if value is None:
        return ""

    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
