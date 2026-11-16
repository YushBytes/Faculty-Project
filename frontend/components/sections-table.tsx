"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UserCog } from "lucide-react";
import type { useScope } from "@/lib/auth/session";
import { insightsApi } from "@/lib/api/endpoints";
import type { OfferingRow } from "@/lib/api/types";
import { useApi } from "@/lib/hooks/use-api";
import { periodQuery } from "@/components/overview";
import { Badge, BarCell, DataTable, Empty, ErrorState, LoadingBlock } from "@/components/ui";
import { Sparkline } from "@/components/charts";
import { FacultyDrawer } from "@/components/assign";
import { pctOf } from "@/lib/format";

/** Every class (course × section) in scope with its measures; faculty assignment in place. */
export function Sections({ scope, canAssign, onChanged, empty }: { scope: ReturnType<typeof useScope>; canAssign: boolean; onChanged?: () => void; empty?: React.ReactNode }) {
  const router = useRouter();
  const { data, error, loading, reload } = useApi(() => insightsApi.offerings(scope), [scope]);
  const [assign, setAssign] = useState<OfferingRow | null>(null);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingBlock rows={10} />;
  const q = periodQuery(scope);
  return (
    <>
      <DataTable
        rows={data.items}
        rowKey={(r) => r.id}
        onRowClick={(r) => router.push(`/classes/${r.id}${q}`)}
        initialSort={{ key: "section", dir: "asc" }}
        empty={empty ?? <Empty title="No classes in this view">Classes appear here for the selected period once they exist in your scope. Try another academic year or semester at the top of the page.</Empty>}
        columns={[
          { key: "section", label: "Class", sort: (r) => `${r.course_code} ${r.section_name}`, render: (r) => <span className="strong">{r.course_code} · {r.section_name}<span className="sub">{r.term_name}</span></span> },
          { key: "faculty", label: "Faculty", sort: (r) => r.faculty[0]?.name ?? "", render: (r) => <span>{r.faculty.map((f) => f.name).join(", ") || <span className="muted">Unassigned</span>}</span> },
          { key: "students", label: "Students", align: "right", sort: (r) => r.enrolments, render: (r) => r.enrolments },
          { key: "avg", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
          { key: "median", label: "Median", align: "right", sort: (r) => r.median.value, render: (r) => pctOf(r.median) },
          { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
          { key: "completion", label: "Completion", align: "right", sort: (r) => r.completion_percent.value, render: (r) => pctOf(r.completion_percent) },
          { key: "trend", label: "Trend", render: (r) => <Sparkline values={r.trend.map((t) => t.mean)} /> },
          { key: "att", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => r.attention_students ? <Badge tone="amber">{r.attention_students}</Badge> : <span className="muted">0</span> },
          ...(canAssign ? [{ key: "assign", label: "", render: (r: OfferingRow) => <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); setAssign(r); }}><UserCog size={15} /> Faculty</button> }] : []),
        ]}
      />
      {assign && <FacultyDrawer offeringId={assign.id} label={`${assign.course_code} · ${assign.section_name}`} onClose={() => setAssign(null)} onChanged={() => { reload(); onChanged?.(); }} />}
    </>
  );
}
