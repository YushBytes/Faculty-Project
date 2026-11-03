"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Eye, EyeOff, GraduationCap, LockKeyhole } from "lucide-react";
import { useSession } from "@/lib/auth/session";
import { ApiError } from "@/lib/api/http";
import type { Workspace } from "@/lib/api/types";
import { ROLE_LABEL, initials } from "@/lib/format";

/** The sign-in accounts an empty platform starts with (see backend/app/bootstrap.py), then the
 * Course Coordinator the demo seed appoints (backend/app/demo/srm.py). Faculty accounts are
 * created from the TLP reports as <staff id>@srmist.edu.in. */
const DEMO = [
  ["admin@acadlytics.dev", "Administrator"],
  ["hod.cse@acadlytics.dev", "Head of Department · CSE"],
  ["academic.head@acadlytics.dev", "Academic Head · CSE"],
  ["coord.dsa@acadlytics.dev", "Course Coordinator · DSA"],
];
const STEPS = ["Verifying your account", "Resolving your academic scope", "Loading the current semester", "Preparing your workspace"];

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export function LoginView() {
  const { status, login } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const reduce = useReducedMotion();
  const next = params.get("next") || "/dashboard";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [boot, setBoot] = useState<Workspace | null>(null);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (status === "authenticated" && !boot) router.replace(next);
  }, [status, boot, router, next]);

  useEffect(() => {
    if (!boot) return;
    if (reduce) { router.replace(next); return; }
    const timer = window.setInterval(() => setStep((s) => s + 1), 430);
    const done = window.setTimeout(() => router.replace(next), 430 * STEPS.length + 350);
    return () => { window.clearInterval(timer); window.clearTimeout(done); };
  }, [boot, reduce, router, next]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      setBoot(await login(email.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? (err.status === 401 ? "That email and password do not match an active account." : err.message) : "Sign-in failed. Is the server running?");
      setBusy(false);
    }
  }

  if (boot) {
    const first = boot.user.full_name.replace(/^(Dr|Mr|Ms|Mrs|Prof)\.?\s+/i, "");
    return (
      <div className="boot" role="status">
        <motion.div className="boot-card" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}>
          <span className="avatar">{initials(boot.user.full_name)}</span>
          <h2>{greeting()}, {first}.</h2>
          <p className="inst"><b>{boot.institution}</b><br />{boot.department?.name ?? "All departments"}<br />{boot.headline}</p>
          <div className="boot-progress"><motion.i initial={{ width: "4%" }} animate={{ width: `${Math.min(100, ((step + 1) / STEPS.length) * 100)}%` }} transition={{ duration: 0.4 }} /></div>
          <p className="boot-step">{STEPS[Math.min(step, STEPS.length - 1)]}…</p>
        </motion.div>
      </div>
    );
  }

  return (
    <main className="login-page">
      <section className="login-art">
        <Link className="brand" href="/"><span className="brand-mark"><GraduationCap size={19} /></span>ACADLYTICS</Link>
        <h1>Academic performance, <em>for every level</em> of the institution.</h1>
        <p>Sign in with your institutional account. Your role and scope come from the institution&apos;s records — the workspace is built around them.</p>
        <div className="login-hier">
          {(["ADMIN", "HOD", "ACADEMIC_HEAD", "COURSE_COORDINATOR", "FACULTY"] as const).map((r, i) => (
            <div key={r} style={{ marginLeft: i * 14 }}><b>{ROLE_LABEL[r]}</b>{["Institution", "Department", "Course portfolio", "Course, all sections", "Own classes"][i]}</div>
          ))}
        </div>
      </section>
      <section className="login-panel">
        <div className="login-box">
          <span className="eyebrow"><LockKeyhole size={14} /> SRM Institute of Science and Technology</span>
          <h2>Sign in to ACADLYTICS</h2>
          <p>Use the email and password issued to you.</p>
          <form className="login-form" onSubmit={submit}>
            <label className="field"><span>Email</span><input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@srmist.edu.in" /></label>
            <label className="field"><span>Password</span>
              <div className="pw-wrap"><input className="input" type={show ? "text" : "password"} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
                <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
            </label>
            {error && <div className="notice notice-error" role="alert">{error}</div>}
            <button className="btn btn-primary" style={{ height: 48 }} disabled={busy || status === "loading"}>{busy ? "Signing in…" : <>Sign in <ArrowRight size={17} /></>}</button>
          </form>
          <details className="demo-accounts">
            <summary>Sign-in accounts</summary>
            {DEMO.map(([address, label]) => (
              <div className="acc" key={address}><span><b>{label}</b><br /><span className="muted">{address}</span></span><button type="button" onClick={() => { setEmail(address); setPassword(""); }}>Use</button></div>
            ))}
            <div className="acc"><span className="muted">Course Coordinators exist once they are appointed in <b>Team &amp; roles</b>, or from the demo seed. Faculty sign in with <b>staff id</b>@srmist.edu.in once a TLP report naming them is uploaded. Initial passwords are in the project README.</span></div>
          </details>
        </div>
      </section>
    </main>
  );
}
