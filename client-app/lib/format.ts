/** Bar color tier for a 0-1 pass rate; the numeric value is always shown beside it. */
export function rateTone(rate: number): string {
  return rate < 0.5 ? "bar-fill tone-low" : rate < 0.8 ? "bar-fill tone-mid" : "bar-fill";
}

export function formatPercent(rate: number, digits = 0): string {
  return Number.isFinite(rate) ? `${(rate * 100).toFixed(digits)}%` : "n/a";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Milliseconds below a second, seconds above, so slow local models stay readable. */
export function formatMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "n/a";
  return value < 1000 ? `${value.toFixed(0)} ms` : `${(value / 1000).toFixed(1)} s`;
}
