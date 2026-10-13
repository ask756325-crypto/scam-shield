"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, buildQuery } from "./api";

type Query = Record<string, string | number | boolean | string[] | undefined | null>;

/** Fetch JSON from the API with loading/error state. Pass null path to skip. */
export function useApi<T>(path: string | null, query?: Query, opts: { pollMs?: number } = {}) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const key = path ? path + buildQuery(query) : null;
  const keyRef = useRef(key);
  keyRef.current = key;

  const load = useCallback(
    async (silent = false) => {
      if (!key || !path) return;
      if (!silent) setLoading(true);
      try {
        const res = await api<T>(path, { query });
        if (keyRef.current === key) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (keyRef.current === key) setError(e as Error);
      } finally {
        if (keyRef.current === key) setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );

  useEffect(() => {
    if (!key) {
      setLoading(false);
      return;
    }
    load();
  }, [key, load]);

  useEffect(() => {
    if (!opts.pollMs || !key) return;
    const id = setInterval(() => load(true), opts.pollMs);
    return () => clearInterval(id);
  }, [opts.pollMs, key, load]);

  return { data, error, loading, reload: load, setData };
}

export function useLocalStorage<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw !== null) setValue(JSON.parse(raw));
    } catch {}
  }, [key]);
  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {}
    },
    [key],
  );
  return [value, set] as const;
}
