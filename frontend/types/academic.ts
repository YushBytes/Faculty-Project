export type Student = { id: string; name: string; studentNo: string; course: string; latest: number; change: number; status: "On track" | "Review" | "Support" };
export type Assessment = { id: string; title: string; course: string; date: string; average: number; students: number; threshold: number };
export type Intervention = { id: string; student: string; course: string; action: string; status: "In progress" | "Completed"; date: string; outcome: string };

