"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Search } from "lucide-react";
import { studentsApi } from "@/lib/api/endpoints";
import { useScope, useUrlState } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, DataTable, Empty, ErrorState, LoadingBlock, PageHead } from "@/components/ui";
import { useOverview } from "@/components/overview";
import { num } from "@/lib/format";

const PAGE = 50;

export default function Students() {
  const router = useRouter();
  const scope = useScope();
  const { params, set } = useUrlState();
  const [text, setText] = useState(params.get("q") ?? "");
  const q = params.get("q") ?? "";
  const sectionId = params.get("section_id") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const options = useOverview({ academic_year: scope.academic_year, semester: scope.semester });
  const { data, error, loading, reload } = useApi(() => studentsApi.list({ q: q || undefined, section_id: sectionId || undefined, limit: PAGE, offset }), [q, sectionId, offset]);
  return (
    <>
      <PageHead eyebrow="Students" title="Students" description="Every student in your scope. Search by register number or name; open a student for their performance across every class you can see." />
      <form className="filters" onSubmit={(e) => { e.preventDefault(); set({ q: text || null, offset: null }); }}>
        <div className="search" style={{ minWidth: 320 }}><Search size={16} /><input className="input" placeholder="Register number or name" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search students" /></div>
        <select className="select" aria-label="Section" value={sectionId} onChange={(e) => set({ section_id: e.target.value || null, offset: null })}>
          <option value="">All sections</option>
          {options.data?.comparisons.sections.map((s) => <option key={s.id} value={s.id}>Section {s.label}</option>)}
        </select>
        <button className="btn">Search</button>
        {data && <span className="muted" style={{ fontSize: 14 }}>{num(data.total)} students</span>}
      </form>
      {error ? <ErrorState error={error} retry={reload} /> : loading || !data ? <LoadingBlock rows={12} /> : (
        <>
          <DataTable rows={data.items} rowKey={(s) => s.id} onRowClick={(s) => router.push(`/students/${s.id}`)} empty={<Empty title="No students match">Try another name or register number.</Empty>} columns={[
            { key: "name", label: "Student", render: (s) => <span className="strong">{s.full_name}<span className="sub">{s.email ?? ""}</span></span> },
            { key: "reg", label: "Register number", render: (s) => <span className="tabular">{s.register_number}</span> },
            { key: "section", label: "Section", render: (s) => s.current_section?.name ?? "—" },
            { key: "batch", label: "Batch", render: (s) => s.batch_year },
            { key: "dept", label: "Department", render: (s) => s.department.code },
            { key: "status", label: "Status", render: (s) => s.is_active ? <Badge tone="green">Active</Badge> : <Badge>Inactive</Badge> },
          ]} />
          <div className="filters" style={{ marginTop: 14, justifyContent: "flex-end" }}>
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) })}>Previous</button>
            <span className="muted" style={{ fontSize: 14 }}>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {num(data.total)}</span>
            <button className="btn btn-sm" disabled={offset + PAGE >= data.total} onClick={() => set({ offset: String(offset + PAGE) })}>Next</button>
          </div>
        </>
      )}
    </>
  );
}
