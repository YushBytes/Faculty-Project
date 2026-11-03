"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, clearCache } from "@/lib/api/http";

export type ApiState<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

type Slot<T> = { key: string | null; data: T | null; error: ApiError | null };

/**
 * Load data for a view. A change of `key` (filters, ids) refetches; the previous data stays on
 * screen until the new response arrives, and responses for a superseded key are dropped.
 */
export function useApi<T>(load: () => Promise<T>, key: unknown[], enabled = true): ApiState<T> {
  const [nonce, setNonce] = useState(0);
  const [slot, setSlot] = useState<Slot<T>>({ key: null, data: null, error: null });
  const loader = useRef(load);
  const requestKey = JSON.stringify([key, nonce]);

  useEffect(() => {
    loader.current = load;
  });

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    loader.current().then(
      (data) => alive && setSlot({ key: requestKey, data, error: null }),
      (err) =>
        alive &&
        setSlot((s) => ({
          key: requestKey,
          data: s.data,
          error: err instanceof ApiError ? err : new ApiError(0, "network_error", String(err?.message ?? err)),
        })),
    );
    return () => {
      alive = false;
    };
  }, [requestKey, enabled]);

  // An explicit reload always goes to the server.
  const reload = useCallback(() => {
    clearCache();
    setNonce((n) => n + 1);
  }, []);
  return {
    data: slot.data,
    error: slot.key === requestKey ? slot.error : null,
    loading: enabled && slot.key !== requestKey,
    reload,
  };
}
