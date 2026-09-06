"use client";

import { useEffect, useRef, useState } from "react";

/** Query changes discard old data; refresh/poll keeps the last successful snapshot. */
export function useRemoteResource<T>(key: string | null, load: () => Promise<T>, refresh = 0, pollMs = 0) {
  const [snapshot, setSnapshot] = useState<{ key: string | null; data: T | null; error: string; loading: boolean }>({
    key: null, data: null, error: "", loading: true
  });
  const latest = useRef({ key, load });
  latest.current = { key, load };

  useEffect(() => {
    if (key === null) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      setSnapshot(previous => ({ key, data: previous.key === key ? previous.data : null, error: "", loading: true }));
      try {
        const data = await latest.current.load();
        if (active && latest.current.key === key) setSnapshot({ key, data, error: "", loading: false });
      } catch (error) {
        if (active && latest.current.key === key) setSnapshot(previous => ({
          key, data: previous.key === key ? previous.data : null,
          error: error instanceof Error ? error.message : "Request failed. Please refresh to retry.", loading: false
        }));
      } finally {
        // Schedule after completion: slow GETs never overlap or starve the display.
        if (active && pollMs) timer = setTimeout(() => void read(), pollMs);
      }
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [key, refresh, pollMs]);

  if (key === null) return { data: null, error: "", loading: false };
  if (snapshot.key !== key) return { data: null, error: "", loading: true };
  return snapshot;
}
