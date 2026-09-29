import { assessments, interventions, students, trend } from "@/lib/mock/data";

/** Thin boundary for mock-to-real API replacement. Existing backend base path: /api/v1. */
export interface AcademicDataSource {
  getOverview(): Promise<{ students: typeof students; assessments: typeof assessments; interventions: typeof interventions; trend: typeof trend }>;
}

const mockSource: AcademicDataSource = {
  async getOverview() { return { students, assessments, interventions, trend }; },
};

export const academicApi = mockSource;

