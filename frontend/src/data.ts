import { useEffect, useRef, useState } from "react";

// Session-local, bounded data only. No credentials or configuration contents are
// persisted; successful writes invalidate every cached view before it can be reused.
const pending = new Map<string, Promise<any>>();
const views = new Map<string, { data: any; until: number }>();
let generation = 0;
let forcedReads = 0;
const refreshers = new Set<() => Promise<void>>();

export async function refreshVisibleQueries() {
  clearReadCache();
  forcedReads++;
  try {
    const results = await Promise.allSettled(
      [...refreshers].map((refresh) => refresh()),
    );
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") throw failure.reason;
  } finally {
    forcedReads--;
  }
}

export function clearReadCache() {
  generation++;
  pending.clear();
  views.clear();
}

export function api(path: string, method = "GET", body?: any): Promise<any> {
  if (method === "GET" && pending.has(path)) return pending.get(path)!;
  const request = (async () => {
    const response = await fetch("/api/v1" + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-Netrix-Request": "1",
        ...(method === "GET" && forcedReads
          ? { "Cache-Control": "no-cache" }
          : {}),
      },
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      ...(method === "GET" ? { signal: AbortSignal.timeout(30000) } : {}),
    });
    if (method !== "GET" && response.ok) clearReadCache();
    if (response.status === 204) return null;
    const data = await response
      .json()
      .catch(() => ({ detail: "Sunucu yanıtı okunamadı" }));
    if (!response.ok) {
      if (response.status === 401) {
        clearReadCache();
        if (!path.startsWith("/auth/"))
          window.dispatchEvent(new Event("netrix:session-expired"));
      }
      throw new Error(
        Array.isArray(data.detail)
          ? data.detail
              .map((x: any) => x.loc.join(".") + ": " + x.msg)
              .join(" · ")
          : data.detail || "İşlem tamamlanamadı",
      );
    }
    return data;
  })();
  if (method === "GET") {
    pending.set(path, request);
    const release = () => {
      if (pending.get(path) === request) pending.delete(path);
    };
    request.then(release, release);
  }
  return request;
}

function cached(key: string | null) {
  const value = key ? views.get(key) : undefined;
  return value && value.until > Date.now() ? value.data : undefined;
}

// A live update queues one follow-up read. It never cancels the first response
// or clears a populated table. Only navigation to a different query discards it.
export function useLiveQuery<T = any>(
  key: string | null,
  refresh = 0,
  load: () => Promise<T> = () => api(key!),
  delay = 0,
) {
  const loader = useRef(load);
  loader.current = load;
  const [state, setState] = useState<{
    key: string | null;
    data?: T;
    error: string;
    settled: boolean;
  }>(() => ({ key, data: cached(key), error: "", settled: false }));
  const control = useRef<{ refresh: number; request: () => void } | null>(null);
  useEffect(() => {
    if (!key) {
      control.current = null;
      return;
    }
    let active = true,
      running = false,
      again = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let waiters: { resolve: () => void; reject: (error: unknown) => void }[] =
      [];
    setState({ key, data: cached(key), error: "", settled: false });
    const run = async () => {
      timer = undefined;
      if (!active) return;
      if (running) {
        again = true;
        return;
      }
      running = true;
      const version = generation;
      let failure: unknown;
      try {
        const data = await loader.current();
        if (active && version === generation) {
          views.delete(key);
          views.set(key, { data, until: Date.now() + 30000 });
          if (views.size > 100) views.delete(views.keys().next().value!);
          setState({ key, data, error: "", settled: true });
        } else if (active) again = true;
      } catch (e: any) {
        failure = e;
        if (active)
          setState((s) => ({
            ...s,
            key,
            error:
              e.name === "TimeoutError"
                ? "Sunucu yanıtı zaman aşımına uğradı. Yeniden deneyin."
                : e.message,
            settled: true,
          }));
      } finally {
        running = false;
        if (active && again) {
          again = false;
          timer = setTimeout(run, 250);
        } else {
          const done = waiters;
          waiters = [];
          done.forEach((waiter) =>
            failure ? waiter.reject(failure) : waiter.resolve(),
          );
        }
      }
    };
    control.current = {
      refresh,
      request: () => {
        if (running) again = true;
        else if (!timer) timer = setTimeout(run, 100);
      },
    };
    const refreshNow = () =>
      new Promise<void>((resolve, reject) => {
        waiters.push({ resolve, reject });
        control.current?.request();
      });
    refreshers.add(refreshNow);
    timer = setTimeout(run, delay);
    return () => {
      active = false;
      clearTimeout(timer);
      refreshers.delete(refreshNow);
      waiters.forEach((waiter) => waiter.resolve());
    };
  }, [key]);
  useEffect(() => {
    if (control.current && control.current.refresh !== refresh) {
      control.current.refresh = refresh;
      control.current.request();
    }
  }, [refresh]);
  const current =
    state.key === key
      ? state
      : { data: cached(key), error: "", settled: false };
  return {
    data: current.data as T | undefined,
    error: current.error,
    loading: !!key && !current.settled && current.data === undefined,
  };
}
