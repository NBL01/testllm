"use client";

import { useEffect, useRef, useState } from "react";

/** Query changes discard old data; refresh/poll keeps the last successful snapshot. */
export function useRemoteResource<T>(key: string | null, load: () => Promise<T>, refresh = 0, pollMs = 0) {
  const revision = JSON.stringify([key, refresh, pollMs]);
  const [snapshot, setSnapshot] = useState<{ key: string | null; revision: string; data: T | null; error: string; loading: boolean }>({
    key: null, revision: "", data: null, error: "", loading: true
  });
  const latest = useRef({ revision, load });
  latest.current = { revision, load };

  useEffect(() => {
    if (key === null) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const isCurrent = () => active && latest.current.revision === revision;
    async function read() {
      if (!isCurrent()) return;
      setSnapshot(previous => ({
        key,
        revision,
        data: previous.key === key ? previous.data : null,
        error: previous.key === key ? previous.error : "",
        loading: !(previous.key === key && previous.revision === revision && previous.data !== null)
      }));
      try {
        const data = await latest.current.load();
        if (isCurrent()) setSnapshot({ key, revision, data, error: "", loading: false });
      } catch (error) {
        if (isCurrent()) setSnapshot(previous => ({
          key, revision, data: previous.key === key ? previous.data : null,
          error: error instanceof Error ? error.message : "Request failed. Please refresh to retry.", loading: false
        }));
      } finally {
        // Schedule after completion: slow GETs never overlap or starve the display.
        if (isCurrent() && pollMs) timer = setTimeout(() => void read(), pollMs);
      }
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [key, revision, pollMs]);

  if (key === null) return { data: null, error: "", loading: false };
  if (snapshot.key !== key) return { data: null, error: "", loading: true };
  // Invalidate during render, not in the later effect: actions must stay disabled
  // between a POST settling and its persisted-state refresh starting.
  if (snapshot.revision !== revision) return { ...snapshot, loading: true };
  return snapshot;
}
