"use client";

/**
 * A short, role-aware welcome tour: four or five steps in a small card in the corner.
 *
 * It never blocks the application (no overlay, no focus trap; the page stays usable behind it),
 * can be skipped at any step, and is remembered per user on this device in localStorage — the
 * same pattern as the academic period. Settings has "Replay tour", which fires
 * `acadlytics:tour-replay`. Steps only mention destinations the user's role actually has
 * (from the same backend capabilities the sidebar uses). No backend state.
 */
import { useEffect, useState } from "react";
import { Compass, X } from "lucide-react";
import type { Workspace } from "@/lib/api/types";

const KEY = "acadlytics.tour.v1";
export const TOUR_REPLAY_EVENT = "acadlytics:tour-replay";

type Step = { title: string; body: string };

export function tourSteps(ws: Workspace): Step[] {
  const caps = ws.capabilities;
  const role = ws.user.role;
  const where = role === "ADMIN" ? "the whole institution" : ws.department?.name ?? "your scope";
  const finish: Step = { title: "Reports and your account", body: "Reports exports PDF, Excel or CSV from the same numbers you see on screen. Settings has your password, the default academic period, your department's thresholds and this tour, if you want it again." };
  switch (role) {
    case "FACULTY":
      return [
        { title: "Your classes at a glance", body: "Home shows how your classes are doing: averages, pass rate, completion, trends and who needs attention — all from the marks you have uploaded." },
        { title: "My classes", body: "Under Academic Management, open a class for its marks grid, assessments, attention flags, interventions and class reports." },
        { title: "Import TLP marks", body: "Under Data & Imports, drop your TLP reports. Every problem is shown before anything is written, and nothing is saved until you confirm." },
        { title: "Student support", body: "Attention lists students who meet the configured rules, each with the evidence. Record an intervention and later see what was observed at the next assessment." },
        finish,
      ];
    case "COURSE_COORDINATOR":
      return [
        { title: "Your courses across every section", body: "Home compares every section and faculty member teaching your courses." },
        { title: "Courses, sections and faculty", body: `Academic Management lists your courses and their sections.${caps.assign_faculty ? " You can assign faculty to a class from the class page." : ""}` },
        { title: "Performance intelligence", body: "Analytics and Assessments compare the same assessment across sections, with distributions and trends." },
        { title: "Imports", body: "Data & Imports accepts TLP reports for any section of your courses; you review and confirm them." },
        finish,
      ];
    case "ACADEMIC_HEAD":
      return [
        { title: "The course portfolio", body: `Home shows every course of ${where} and how each is performing.` },
        { title: "Coordinators", body: "Academic Management → Coordinators is where you appoint and see the Course Coordinators of each course." },
        { title: "Courses and faculty", body: "Courses, Sections and Faculty let you compare performance across the portfolio and drill into any class." },
        { title: "Performance and support", body: "Analytics compares any slice; Attention and Interventions show where students need support across the department." },
        finish,
      ];
    case "HOD":
      return [
        { title: "Your department", body: `Home is the overview of ${where}: courses, sections, faculty, attention and recent imports.` },
        { title: "Academic management", body: "Courses, Sections, Classes, Faculty and Team & roles cover the whole department; open any of them to drill down." },
        { title: "Student support", body: "Attention and Interventions show which students meet the configured rules across the department and what was done." },
        caps.manage_users
          ? { title: "People", body: "Administration → People is where you add staff below you and set their passwords (faculty created from TLP reports need one before they can sign in)." }
          : { title: "Performance intelligence", body: "Analytics compares any slice of the department with the same engine as the class pages." },
        finish,
      ];
    default:
      return [
        { title: "The whole institution", body: "Home is the institution-wide view across every department. Nothing is filtered to one department for the Administrator." },
        { title: "Administration", body: "People manages every account and role (there is exactly one Administrator), Academic structure holds semesters, departments, courses and sections, and the Audit log records every change." },
        { title: "Academic management", body: "Departments, Courses, Sections, Classes, Faculty and Team & roles drill into any part of the institution." },
        { title: "Data & Imports", body: "TLP reports set up semesters, courses, sections, faculty and students from the files themselves; nothing is written until confirmed." },
        finish,
      ];
  }
}

function storageKey(userId: string) {
  return `${KEY}.${userId}`;
}

function seen(userId: string): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(storageKey(userId)) === "done";
  } catch {
    return false; // storage unavailable: show it on this visit
  }
}

function markSeen(userId: string) {
  try { window.localStorage.setItem(storageKey(userId), "done"); } catch { /* the choice lasts for this visit */ }
}

/** Rendered only inside the signed-in shell, so it mounts once per signed-in user. */
export function Tour({ workspace }: { workspace: Workspace }) {
  const steps = tourSteps(workspace);
  const userId = workspace.user.id;
  const [step, setStep] = useState<number | null>(() => (seen(userId) ? null : 0));

  useEffect(() => {
    const replay = () => setStep(0);
    window.addEventListener(TOUR_REPLAY_EVENT, replay);
    return () => window.removeEventListener(TOUR_REPLAY_EVENT, replay);
  }, []);

  const finish = () => {
    markSeen(userId);
    setStep(null);
  };

  useEffect(() => {
    if (step === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      markSeen(userId);
      setStep(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, userId]);

  if (step === null) return null;
  const current = steps[step];
  const last = step === steps.length - 1;
  return (
    <section className="tour" role="dialog" aria-modal="false" aria-labelledby="tour-title" aria-describedby="tour-body">
      <div className="tour-head">
        <span className="tour-icon" aria-hidden="true"><Compass size={16} /></span>
        <small className="muted">Welcome tour · {step + 1} of {steps.length}</small>
        <button className="btn btn-ghost btn-icon btn-sm" onClick={finish} aria-label="Close tour"><X size={16} /></button>
      </div>
      <h2 id="tour-title">{current.title}</h2>
      <p id="tour-body">{current.body}</p>
      <div className="tour-dots" aria-hidden="true">{steps.map((_, i) => <i key={i} className={i === step ? "on" : ""} />)}</div>
      <div className="tour-actions">
        <button className="btn btn-sm btn-ghost" onClick={finish}>Skip tour</button>
        <div style={{ display: "flex", gap: 8 }}>
          {step > 0 && <button className="btn btn-sm" onClick={() => setStep(step - 1)}>Back</button>}
          <button className="btn btn-sm btn-primary" onClick={() => (last ? finish() : setStep(step + 1))}>{last ? "Done" : "Next"}</button>
        </div>
      </div>
    </section>
  );
}

/** For Settings: show the tour again now. */
export function replayTour() {
  window.dispatchEvent(new Event(TOUR_REPLAY_EVENT));
}
