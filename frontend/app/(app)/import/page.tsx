"use client";

import Link from "next/link";
import { useCallback, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, Copy, FileSpreadsheet, FileText, Info, Loader2, SkipForward, Trash2, UploadCloud, XCircle } from "lucide-react";
import { importsApi, insightsApi, offeringsApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import type { ImportPreview, TlpFile, TlpUpload } from "@/lib/api/types";
import { useScope, useSession, useUrlState, useWorkspace } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, Card, DataTable, Drawer, Empty, LoadingBlock, Notice, PageHead } from "@/components/ui";
import { dateTime, num } from "@/lib/format";

const STATUS: Record<TlpFile["status"] | "uploading", { label: string; tone: "green" | "amber" | "red" | "blue" | "violet" | undefined; icon: React.ReactNode }> = {
  uploading: { label: "Processing", tone: "blue", icon: <Loader2 size={14} className="spin" /> },
  valid: { label: "Valid", tone: "green", icon: <CheckCircle2 size={14} /> },
  warning: { label: "Warnings", tone: "amber", icon: <AlertTriangle size={14} /> },
  error: { label: "Errors", tone: "red", icon: <XCircle size={14} /> },
  rejected: { label: "Rejected", tone: "red", icon: <XCircle size={14} /> },
  needs_section: { label: "Section needed", tone: "amber", icon: <AlertTriangle size={14} /> },
  duplicate: { label: "Duplicate", tone: "violet", icon: <Copy size={14} /> },
  skipped: { label: "Skipped", tone: undefined, icon: <SkipForward size={14} /> },
  confirmed: { label: "Confirmed", tone: "green", icon: <CheckCircle2 size={14} /> },
  discarded: { label: "Discarded", tone: undefined, icon: <Trash2 size={14} /> },
};

