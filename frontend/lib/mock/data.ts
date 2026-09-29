import type { Assessment, Intervention, Student } from "@/types/academic";

// All records here are fictional demo data. Replace the adapter, not page compositions.
export const students: Student[] = [
  { id: "STU-2041", name: "Aarav Sharma", studentNo: "STU-2041", course: "Data Structures · CSE-A", latest: 78, change: 6, status: "On track" },
  { id: "STU-1982", name: "Diya Menon", studentNo: "STU-1982", course: "Data Structures · CSE-A", latest: 42, change: -14, status: "Review" },
  { id: "STU-2136", name: "Ishaan Kapoor", studentNo: "STU-2136", course: "Database Systems · CSE-B", latest: 38, change: -5, status: "Support" },
  { id: "STU-1877", name: "Meera Iyer", studentNo: "STU-1877", course: "Data Structures · CSE-A", latest: 84, change: 9, status: "On track" },
  { id: "STU-2204", name: "Kabir Das", studentNo: "STU-2204", course: "Database Systems · CSE-B", latest: 53, change: 2, status: "Review" },
  { id: "STU-2018", name: "Sara Thomas", studentNo: "STU-2018", course: "Operating Systems · CSE-A", latest: 67, change: -2, status: "On track" },
  { id: "STU-2150", name: "Rohan Nair", studentNo: "STU-2150", course: "Operating Systems · CSE-A", latest: 45, change: -11, status: "Review" },
  { id: "STU-1929", name: "Ananya Roy", studentNo: "STU-1929", course: "Database Systems · CSE-B", latest: 91, change: 4, status: "On track" },
];

export const assessments: Assessment[] = [
  { id: "ASM-024", title: "Mid-semester examination", course: "Data Structures · CSE-A", date: "24 Sep 2026", average: 68, students: 42, threshold: 50 },
  { id: "ASM-023", title: "Practical assessment 02", course: "Database Systems · CSE-B", date: "17 Sep 2026", average: 72, students: 38, threshold: 50 },
  { id: "ASM-022", title: "Quiz 03", course: "Operating Systems · CSE-A", date: "09 Sep 2026", average: 64, students: 44, threshold: 50 },
  { id: "ASM-021", title: "Practical assessment 01", course: "Data Structures · CSE-A", date: "02 Sep 2026", average: 63, students: 42, threshold: 50 },
];

export const interventions: Intervention[] = [
  { id: "INT-014", student: "Diya Menon", course: "Data Structures · CSE-A", action: "One-to-one review", status: "In progress", date: "25 Sep 2026", outcome: "Review after next assessment" },
  { id: "INT-013", student: "Ishaan Kapoor", course: "Database Systems · CSE-B", action: "Study plan shared", status: "In progress", date: "22 Sep 2026", outcome: "Review after next assessment" },
  { id: "INT-011", student: "Rohan Nair", course: "Operating Systems · CSE-A", action: "Office hours", status: "Completed", date: "18 Sep 2026", outcome: "Score increased 5 points" },
];

export const trend = [
  { name: "Wk 1", score: 61 }, { name: "Wk 2", score: 64 }, { name: "Wk 3", score: 62 },
  { name: "Wk 4", score: 68 }, { name: "Wk 5", score: 71 }, { name: "Wk 6", score: 68 },
];

