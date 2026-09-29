"use client";

import { useAuth, type Semester } from "@/lib/auth/session";

const semesters: Semester[] = ["Odd Semester", "Even Semester"];

export function SemesterSelector() {
  const { semester, setSemester } = useAuth();
  return <div className="semester-control" role="group" aria-label="Select academic semester">
    {semesters.map((item) => <button key={item} type="button" aria-pressed={semester === item} className={semester === item ? "semester-option is-selected" : "semester-option"} onClick={() => setSemester(item)}>{item}</button>)}
  </div>;
}
