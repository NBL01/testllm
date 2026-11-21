import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LLM Reliability Client",
  description: "Client-facing workflow for evaluation jobs and result review."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