export default function ImportPage() {
  const ws = useWorkspace();
  const { notify } = useSession();
  const scope = useScope();
  const { params } = useUrlState();
  const offeringId = params.get("offering_id") ?? "";
  const [courseId, setCourseId] = useState(params.get("course_id") ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [upload, setUpload] = useState<TlpUpload | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [review, setReview] = useState<TlpFile | null>(null);
  const input = useRef<HTMLInputElement>(null);
  // The files of the last upload, so one that needs its section can be sent again.
  const [sent, setSent] = useState<Map<string, File>>(() => new Map());

  const offering = useApi(() => offeringsApi.get(offeringId), [offeringId], !!offeringId);
  const courses = useApi(() => insightsApi.overview({ academic_year: scope.academic_year, semester: scope.semester }), [scope.academic_year, scope.semester], !offeringId);
  const history = useApi(() => importsApi.history({ limit: 10 }), [upload?.group_id, upload?.counts.confirmed]);

  const add = useCallback((list: FileList | null) => {
    if (!list) return;
    const picked = Array.from(list); // copy now: the input is cleared right after
    setFiles((current) => [...current, ...picked.filter((f) => !current.some((c) => c.name === f.name && c.size === f.size))]);
  }, []);

  async function send() {
    if (!files.length) return;
    setProgress(0);
    setUpload(null);
    try {
      const result = await importsApi.tlpUpload(files, { offering_id: offeringId || undefined, course_id: offeringId ? undefined : courseId || undefined }, setProgress);
      setSent(new Map(files.map((f) => [f.name, f])));
      setUpload(result);
      setFiles([]);
      notify("Files processed", `${result.counts.total} file(s): ${num((result.counts.valid ?? 0) + (result.counts.warning ?? 0))} ready, ${num((result.counts.error ?? 0) + (result.counts.rejected ?? 0) + (result.counts.needs_section ?? 0))} need attention`);
    } catch (err) {
      notify("Upload failed", err instanceof ApiError ? err.message : String(err), "error");
    } finally {
      setProgress(null);
    }
  }

  async function refresh(groupId: string) {
    const fresh = await importsApi.tlpGroup(groupId);
    setUpload((current) => {
      if (!current) return fresh;
      const byBatch = new Map(fresh.files.map((f) => [f.batch_id, f]));
      const files = current.files.map((f) => (f.batch_id && byBatch.get(f.batch_id)) || f);
      return { ...current, files, counts: countOf(files) };
    });
  }

  /** Send one file again with the section typed for it; it joins the same upload. */
  async function resend(fileName: string, section: string) {
    const file = sent.get(fileName);
    if (!upload || !file) return;
    try {
      const result = await importsApi.tlpUpload([file], { group_id: upload.group_id, sections: JSON.stringify({ [fileName]: section }) });
      const fresh = result.files[0];
      setUpload((current) => {
        if (!current) return current;
        const files = current.files.map((f) => (f.file_name === fileName && f.status === "needs_section" ? fresh : f));
        return { ...current, files, counts: countOf(files) };
      });
      notify(fresh.status === "needs_section" || fresh.status === "rejected" ? "Still not routed" : `Routed to section ${fresh.section_name}`, fresh.message ?? fresh.routed_by ?? "", fresh.status === "rejected" ? "error" : undefined);
    } catch (err) {
      notify("Upload failed", err instanceof ApiError ? err.message : String(err), "error");
    }
  }

  async function discard(file: TlpFile) {
    if (!file.batch_id) return;
    try {
      await importsApi.discard(file.batch_id);
      setUpload((current) => {
        if (!current) return current;
        const files = current.files.map((f) => (f.batch_id === file.batch_id ? { ...f, status: "discarded" as const, created: {} } : f));
        return { ...current, files, counts: countOf(files) };
      });
      notify("File discarded", "Its marks were not written, and anything it had set up that nothing else uses was removed.");
    } catch (err) {
      notify("Discard failed", err instanceof ApiError ? err.message : String(err), "error");
    }
  }

  async function confirmAll() {
    if (!upload) return;
    setConfirming(true);
    try {
      const result = await importsApi.tlpConfirm(upload.group_id);
      const byBatch = new Map(result.files.map((f) => [f.batch_id, f]));
      const merged = upload.files.map((f) => (f.batch_id && byBatch.get(f.batch_id)) || f);
      setUpload({ ...upload, files: merged, counts: countOf(merged) });
      const n = result.files.filter((f) => f.status === "confirmed").length;
      notify("Marks written", `${n} file(s) confirmed · assessments published · analytics recomputed`);
    } catch (err) {
      notify("Confirm failed", err instanceof ApiError ? err.message : String(err), "error");
    } finally {
      setConfirming(false);
    }
  }

  const ready = upload?.files.filter((f) => f.status === "valid" || f.status === "warning" || f.status === "duplicate").length ?? 0;
  const confirmed = upload?.files.filter((f) => f.status === "confirmed") ?? [];
  const stage = upload ? (confirmed.length ? 4 : 3) : files.length ? 2 : 1;
  const courseOptions = courses.data?.comparisons.courses ?? [];
  const target = offeringId && offering.data ? `${offering.data.course.code} · Section ${offering.data.section.name} (${offering.data.term.name})` : null;

  return (
    <>
      <PageHead eyebrow="Import" title="Import TLP marks" description="Drop SRM TLP reports — Excel, CSV or the TLP PDF, one per section, as many as you like. Everything is read from the files: semester, course, section, faculty, students, test and marks. Nothing is written until you confirm." />
      <div className="steps" aria-label="Progress">
        {["Choose files", "Upload & validate", "Review", "Confirm"].map((label, i) => <span key={label} className={`step ${stage > i + 1 ? "done" : stage === i + 1 ? "now" : ""}`}><i>{i + 1}</i>{label}</span>)}
      </div>
      <div className="grid g-main">
        <Card title="1 · Files" subtitle={target ? `Uploading into ${target}` : "Name files with their section (e.g. DSA_FJ-III_A1.xlsx) — or type it when asked"}>
          {!offeringId && (
            <div className="filters">
              <label className="field" style={{ minWidth: 300 }}><span>Course</span>
                <select className="select" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
                  <option value="">Read from each file (recommended)</option>
                  {courseOptions.map((c) => <option key={c.id} value={c.id}>{c.label} · {c.name}</option>)}
                </select>
              </label>
              <span className="muted" style={{ fontSize: 13.5, alignSelf: "end", paddingBottom: 10 }}>Choose one only for plain mark sheets that have no TLP title block.</span>
            </div>
          )}
          <div className={`dropzone ${drag ? "drag" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}>
            <UploadCloud size={36} color="var(--accent)" />
            <h3>Drop TLP reports here</h3>
            <p>.xlsx, .csv or TLP-format .pdf · up to 150 files, 5 MB each</p>
            <button className="btn" style={{ marginTop: 14 }} onClick={() => input.current?.click()}>Choose files</button>
            <input ref={input} type="file" multiple hidden accept=".xlsx,.csv,.pdf" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          </div>
          {files.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 14 }}>
              {files.map((f) => (
                <div className="file-row" key={f.name + f.size}>
                  {f.name.endsWith(".pdf") ? <FileText size={18} color="var(--red)" /> : <FileSpreadsheet size={18} color="var(--accent)" />}
                  <span className="fname">{f.name}</span>
                  <span className="muted">{num(Math.ceil(f.size / 1024))} KB</span>
                  <Badge><CircleDashed size={13} /> Selected</Badge>
                  <button className="btn btn-sm btn-ghost" onClick={() => setFiles((c) => c.filter((x) => x !== f))} aria-label={`Remove ${f.name}`}><Trash2 size={15} /></button>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 16 }}>
            <button className="btn btn-primary" disabled={!files.length || progress !== null} onClick={send}><UploadCloud size={17} /> Upload and validate {files.length ? `${files.length} file${files.length > 1 ? "s" : ""}` : ""}</button>
            {progress !== null && (
              <div style={{ flex: 1 }}>
                <div className="meter"><i style={{ width: `${Math.round(progress * 100)}%`, background: "var(--accent)" }} /></div>
                <small className="muted">{progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : "Parsing, routing and validating each file…"}</small>
              </div>
            )}
          </div>
        </Card>
        <Card title="What happens" subtitle="Everything comes from your files">
          <div className="statement"><CheckCircle2 size={16} /><span>The title block gives the <b>semester</b> (AY2025-26-EVEN), the <b>course</b> (21CSC201J and its name), the <b>faculty</b> (name and staff id — a login is created as <i>staffid</i>@srmist.edu.in) and the <b>test</b> with its maximum.</span></div>
          <div className="statement"><CheckCircle2 size={16} /><span>The <b>section</b> comes from where the students already are, else the file name (…_A1.xlsx), else you type it. A file name that contradicts the students is stopped.</span></div>
          <div className="statement"><CheckCircle2 size={16} /><span>Each row gives a <b>student</b> (register number and name). Existing records are reused, never overwritten.</span></div>
          <div className="statement"><CheckCircle2 size={16} /><span>Marks are numbers within the maximum; <b>Absent</b> stays absent — never zero. The % column is checked against the mark.</span></div>
          <div className="statement"><CheckCircle2 size={16} /><span>The summary block (strength, absentees) agrees with the rows, so a truncated export is caught.</span></div>
          <div className="statement"><Info size={16} /><span>Confirming writes marks, audit records and analytics in one transaction per file. Discarding a file also removes whatever it set up that nothing else uses.</span></div>
        </Card>
      </div>

      {upload && (
        <Card className="section" title="2 · Results per file" subtitle={`${upload.counts.total} file(s) · ${ready} ready to confirm${confirmed.length ? ` · ${confirmed.length} confirmed` : ""}`}
          actions={<button className="btn btn-primary" disabled={!ready || confirming} onClick={confirmAll}>{confirming ? "Confirming…" : `Confirm ${ready} file${ready === 1 ? "" : "s"}`}</button>}>
          <div className="filters">{Object.entries(upload.counts).filter(([k]) => k !== "total").map(([k, v]) => <Badge key={k} tone={STATUS[k as TlpFile["status"]]?.tone}>{STATUS[k as TlpFile["status"]]?.label ?? k}: {v}</Badge>)}</div>
          <div className="table-wrap">
            {upload.files.map((f, i) => {
              const s = STATUS[f.status];
              const sum = f.summary as Record<string, number>;
              return (
                <div className="file-row" key={`${f.file_name}-${i}`}>
                  {f.file_name.endsWith(".pdf") ? <FileText size={18} color="var(--red)" /> : <FileSpreadsheet size={18} color="var(--accent)" />}
                  <div style={{ minWidth: 0 }}>
                    <div className="fname">{f.file_name}</div><small>{f.message ?? f.routed_by ?? ""}</small>
                    <Created created={f.created} />
                    {f.status === "needs_section" && <SectionRetry fileName={f.file_name} canResend={sent.has(f.file_name)} onSend={resend} />}
                  </div>
                  <div>{f.offering_label ? <><b>{f.offering_label}</b><small>{f.assessment_name ? `→ ${f.assessment_name}` : ""}</small></> : <span className="muted">Not routed</span>}</div>
                  <div>{f.batch_id ? <small>{num(sum.total_rows)} rows · {num(sum.cells_to_write)} marks · <span style={{ color: sum.errors ? "var(--red)" : undefined }}>{num(sum.errors)} errors</span> · {num(sum.warnings)} warnings{sum.created !== undefined ? ` · ${num(sum.created)} written` : ""}</small> : f.issues.map((x) => <small key={x.message}>{x.message}</small>)}</div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <Badge tone={s.tone}>{s.icon} {s.label}</Badge>
                    {f.batch_id && f.status !== "confirmed" && f.status !== "discarded" && <button className="btn btn-sm" onClick={() => setReview(f)}>Review</button>}
                    {f.batch_id && f.status !== "confirmed" && f.status !== "discarded" && <button className="btn btn-sm btn-ghost" onClick={() => discard(f)} aria-label={`Discard ${f.file_name}`} title="Discard this file"><Trash2 size={15} /></button>}
                    {f.status === "confirmed" && f.offering_id && <Link className="btn btn-sm" href={`/classes/${f.offering_id}`}>Open class</Link>}
                  </div>
                </div>
              );
            })}
          </div>
          {confirmed.length > 0 && <Notice tone="ok" icon={<CheckCircle2 size={18} />}>Marks for {confirmed.length} section(s) are now in the database; dashboards, attention and reports already reflect them. <Link href="/analytics" style={{ fontWeight: 700 }}>Open analytics →</Link></Notice>}
        </Card>
      )}

      <Card className="section" title="Recent imports" subtitle="Your scope's import history">
        {history.loading ? <LoadingBlock rows={4} /> : (
          <DataTable rows={history.data?.items ?? []} rowKey={(b) => b.id} empty={<Empty title="No imports yet" />} columns={[
            { key: "file", label: "File", render: (b) => <span className="strong">{b.file_name}<span className="sub">{b.file_type.toUpperCase()} · {String(b.source_metadata?.test_name ?? "")}</span></span> },
            { key: "rows", label: "Rows", align: "right", render: (b) => b.total_rows },
            { key: "status", label: "Status", render: (b) => <Badge tone={b.status === "committed" ? "green" : b.status === "discarded" ? undefined : "amber"}>{b.status}</Badge> },
            { key: "at", label: "When", render: (b) => dateTime(b.committed_at ?? b.created_at) },
            { key: "open", label: "", render: (b) => <Link className="btn btn-sm" href={`/classes/${b.offering_id}`}>Class</Link> },
          ]} />
        )}
      </Card>
      {review && review.batch_id && <ReviewDrawer file={review} onClose={() => setReview(null)} onChanged={() => upload && refresh(upload.group_id)} />}
      <style>{`.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      {ws.user.role === "FACULTY" && !offeringId && <p className="muted" style={{ marginTop: 12, fontSize: 13.5 }}>Files are only routed into your own classes.</p>}
    </>
  );
}

/** What a file set up on the platform, in one line of chips. */
function Created({ created }: { created: TlpFile["created"] | undefined }) {
  if (!created) return null;
  const parts = [
    created.term && `semester ${created.term}`,
    created.course && `course ${created.course}`,
    created.section && `section ${created.section}`,
    created.students && `${num(created.students)} student${created.students === 1 ? "" : "s"}`,
    !created.students && created.enrolments && `${num(created.enrolments)} enrolment${created.enrolments === 1 ? "" : "s"}`,
    created.faculty && `faculty login ${created.faculty.email}`,
    created.assessment && `test ${created.assessment}`,
  ].filter(Boolean) as string[];
  if (!parts.length) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
      <small className="muted" style={{ fontWeight: 600 }}>New:</small>
      {parts.map((p) => <Badge key={p} tone="blue">{p}</Badge>)}
    </div>
  );
}

function SectionRetry({ fileName, canResend, onSend }: { fileName: string; canResend: boolean; onSend: (fileName: string, section: string) => Promise<void> }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  if (!canResend) return <small className="muted">Rename the file with its section (e.g. …_A1.xlsx) and upload it again.</small>;
  return (
    <form style={{ display: "flex", gap: 8, marginTop: 8 }} onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onSend(fileName, value.trim()); setBusy(false); }}>
      <input className="input input-sm" style={{ maxWidth: 160 }} aria-label={`Section for ${fileName}`} placeholder="Section, e.g. A1" value={value} onChange={(e) => setValue(e.target.value)} />
      <button className="btn btn-sm btn-primary" disabled={busy || !value.trim()}>{busy ? "Sending…" : "Use this section"}</button>
    </form>
  );
}

