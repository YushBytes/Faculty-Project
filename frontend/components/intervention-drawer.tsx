"use client";

/** Record an intervention for students of one class, with reasons taken from their live
 * attention flags (frozen server-side as they stand now) or a note. */
import { useMemo, useState } from "react";
import { insightsApi, offeringsApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import { useScope, useSession } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Drawer, LoadingBlock, Notice, SeverityBadge } from "@/components/ui";
import { INTERVENTION_KINDS, RULES } from "@/lib/format";

export function InterventionDrawer({ offeringId, label, preselect = [], onClose, onSaved }: { offeringId: string; label: string; preselect?: string[]; onClose: () => void; onSaved?: () => void }) {
  const { notify } = useSession();
  const scope = useScope({ offering_id: offeringId });
  const flags = useApi(() => insightsApi.attention({ ...scope, semester: "YEAR" }, { limit: 200 }), [offeringId]);
  const assessments = useApi(() => offeringsApi.assessments(offeringId), [offeringId]);
  const [selected, setSelected] = useState<Set<string>>(new Set(preselect));
  const [flagIds, setFlagIds] = useState<Set<string>>(new Set());
  const [kind, setKind] = useState("academic_support");
  const [status, setStatus] = useState("completed");
  const [after, setAfter] = useState<number | null>(null);
  const [recordedOn, setRecordedOn] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const byStudent = useMemo(() => {
    const map = new Map<string, { name: string; reg: string; flags: { id: string; rule: string; severity: string; message: string }[] }>();
    for (const f of flags.data?.items ?? []) {
      const entry = map.get(f.student.id) ?? { name: f.student.name, reg: f.student.register_number, flags: [] };
      entry.flags.push({ id: f.id, rule: f.rule_code, severity: f.severity, message: f.message });
      map.set(f.student.id, entry);
    }
    return map;
  }, [flags.data]);
  const published = assessments.data?.items.filter((a) => a.is_published) ?? [];
  const afterSeq = after ?? (published.length ? Math.max(...published.map((a) => a.sequence_no)) : 0);

  const toggle = (set: Set<string>, id: string, update: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    update(next);
  };

  async function save() {
    setError("");
    const students = [...selected];
    const reasons = students.flatMap((sid) => (byStudent.get(sid)?.flags ?? []).filter((f) => flagIds.has(f.id)).map((f) => ({ student_id: sid, flag_id: f.id })));
    if (!students.length) return setError("Choose at least one student.");
    if (!reasons.length && !note.trim()) return setError("Tick at least one attention flag as the reason, or write a note.");
    setSaving(true);
    try {
      await offeringsApi.createIntervention(offeringId, { student_ids: students, kind, status, after_sequence_no: afterSeq, recorded_on: recordedOn || null, reasons, note: note.trim() || null });
      notify("Intervention recorded", `${students.length} student${students.length > 1 ? "s" : ""} · ${label}`);
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer title="Record an intervention" subtitle={label} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Record intervention"}</button></>}>
      <Notice>What happens next is observed at the following assessment and compared with classmates. It is reported as an observation — never as the effect of the intervention.</Notice>
      <div className="grid g-2">
        <label className="field"><span>Action</span><select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>{Object.entries(INTERVENTION_KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field"><span>Status</span><select className="select" value={status} onChange={(e) => setStatus(e.target.value)}><option value="planned">Planned</option><option value="active">In progress</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label>
        <label className="field"><span>Raised after</span><select className="select" value={afterSeq} onChange={(e) => setAfter(Number(e.target.value))}><option value={0}>Before any assessment</option>{published.map((a) => <option key={a.id} value={a.sequence_no}>{a.name}</option>)}</select></label>
        <label className="field"><span>Date</span><input className="input" type="date" value={recordedOn} onChange={(e) => setRecordedOn(e.target.value)} /></label>
      </div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
          <div className="label" style={{ margin: 0 }}>Students with attention flags · tick the flags that are the reason</div>
          {byStudent.size > 0 && (
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted" style={{ fontSize: 13 }}>{selected.size} selected</span>
              <button type="button" className="btn btn-sm" onClick={() => {
                const everyone = [...byStudent.keys()];
                const all = everyone.every((id) => selected.has(id));
                setSelected(all ? new Set() : new Set([...selected, ...everyone]));
                if (all) setFlagIds(new Set());
              }}>{[...byStudent.keys()].every((id) => selected.has(id)) ? "Clear all" : "Select all"}</button>
            </div>
          )}
        </div>
        {flags.loading ? <LoadingBlock rows={4} /> : byStudent.size === 0 ? <p className="muted">No live attention flags in this class. You can still record an intervention with a note for students chosen from the Marks tab.</p> : (
          <div className="list" style={{ maxHeight: 340, overflowY: "auto" }}>
            {[...byStudent.entries()].map(([sid, s]) => (
              <div className="list-item" key={sid} style={{ alignItems: "flex-start" }}>
                <input type="checkbox" checked={selected.has(sid)} onChange={() => toggle(selected, sid, setSelected)} aria-label={`Select ${s.name}`} style={{ marginTop: 4 }} />
                <div className="grow"><b>{s.name}</b><small>{s.reg}</small>
                  <div style={{ display: "grid", gap: 4, marginTop: 6 }}>{s.flags.map((f) => (
                    <label key={f.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5 }}>
                      <input type="checkbox" disabled={!selected.has(sid)} checked={flagIds.has(f.id)} onChange={() => toggle(flagIds, f.id, setFlagIds)} />
                      <SeverityBadge severity={f.severity} /> {RULES[f.rule]?.name ?? f.rule}
                    </label>))}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {[...selected].filter((sid) => !byStudent.has(sid)).length > 0 && <p className="muted" style={{ fontSize: 13.5 }}>{[...selected].filter((sid) => !byStudent.has(sid)).length} student(s) chosen without a flag — add a note.</p>}
      </div>
      <label className="field"><span>Note</span><textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What was done, and what to look for next time" /></label>
      {error && <Notice tone="error">{error}</Notice>}
    </Drawer>
  );
}
