"use client";

/**
 * The authenticated session, built from the backend's own answer.
 *
 * On load the provider restores the session through the httpOnly refresh cookie, then asks the
 * backend who the user is (`/me/workspace`): role, department, courses coordinated, classes
 * taught, terms and capabilities. Nothing about the user is decided in the browser; the UI is
 * generated from that response, and every capability is enforced again by the API.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, AlertTriangle, X } from "lucide-react";
import { onUnauthenticated, refreshSession, sessionLogin, sessionLogout } from "@/lib/api/http";
import { workspaceApi } from "@/lib/api/endpoints";
import type { ScopeFilters, SemesterPeriod, Workspace } from "@/lib/api/types";

type Status = "loading" | "anonymous" | "authenticated";
type Toast = { id: number; title: string; detail?: string; tone: "success" | "error" | "info" };
export type Period = { academic_year: string | null; semester: SemesterPeriod };

type SessionValue = {
  status: Status;
  workspace: Workspace | null;
  period: Period;
  setPeriod: (period: Period) => void;
  login: (email: string, password: string) => Promise<Workspace>;
  logout: () => Promise<void>;
  reloadWorkspace: () => Promise<void>;
  notify: (title: string, detail?: string, tone?: Toast["tone"]) => void;
};

const Context = createContext<SessionValue | null>(null);
const PERIOD_KEY = "acadlytics.period.v2";

function defaultPeriod(ws: Workspace | null): Period {
  return { academic_year: ws?.current_term?.academic_year ?? null, semester: (ws?.current_term?.semester ?? "YEAR") as SemesterPeriod };
}

function savedPeriod(userId: string): Period | null {
  try {
    const raw = window.localStorage.getItem(`${PERIOD_KEY}.${userId}`);
    return raw ? (JSON.parse(raw) as Period) : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [period, setPeriodState] = useState<Period>({ academic_year: null, semester: "YEAR" });
  const [toasts, setToasts] = useState<Toast[]>([]);

  const adopt = useCallback((ws: Workspace) => {
    setWorkspace(ws);
    const saved = savedPeriod(ws.user.id);
    const valid = saved && (saved.academic_year === null || ws.academic_years.includes(saved.academic_year));
    setPeriodState(valid ? saved : defaultPeriod(ws));
    setStatus("authenticated");
  }, []);

  useEffect(() => {
    let alive = true;
    onUnauthenticated(() => {
      setWorkspace(null);
      setStatus("anonymous");
    });
    (async () => {
      const token = await refreshSession();
      if (!alive) return;
      if (!token) return setStatus("anonymous");
      try {
        adopt(await workspaceApi.get());
      } catch {
        if (alive) setStatus("anonymous");
      }
    })();
    return () => {
      alive = false;
    };
  }, [adopt]);

  const login = useCallback(async (email: string, password: string) => {
    await sessionLogin(email, password);
    const ws = await workspaceApi.get();
    adopt(ws);
    return ws;
  }, [adopt]);

  const logout = useCallback(async () => {
    await sessionLogout();
    setWorkspace(null);
    setStatus("anonymous");
  }, []);

  const reloadWorkspace = useCallback(async () => {
    setWorkspace(await workspaceApi.get());
  }, []);

  const setPeriod = useCallback((next: Period) => {
    setPeriodState(next);
    if (workspace) {
      try {
        window.localStorage.setItem(`${PERIOD_KEY}.${workspace.user.id}`, JSON.stringify(next));
      } catch {
        /* storage unavailable: the choice lasts for this visit */
      }
    }
  }, [workspace]);

  const notify = useCallback((title: string, detail?: string, tone: Toast["tone"] = "success") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-2), { id, title, detail, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 5200);
  }, []);

  const value = useMemo(
    () => ({ status, workspace, period, setPeriod, login, logout, reloadWorkspace, notify }),
    [status, workspace, period, setPeriod, login, logout, reloadWorkspace, notify],
  );
  return (
    <Context.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div className={`toast toast-${t.tone}`} key={t.id} role="status">
            <span className="toast-icon">{t.tone === "error" ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}</span>
            <div>
              <b>{t.title}</b>
              {t.detail && <p>{t.detail}</p>}
            </div>
            <button onClick={() => setToasts((c) => c.filter((x) => x.id !== t.id))} aria-label="Dismiss notification"><X size={16} /></button>
          </div>
        ))}
      </div>
    </Context.Provider>
  );
}

export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}

/** The workspace, for pages rendered inside the authenticated shell. */
export function useWorkspace(): Workspace {
  const { workspace } = useSession();
  if (!workspace) throw new Error("useWorkspace outside the authenticated shell");
  return workspace;
}

/**
 * Scope filters for the current page: the global period, overridden by `?year=` / `?sem=`,
 * plus any entity ids in the URL — so every view is shareable as a link.
 */
export function useScope(fixed: ScopeFilters = {}): ScopeFilters {
  const { period } = useSession();
  const params = useSearchParams();
  const year = params.get("year");
  const sem = params.get("sem") as SemesterPeriod | null;
  const fromUrl: ScopeFilters = {};
  for (const key of ["department_id", "course_id", "section_id", "faculty_id", "coordinator_id", "offering_id"] as const) {
    const value = params.get(key);
    if (value) fromUrl[key] = value;
  }
  return {
    academic_year: year ?? period.academic_year,
    semester: sem ?? period.semester,
    ...fromUrl,
    ...fixed,
  };
}

export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const set = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, value);
      }
      const text = next.toString();
      router.replace(text ? `${pathname}?${text}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );
  return { params, set };
}