function countOf(files: TlpFile[]) {
  const counts: Record<string, number> = { total: files.length };
  for (const f of files) counts[f.status] = (counts[f.status] ?? 0) + 1;
  return counts;
}

function ReviewDrawer({ file, onClose, onChanged }: { file: TlpFile; onClose: () => void; onChanged: () => void }) {
  const { notify } = useSession();
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [error, setError] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const load = useApi(async () => { const p = await importsApi.preview(file.batch_id!, "issues"); setPreview(p); return p; }, [file.batch_id]);
  const meta = (preview?.batch.source_metadata ?? {}) as Record<string, unknown>;
  const rows = useMemo(() => preview?.rows ?? [], [preview]);
  const apply = async (fn: () => Promise<ImportPreview>, ok: string) => {
    setBusy(true); setError("");
    try { setPreview(await fn()); notify(ok); onChanged(); } catch (err) { setError(err instanceof ApiError ? err.message : String(err)); } finally { setBusy(false); }
  };
  return (
    <Drawer title={file.file_name} subtitle={`${file.offering_label ?? ""} → ${file.assessment_name ?? ""}`} onClose={onClose}
      footer={<><button className="btn btn-danger" disabled={busy} onClick={async () => { await importsApi.discard(file.batch_id!); notify("Import discarded"); onChanged(); onClose(); }}><Trash2 size={15} /> Discard file</button><button className="btn" onClick={onClose}>Done</button></>}>
      {load.loading && !preview ? <LoadingBlock rows={8} /> : preview && (
        <>
          <div className="grid g-2">
            <div className="kpi"><div className="k-label">From the report</div><div style={{ fontSize: 14, marginTop: 6 }}>{String(meta.test_name ?? "—")} · {String(meta.academic_year ?? "—")}<br />max {String(meta.component_max ?? "—")} · {String(meta.course_code ?? "")}<br />{String(meta.faculty_name ?? "")} {meta.faculty_code ? `(${String(meta.faculty_code)})` : ""}</div></div>
            <div className="kpi"><div className="k-label">This file</div><div style={{ fontSize: 14, marginTop: 6 }}>{num(preview.summary.total_rows as number)} rows · {num(preview.summary.cells_to_write as number)} marks to write<br />{num(preview.summary.absent_markers as number)} absent · {num(preview.summary.will_update as number)} updates<br />{num(preview.summary.errors as number)} errors · {num(preview.summary.warnings as number)} warnings</div></div>
          </div>
          {preview.file_issues.map((i) => <Notice key={i.code + i.message} tone={i.level === "error" ? "error" : i.level === "warning" ? "warn" : "info"}>{i.message}</Notice>)}
          {preview.missing_students.length > 0 && <Notice tone="warn">{preview.missing_students.length} enrolled student(s) are not in the file; their marks stay as they are: {preview.missing_students.slice(0, 6).map((s) => s.register_number).join(", ")}{preview.missing_students.length > 6 ? " …" : ""}</Notice>}
          <div className="label">Rows with issues ({rows.length})</div>
          {rows.length === 0 ? <p className="muted">No row-level issues.</p> : rows.map((r) => {
            const bad = r.cells.find((c) => c.issues.some((i) => i.level === "error"));
            const key = `${r.row}|${bad?.column}`;
            return (
              <div key={r.row} className="card card-flat" style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <div><b>Row {r.row}</b> · {r.register_number ?? "no register number"} {r.student_name && <span className="muted">· {r.student_name}</span>}</div>
                  <button className="btn btn-sm" disabled={busy} onClick={() => apply(() => importsApi.exclude(file.batch_id!, [r.row], !r.excluded), r.excluded ? "Row included" : "Row excluded")}>{r.excluded ? "Include" : "Exclude row"}</button>
                </div>
                {[...r.issues, ...r.cells.flatMap((c) => c.issues)].map((i, n) => <p key={n} style={{ fontSize: 13.5, marginTop: 6, color: i.level === "error" ? "var(--red)" : i.level === "warning" ? "var(--amber)" : "var(--muted)" }}>{i.message}</p>)}
                {bad && !r.excluded && (
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <input className="input input-sm" aria-label={`New value for row ${r.row}`} placeholder={`Correct ${bad.column} (was “${bad.raw ?? ""}”)`} value={edits[key] ?? ""} onChange={(e) => setEdits((x) => ({ ...x, [key]: e.target.value }))} />
                    <button className="btn btn-sm btn-primary" disabled={busy || !edits[key]} onClick={() => apply(() => importsApi.fix(file.batch_id!, [{ row: r.row, column: bad.column, value: edits[key] }]), "Correction applied (audited)")}>Apply</button>
                  </div>
                )}
              </div>
            );
          })}
          {error && <Notice tone="error">{error}</Notice>}
          <p className="muted" style={{ fontSize: 13 }}>Every correction is recorded in the audit log with the value that was uploaded.</p>
        </>
      )}
    </Drawer>
  );
}
