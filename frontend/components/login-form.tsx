"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight, Building2, Check, CircleDot, Eye, EyeOff, LockKeyhole, ShieldCheck, UserRound, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useAuth, type UserRole } from "@/lib/auth/session";

const demoUsers = {
  faculty: { email: "faculty@srmist.edu", name: "Dr. Ananya Rao", department: "Computer Science and Engineering", role: "faculty" as const, password: "SRMdemo2026!" },
  hod: { email: "hod@srmist.edu", name: "Dr. Meera Krishnan", department: "Computer Science and Engineering", role: "hod" as const, password: "SRMdemo2026!" },
};

const bootSteps = ["Connecting to academic workspace", "Loading academic records", "Processing assessments", "Building class insights", "Preparing attention center", "Rendering your dashboard"];

export function LoginForm() {
  const router = useRouter();
  const { login, ready, user, semester } = useAuth();
  const reduceMotion = useReducedMotion();
  const [role, setRole] = useState<UserRole>("faculty");
  const [email, setEmail] = useState(demoUsers.faculty.email);
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [transition, setTransition] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => { if (ready && user && !transition) router.replace("/dashboard"); }, [ready, user, transition, router]);

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading || transition) return;
    setError("");
    setLoading(true);
    const expected = demoUsers[role];
    window.setTimeout(() => {
      if (email.trim().toLowerCase() !== expected.email || password !== expected.password) {
        setError(`Use the ${role === "faculty" ? "Faculty" : "HOD"} demo email and password shown below.`);
        setLoading(false);
        return;
      }
      login({ email: expected.email, name: expected.name, department: expected.department, role: expected.role }, remember);
      setLoading(false);
      setTransition(true);
      if (reduceMotion) {
        router.replace("/dashboard");
        return;
      }
      let index = 0;
      const advance = () => {
        index += 1;
        setStep(index);
        if (index < bootSteps.length) window.setTimeout(advance, 245);
        else window.setTimeout(() => router.replace("/dashboard"), 240);
      };
      window.setTimeout(advance, 520);
    }, 420);
  }

  return <main className="login-page"><Link className="login-back" href="/"><ArrowLeft size={15} /> Back to ACADLYTICS</Link>
    <section className="login-card login-card-srm">
      <div className="login-brand"><span className="brand-mark"><CircleDot size={18} /></span><span>ACADLYTICS</span></div>
      <div className="institution-lockup"><span><Building2 size={15} /></span><div><b>SRM Institute of Science and Technology</b><small>Faculty academic workspace</small></div></div>
      <div className="login-eyebrow"><span /> SECURE DEMO SIGN-IN</div>
      <h1>Welcome back.</h1><p className="login-subtitle">Sign in to review your academic workspace.</p>
      <div className="role-picker" role="group" aria-label="Choose your role">
        {(["faculty", "hod"] as const).map((item) => <button type="button" key={item} aria-pressed={role === item} className={role === item ? "role-choice active" : "role-choice"} onClick={() => { setRole(item); setEmail(demoUsers[item].email); setError(""); }}><span className="role-choice-icon">{item === "faculty" ? <UserRound size={16} /> : <Building2 size={16} />}</span><span><b>{item === "faculty" ? "Faculty" : "Head of Department"}</b><small>{item === "faculty" ? "My courses and students" : "Department-wide overview"}</small></span><span className="role-choice-check"><Check size={12} /></span></button>)}
      </div>
      <form className="login-form" onSubmit={submit}>
        <label className="form-label">INSTITUTIONAL EMAIL<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label className="form-label">PASSWORD<span className="password-wrap"><input type={show ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" required minLength={8} /><button type="button" aria-label={show ? "Hide password" : "Show password"} onClick={() => setShow(!show)}>{show ? <EyeOff size={16} /> : <Eye size={16} />}</button></span></label>
        <div className="login-options"><label className="remember-option"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> Remember me</label><button type="button" className="forgot-link" onClick={() => setForgot(!forgot)}>Forgot password?</button></div>
        {forgot && <p className="recovery-note" role="status">Password recovery will be available when SRM authentication is connected. For this demo, use the credentials below.</p>}
        {error && <p role="alert" className="form-error">{error}</p>}
        <button className="button button-primary login-submit" type="submit" disabled={loading || transition}>{loading ? <><span className="button-spinner" /> Verifying demo access…</> : <>Continue to workspace <ArrowRight size={16} /></>}</button>
      </form>
      <div className="login-demo"><ShieldCheck size={15} /><span><b>Clearly marked demo authentication</b><br />Faculty: {demoUsers.faculty.email}<br />HOD: {demoUsers.hod.email}<br />Password for both: <code>{demoUsers.faculty.password}</code></span></div>
      <p className="login-security"><LockKeyhole size={12} /> Demo only. No password or token is sent to a backend.</p>
    </section>
    <footer className="login-footer">SRM INSTITUTE OF SCIENCE AND TECHNOLOGY <i /> ACADLYTICS · DEMO WORKSPACE</footer>
    <AnimatePresence>{transition && <motion.div className="login-transition" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduceMotion ? 0 : .34 }} aria-live="polite">
        <motion.div className="greeting-card" initial={reduceMotion ? false : { opacity: 0, y: 18, scale: .98, filter: "blur(8px)" }} animate={{ opacity: step > 1 ? 0 : 1, y: step > 1 ? -10 : 0, scale: 1, filter: "blur(0px)" }} transition={{ duration: .55 }}>
        <span className="brand-mark"><CircleDot size={19} /></span><small>SRM INSTITUTE OF SCIENCE AND TECHNOLOGY</small><h2>{new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 17 ? "Good afternoon" : "Good evening"}, {role === "faculty" ? "Professor." : "Head of Department."}</h2><p>Welcome back, {demoUsers[role].name}.</p><div className="greeting-meta"><span>{demoUsers[role].department}</span><b>·</b><span>{semester}</span></div>
      </motion.div>
      <motion.div className="boot-card" initial={{ opacity: 0, y: 12 }} animate={{ opacity: step > 0 ? 1 : 0, y: step > 0 ? 0 : 12 }} transition={{ duration: .45 }}><div className="boot-mark"><CircleDot size={20} /></div><span className="boot-label">ACADEMIC WORKSPACE</span><div className="boot-status">{bootSteps[Math.min(step, bootSteps.length - 1)]}<span className="boot-dots"><i /><i /><i /></span></div><div className="boot-progress"><motion.i initial={{ scaleX: 0 }} animate={{ scaleX: Math.min(step / (bootSteps.length - 1), 1) }} transition={{ duration: .45 }} /></div><div className="boot-steps">{bootSteps.map((label, index) => <span className={index <= step ? "boot-step boot-step-active" : "boot-step"} key={label}>{index < step ? <Check size={11} /> : <i />}{label}</span>)}</div></motion.div>
      <button className="transition-skip" onClick={() => router.replace("/dashboard")}><X size={13} /> Skip intro</button>
    </motion.div>}</AnimatePresence>
  </main>;
}
