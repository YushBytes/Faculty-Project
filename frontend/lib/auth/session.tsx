"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Info, X } from "lucide-react";

export type UserRole = "faculty" | "hod";
export type Semester = "Odd Semester" | "Even Semester";
export type DemoUser = { email: string; name: string; department: string; role: UserRole };
type AuthContextValue = {
  user: DemoUser | null;
  semester: Semester;
  course: string;
  ready: boolean;
  login: (user: DemoUser, remember: boolean) => void;
  logout: () => void;
  setSemester: (semester: Semester) => void;
  setCourse: (course: string) => void;
  notify: (title: string, detail: string) => void;
};
type Toast = { id: number; title: string; detail: string };

const STORAGE_KEY = "acadlytics.demo-session.v1";
const context = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<DemoUser | null>(null);
  const [semester, setSemesterState] = useState<Semester>("Odd Semester");
  const [course, setCourseState] = useState("All assigned courses");
  const [ready, setReady] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const restoreSession = () => {
      try {
        const raw = localStorage.getItem(STORAGE_KEY) ?? sessionStorage.getItem(STORAGE_KEY);
        if (raw) {
          const saved = JSON.parse(raw) as { user?: DemoUser; semester?: Semester; course?: string };
          if (saved.user?.role === "faculty" || saved.user?.role === "hod") setUser(saved.user);
          if (saved.semester === "Odd Semester" || saved.semester === "Even Semester") setSemesterState(saved.semester);
          if (saved.course) setCourseState(saved.course);
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(STORAGE_KEY);
      }
      setReady(true);
    };
    const frame = window.requestAnimationFrame(restoreSession);
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const persist = useCallback((nextUser: DemoUser | null, nextSemester = semester, nextCourse = course, remember = true) => {
    const storage = remember ? localStorage : sessionStorage;
    const other = remember ? sessionStorage : localStorage;
    other.removeItem(STORAGE_KEY);
    if (nextUser) storage.setItem(STORAGE_KEY, JSON.stringify({ user: nextUser, semester: nextSemester, course: nextCourse }));
  }, [semester, course]);

  const login = useCallback((nextUser: DemoUser, remember: boolean) => {
    setUser(nextUser);
    persist(nextUser, semester, course, remember);
  }, [persist, semester, course]);

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const setSemester = useCallback((next: Semester) => {
    setSemesterState(next);
    if (user) persist(user, next, course, localStorage.getItem(STORAGE_KEY) !== null);
  }, [user, persist, course]);

  const setCourse = useCallback((next: string) => {
    setCourseState(next);
    if (user) persist(user, semester, next, localStorage.getItem(STORAGE_KEY) !== null);
  }, [user, persist, semester]);

  const notify = useCallback((title: string, detail: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-2), { id, title, detail }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4200);
  }, []);

  const value = useMemo(() => ({ user, semester, course, ready, login, logout, setSemester, setCourse, notify }), [user, semester, course, ready, login, logout, setSemester, setCourse, notify]);
  return <context.Provider value={value}>{children}<div className="toast-stack" aria-live="polite" aria-atomic="false">{toasts.map((toast) => <div className="product-toast" key={toast.id}><span className="toast-icon"><CheckCircle2 size={16} /></span><div><b>{toast.title}</b><p>{toast.detail}</p></div><button onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))} aria-label="Dismiss notification"><X size={14} /></button><Info className="toast-accent" size={13} /></div>)}</div></context.Provider>;
}

export function useAuth() {
  const value = useContext(context);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
