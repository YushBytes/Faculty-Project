"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, Inbox, RefreshCw, X } from "lucide-react";
import type { ApiError } from "@/lib/api/http";
import type { Crumb, Measure } from "@/lib/api/types";
import { pct, scaleColor, value } from "@/lib/format";

export function PageHead({ eyebrow, title, description, actions, crumbs }: { eyebrow?: React.ReactNode; title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; crumbs?: { href?: string; label: string }[] }) {
  return (
    <>
      {crumbs && crumbs.length > 0 && <Breadcrumbs items={crumbs} />}
      <div className="page-head">
        <div>
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h1>{title}</h1>
          {description && <p>{description}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </>
  );
}

export function Breadcrumbs({ items }: { items: { href?: string; label: string }[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map((item, i) => (
        <span key={`${item.label}-${i}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {i > 0 && <ChevronRight size={14} className="sep" />}
          {item.href && i < items.length - 1 ? <Link href={item.href}>{item.label}</Link> : <span className={i === items.length - 1 ? "current" : ""}>{item.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function crumbHref(crumb: Crumb, query: string): string {
  const base = { department: "/departments", course: "/courses", coordinator: "/team", faculty: "/faculty", section: "/sections", offering: "/classes" }[crumb.kind];
  return `${base}/${crumb.id}${query}`;
}

export function Card({ title, subtitle, actions, children, className = "", id }: { title?: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string; id?: string }) {
  return (
    <section className={`card ${className}`} id={id}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value: v, foot, icon, tone }: { label: string; value: React.ReactNode; foot?: React.ReactNode; icon?: React.ReactNode; tone?: "accent" | "warn" }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <div className="k-label">{icon}{label}</div>
      <div className="k-value">{v}</div>
      {foot && <div className="k-foot">{foot}</div>}
    </div>
  );
}

export function MeasureValue({ m, digits = 1 }: { m?: Measure | null; digits?: number }) {
  if (!m || m.value === null) return <span title={m?.reason ?? "Insufficient data"} className="muted" style={{ fontSize: "0.62em", fontWeight: 600 }}>Insufficient data</span>;
  return <>{m.value.toFixed(digits)}<span style={{ fontSize: "0.55em", marginLeft: 2, color: "var(--muted)" }}>%</span></>;
}

export function Delta({ v, unit = " pp", invert = false }: { v: number | null | undefined; unit?: string; invert?: boolean }) {
  if (v === null || v === undefined) return null;
  const good = invert ? v < 0 : v > 0;
  const cls = Math.abs(v) < 0.5 ? "flat" : good ? "up" : "down";
  return (
    <span className={`delta ${cls}`}>
      {v > 0 ? <ArrowUp size={12} /> : v < 0 ? <ArrowDown size={12} /> : null}
      {`${v > 0 ? "+" : ""}${v.toFixed(1)}${unit}`}
    </span>
  );
}

export function Badge({ children, tone }: { children: React.ReactNode; tone?: "accent" | "blue" | "violet" | "amber" | "red" | "green" | "outline" }) {
  return <span className={`badge ${tone ? `badge-${tone}` : ""}`}>{children}</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  const tone = severity === "high" ? "red" : severity === "medium" ? "amber" : "blue";
  return <Badge tone={tone}><span className="dot" />{severity[0].toUpperCase() + severity.slice(1)}</Badge>;
}

export function Empty({ title, children, icon }: { title: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="state">
      <div className="state-icon">{icon ?? <Inbox size={24} />}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: ApiError | Error; retry?: () => void }) {
  const status = "status" in error ? (error as ApiError).status : 0;
  return (
    <div className="state error" role="alert">
      <div className="state-icon"><AlertTriangle size={24} /></div>
      <h3>{status === 404 ? "Not found or not in your scope" : status === 403 ? "Not permitted" : "Could not load this view"}</h3>
      <p>{error.message}</p>
      {retry && <button className="btn btn-sm" onClick={retry}><RefreshCw size={15} /> Try again</button>}
    </div>
  );
}

export function Skel({ h = 16, w = "100%", r = 8 }: { h?: number; w?: number | string; r?: number }) {
  return <span className="skeleton" style={{ height: h, width: w, borderRadius: r }} aria-hidden />;
}

export function LoadingDashboard() {
  return (
    <div role="status" aria-label="Loading">
      <div className="kpis">{Array.from({ length: 6 }, (_, i) => <div className="kpi" key={i}><Skel h={13} w="55%" /><div style={{ height: 10 }} /><Skel h={30} w="70%" /><div style={{ height: 8 }} /><Skel h={12} w="80%" /></div>)}</div>
      <div className="grid g-main section">
        <div className="card"><Skel h={16} w="30%" /><div style={{ height: 16 }} /><Skel h={260} r={12} /></div>
        <div className="card"><Skel h={16} w="40%" /><div style={{ height: 16 }} /><Skel h={260} r={12} /></div>
      </div>
      <div className="card section"><Skel h={16} w="25%" />{Array.from({ length: 6 }, (_, i) => <div key={i} style={{ marginTop: 14 }}><Skel h={18} /></div>)}</div>
    </div>
  );
}

export function LoadingBlock({ rows = 6 }: { rows?: number }) {
  return <div role="status" aria-label="Loading" style={{ display: "grid", gap: 12 }}>{Array.from({ length: rows }, (_, i) => <Skel key={i} h={20} w={i % 3 === 0 ? "70%" : "100%"} />)}</div>;
}

export function Tabs<T extends string>({ tabs, value: v, onChange }: { tabs: { id: T; label: React.ReactNode; count?: number }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={v === t.id} onClick={() => onChange(t.id)}>
          {t.label}{t.count !== undefined && <span className="badge">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Drawer({ title, subtitle, onClose, children, footer }: { title: string; subtitle?: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="muted" style={{ marginTop: 4 }}>{subtitle}</p>}
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>
  );
}

export function BarCell({ v, max = 100, color }: { v: number | null | undefined; max?: number; color?: string }) {
  if (v === null || v === undefined) return <span className="muted">Insufficient data</span>;
  return (
    <span className="bar-cell">
      <span className="bar"><i style={{ width: `${Math.max(0, Math.min(100, (v / max) * 100))}%`, background: color ?? scaleColor(v) }} /></span>
      <b>{pct(v)}</b>
    </span>
  );
}

export type Column<T> = {
  key: string;
  label: string;
  align?: "right";
  sort?: (row: T) => number | string | null;
  render: (row: T) => React.ReactNode;
  width?: number | string;
};

export function DataTable<T>({ rows, columns, rowKey, onRowClick, initialSort, empty, maxHeight }: {
  rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string; onRowClick?: (row: T) => void;
  initialSort?: { key: string; dir: "asc" | "desc" }; empty?: React.ReactNode; maxHeight?: number;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sort) return rows;
    const get = column.sort;
    return [...rows].sort((a, b) => {
      const x = get(a), y = get(b);
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      const cmp = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, sort, columns]);
  if (!rows.length) return <>{empty ?? <Empty title="Nothing to show yet" />}</>;
  return (
    <div className="table-wrap" style={maxHeight ? { maxHeight, overflow: "auto" } : undefined}>
      <table className="table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.align === "right" ? "r" : ""} style={c.width ? { width: c.width } : undefined} aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
                {c.sort ? (
                  <button onClick={() => setSort((s) => ({ key: c.key, dir: s?.key === c.key && s.dir === "desc" ? "asc" : "desc" }))}>
                    {c.label} {sort?.key === c.key ? (sort.dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />) : <ArrowUpDown size={12} opacity={0.45} />}
                  </button>
                ) : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)} className={onRowClick ? "clickable" : ""} onClick={onRowClick ? () => onRowClick(row) : undefined} tabIndex={onRowClick ? 0 : undefined} onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(row) : undefined}>
              {columns.map((c) => <td key={c.key} className={c.align === "right" ? "r" : ""}>{c.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Notice({ tone = "info", children, icon }: { tone?: "info" | "warn" | "error" | "ok"; children: React.ReactNode; icon?: React.ReactNode }) {
  return <div className={`notice notice-${tone}`}>{icon}{<div>{children}</div>}</div>;
}

export const measureOk = (m?: Measure | null) => value(m) !== null;
