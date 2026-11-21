import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "LLM Reliability",
  description: "Create evaluation jobs, review failures and traces, and export reliability reports."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <Link href="/jobs" className="brand"><span className="brand-mark" aria-hidden="true" />LLM Reliability</Link>
            <nav aria-label="Primary" className="topbar-nav">
              <Link href="/jobs">Jobs</Link>
              <Link href="/compare">Compare</Link>
              <Link href="/jobs/new">New job</Link>
            </nav>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
