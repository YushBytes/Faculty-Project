"use client";

import { auditApi } from "@/lib/api/endpoints";
import { useUrlState } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, DataTable, ErrorState, LoadingBlock, PageHead } from "@/components/ui";
import { dateTime, num } from "@/lib/format";

const ENTITIES = ["assessment_result", "import_batch", "user", "course", "offering", "assessment", "student", "setting"];

export default function Audit() {
  const { params, set } = useUrlState();
  const entity = params.get("entity") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi(() => auditApi.list({ entity: entity || undefined, limit: 50, offset }), [entity, offset]);
  const show = (v: unknown) => (v ? Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : String(x)}`).join(" · ") : "—");
  return (
    <>
      <PageHead eyebrow="Accountability" title="Audit log" description="Append-only record of changes to marks, imports and corrections, roles, assignments and settings — written in the same transaction as the change. Passwords are never recorded." />
      <div className="filters">
        <select className="select" value={entity} onChange={(e) => set({ entity: e.target.value || null, offset: null })}><option value="">Everything</option>{ENTITIES.map((e) => <option key={e} value={e}>{e.replaceAll("_", " ")}</option>)}</select>
        {data && <span className="muted">{num(data.total)} entries</span>}
      </div>
      {error ? <ErrorState error={error} retry={reload} /> : loading || !data ? <LoadingBlock rows={12} /> : (
        <>
          <DataTable rows={data.items} rowKey={(r) => r.id} columns={[
            { key: "when", label: "When", render: (r) => dateTime(r.created_at) },
            { key: "what", label: "Change", render: (r) => <span className="strong">{r.entity.replaceAll("_", " ")} <Badge>{r.action.replaceAll("_", " ")}</Badge></span> },
            { key: "old", label: "Before", render: (r) => <span style={{ fontSize: 13.5 }}>{show(r.old_value)}</span> },
            { key: "new", label: "After", render: (r) => <span style={{ fontSize: 13.5 }}>{show(r.new_value)}</span> },
          ]} />
          <div className="filters" style={{ marginTop: 14, justifyContent: "flex-end" }}>
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - 50)) })}>Previous</button>
            <button className="btn btn-sm" disabled={offset + 50 >= data.total} onClick={() => set({ offset: String(offset + 50) })}>Next</button>
          </div>
        </>
      )}
    </>
  );
}
