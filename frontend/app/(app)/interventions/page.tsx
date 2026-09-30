"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { insightsApi } from "@/lib/api/endpoints";
import { useScope, useUrlState } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { periodQuery } from "@/components/overview";
import { FilterBar } from "@/components/filter-bar";
import { Badge, DataTable, Empty, ErrorState, Kpi, LoadingBlock, Notice, PageHead } from "@/components/ui";
import { INTERVENTION_KINDS, date, num } from "@/lib/format";

const PAGE = 50;

export default function Interventions() {
  const scope = useScope();
  const router = useRouter();
  const { params, set } = useUrlState();
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi(() => insightsApi.interventions(scope, { limit: PAGE, offset }), [scope, offset]);
  const q = periodQuery(scope);
  return (
    <>
      <PageHead eyebrow="Interventions" title="Interventions" description="Support actions recorded for students, with the observed change at the next assessment. Record a new one from Attention, a class or a student." />
      <FilterBar show={["course", "section", "faculty"]} />
      <Notice>Outcomes are observations. The students were chosen because they were struggling and nothing was randomised, so a change after an intervention is reported — never claimed as its effect.</Notice>
      {error ? <ErrorState error={error} retry={reload} /> : loading || !data ? <LoadingBlock rows={10} /> : (
        <>
          <div className="kpis section" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
            <Kpi label="Recorded" value={num(data.total)} />
            <Kpi label="Completed" value={num(data.by_status.completed ?? 0)} />
            <Kpi label="In progress" value={num(data.by_status.active ?? 0)} />
            <Kpi label="Planned" value={num(data.by_status.planned ?? 0)} />
          </div>
          <div className="section">
            <DataTable rows={data.items} rowKey={(r) => r.id} onRowClick={(r) => router.push(`/interventions/${r.id}?offering=${r.offering_id}`)} empty={<Empty title="No interventions recorded in this scope">Open Attention to act on a flagged student.</Empty>} columns={[
              { key: "date", label: "Date", render: (r) => date(r.recorded_on ?? r.created_at) },
              { key: "kind", label: "Action", render: (r) => <span className="strong">{INTERVENTION_KINDS[r.kind] ?? r.kind}<span className="sub">{r.note}</span></span> },
              { key: "students", label: "Students", render: (r) => r.students.map((s) => s.name).join(", ") },
              { key: "class", label: "Class", render: (r) => <Link href={`/classes/${r.offering_id}${q}`} onClick={(e) => e.stopPropagation()}>{r.offering}</Link> },
              { key: "by", label: "Recorded by", render: (r) => r.recorded_by ?? "—" },
              { key: "status", label: "Status", render: (r) => <Badge tone={r.status === "completed" ? "green" : r.status === "active" ? "blue" : undefined}>{r.status}</Badge> },
            ]} />
            <div className="filters" style={{ marginTop: 14, justifyContent: "flex-end" }}>
              <button className="btn btn-sm" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) })}>Previous</button>
              <button className="btn btn-sm" disabled={offset + PAGE >= data.total} onClick={() => set({ offset: String(offset + PAGE) })}>Next</button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
