import type { HTMLAttributes, ReactNode } from "react";
import { rateTone } from "@/lib/format";

/** Shared building blocks; styles live in globals.css. */

export function PageHeader({ title, subtitle, children }: { title: ReactNode; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <section className="hero">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="btn-row">{children}</div>}
    </section>
  );
}

const STATUS_TONES: Record<string, string> = {
  running: "status-running", completed: "status-completed", failed: "status-failed", canceled: "status-canceled"
};

/** Job status, or an attempt outcome when `status` is "completed"/"failed" with a custom label. */
export function StatusPill({ status, label }: { status: string; label?: string }) {
  return <span className={["pill", STATUS_TONES[status]].filter(Boolean).join(" ")}>{label ?? status}</span>;
}

type MeterProps = {
  rate: number;
  /** "auto" colours a pass rate (red/amber/green); "neutral" is for shares that are not pass rates. */
  tone?: "auto" | "neutral" | "brand";
  small?: boolean;
  /** Exposes the meter as a progressbar; otherwise it is decorative next to a printed value. */
  progress?: { label: string; now: number; max: number };
};

export function Meter({ rate, tone = "auto", small = false, progress }: MeterProps) {
  const fill = tone === "neutral" ? "bar-fill tone-neutral" : tone === "brand" ? "bar-fill" : rateTone(rate);
  const a11y = progress
    ? { role: "progressbar", "aria-label": progress.label, "aria-valuemin": 0, "aria-valuemax": progress.max, "aria-valuenow": progress.now }
    : { "aria-hidden": true };
  return (
    <div className={small ? "bar-track mini-bar" : "bar-track"} {...a11y}>
      <div className={fill} style={{ width: `${Math.max(0, Math.min(1, rate)) * 100}%` }} />
    </div>
  );
}

export function Pager({ offset, count, total, pageSize, loading = false, onPage }: {
  offset: number; count: number; total: number; pageSize: number; loading?: boolean; onPage: (offset: number) => void;
}) {
  if (!total) return null;
  return (
    <div className="pager">
      <p className="meta">Showing {count ? offset + 1 : 0}-{count ? offset + count : 0} of {total}</p>
      {total > pageSize && <div className="btn-row">
        <button className="btn btn-secondary" type="button" disabled={loading || offset === 0}
          onClick={() => onPage(Math.max(0, offset - pageSize))}>Previous</button>
        <button className="btn btn-secondary" type="button" disabled={loading || offset + count >= total}
          onClick={() => onPage(offset + pageSize)}>Next</button>
      </div>}
    </div>
  );
}

export function Notice({ tone, title, children, ...rest }: {
  tone: "error" | "success"; title?: ReactNode; children?: ReactNode;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`notice notice-${tone}`} {...rest}>
      {title && <strong className={tone}>{title}</strong>}
      {children}
    </div>
  );
}
