"use client";

/** Charts over backend analytics. Every value plotted comes from the API; nothing is computed here. */
import Link from "next/link";
import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, Pie, PieChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, LabelList,
} from "recharts";
import type { CompareRow, TrendPoint } from "@/lib/api/types";
import { pct, scaleColor } from "@/lib/format";

export const SERIES = ["#0d7a69", "#2459d6", "#b86e00", "#6b4fd1", "#c2357a", "#0891b2", "#4d7c0f", "#9f1239"];
const AXIS = { stroke: "#cfd6e0", tickLine: false, axisLine: false } as const;

type TipProps = { active?: boolean; payload?: { name?: string; value?: number | null; color?: string; payload?: Record<string, unknown> }[]; label?: string | number };

function Tip({ active, payload, label, title, unit = "%" }: TipProps & { title?: (p: Record<string, unknown>) => string; unit?: string }) {
  if (!active || !payload?.length) return null;
  const head = title ? title(payload[0].payload ?? {}) : String(label ?? "");
  return (
    <div className="chart-tip">
      <b>{head}</b>
      {payload.map((p) => (
        <div className="row" key={p.name}>
          <span style={{ color: p.color }}>{p.name}</span>
          <strong>{p.value === null || p.value === undefined ? "—" : `${Number(p.value).toFixed(1)}${unit}`}</strong>
        </div>
      ))}
    </div>
  );
}

/** Mean and pass % across assessments, with the movement between them. */
export function TrendChart({ points, onSelect, height = 300 }: { points: TrendPoint[]; onSelect?: (key: string) => void; height?: number }) {
  const data = points.map((p) => ({ key: p.key, name: p.name, mean: p.mean.value, pass: p.pass_percent?.value ?? null, change: p.change }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 22, right: 16, left: -6, bottom: 0 }} onClick={(e) => { const key = (e as { activePayload?: { payload: { key: string } }[] })?.activePayload?.[0]?.payload?.key; if (key && onSelect) onSelect(key); }}>
          <defs>
            <linearGradient id="meanFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#0d7a69" stopOpacity={0.22} />
              <stop offset="1" stopColor="#0d7a69" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="name" {...AXIS} tick={{ fontSize: 12.5 }} />
          <YAxis domain={[0, 100]} {...AXIS} tick={{ fontSize: 12.5 }} tickFormatter={(v) => `${v}%`} width={48} />
          <Tooltip content={<Tip />} cursor={{ stroke: "#cfd6e0" }} />
          <Area type="monotone" dataKey="mean" name="Mean" stroke="#0d7a69" strokeWidth={2.6} fill="url(#meanFill)" dot={{ r: 4.5, fill: "#fff", strokeWidth: 2.4 }} activeDot={{ r: 6.5, cursor: onSelect ? "pointer" : undefined }}>
            <LabelList dataKey="mean" position="top" formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)}` : "")} style={{ fontSize: 12, fontWeight: 700, fill: "#0e1a2b" }} />
          </Area>
          <Line type="monotone" dataKey="pass" name="Pass %" stroke="#2459d6" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
          <Legend verticalAlign="bottom" height={28} iconType="plainline" wrapperStyle={{ fontSize: 13 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** One line per course when a scope spans courses with different components. */
export function MultiTrend({ series, height = 300 }: { series: { course_id: string; course_code: string; points: { name: string; mean: number | null }[] }[]; height?: number }) {
  const length = Math.max(0, ...series.map((s) => s.points.length));
  const data = Array.from({ length }, (_, i) => {
    const row: Record<string, number | string | null> = { position: `#${i + 1}` };
    series.forEach((s) => { row[s.course_code] = s.points[i]?.mean ?? null; row[`${s.course_code}__name`] = s.points[i]?.name ?? null; });
    return row;
  });
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 16, left: -6, bottom: 0 }}>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="position" {...AXIS} tick={{ fontSize: 12.5 }} />
          <YAxis domain={[30, 90]} {...AXIS} tick={{ fontSize: 12.5 }} tickFormatter={(v) => `${v}%`} width={48} />
          <Tooltip content={({ active, payload }) => active && payload?.length ? (
            <div className="chart-tip"><b>Assessment {String(payload[0].payload.position)}</b>
              {payload.map((p) => <div className="row" key={String(p.dataKey)}><span style={{ color: p.color }}>{String(p.dataKey)} · {String(p.payload[`${String(p.dataKey)}__name`] ?? "")}</span><strong>{p.value === null ? "—" : `${Number(p.value).toFixed(1)}%`}</strong></div>)}
            </div>) : null} />
          {series.map((s, i) => <Line key={s.course_id} type="monotone" dataKey={s.course_code} stroke={SERIES[i % SERIES.length]} strokeWidth={2.4} dot={{ r: 3.5 }} connectNulls />)}
          <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 13 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A histogram of course scores (or one assessment's percentages). */
export function Histogram({ bins, height = 260, label = "Students" }: { bins: { range: string; count: number }[]; height?: number; label?: string }) {
  const data = bins.map((b) => ({ ...b, mid: Number(b.range.split("-")[0]) + 5 }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 20, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="range" {...AXIS} tick={{ fontSize: 12 }} />
          <YAxis {...AXIS} tick={{ fontSize: 12 }} allowDecimals={false} width={56} />
          <Tooltip content={<Tip unit="" title={(p) => `${p.range}%`} />} cursor={{ fill: "#f2f4f7" }} />
          <Bar dataKey="count" name={label} radius={[6, 6, 0, 0]}>
            {data.map((d) => <Cell key={d.range} fill={scaleColor(d.mid)} stroke="rgba(14,26,43,.08)" />)}
            <LabelList dataKey="count" position="top" style={{ fontSize: 11.5, fontWeight: 700, fill: "#3a475a" }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Pass / below pass mark / no course score yet. */
export function PassDonut({ passed, failed, notScored, height = 240 }: { passed: number; failed: number; notScored: number; height?: number }) {
  const data = [
    { name: "At or above pass mark", value: passed, color: "#0d7a69" },
    { name: "Below pass mark", value: failed, color: "#e0786d" },
    { name: "No course score yet", value: notScored, color: "#d5dbe4" },
  ].filter((d) => d.value > 0);
  const total = passed + failed;
  return (
    <div style={{ height, position: "relative" }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="88%" paddingAngle={2} stroke="#fff" strokeWidth={2}>
            {data.map((d) => <Cell key={d.name} fill={d.color} />)}
          </Pie>
          <Tooltip content={<Tip unit="" />} />
        </PieChart>
      </ResponsiveContainer>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none", textAlign: "center" }}>
        <div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 800, color: "var(--ink)" }}>{total ? pct((passed * 100) / total) : "—"}</div>
          <div className="muted" style={{ fontSize: 12.5 }}>pass rate</div>
        </div>
      </div>
    </div>
  );
}

/** Ranked horizontal bars (sections, faculty, courses). Rows link to their drill-down. */
export function RankBars({ rows, href, height, metric = "average" }: { rows: CompareRow[]; href?: (row: CompareRow) => string; height?: number; metric?: "average" | "pass_percent" }) {
  const data = rows
    .filter((r) => r[metric].value !== null)
    .map((r) => ({ id: r.id, label: r.label, v: r[metric].value as number, row: r }))
    .sort((a, b) => b.v - a.v);
  const h = height ?? Math.max(180, data.length * 30 + 30);
  return (
    <div style={{ height: h }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 46, left: 8, bottom: 4 }}>
          <CartesianGrid stroke="#eef1f5" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} {...AXIS} tick={{ fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
          <YAxis type="category" dataKey="label" width={150} {...AXIS} tick={({ x, y, payload }) => {
            const item = data.find((d) => d.label === payload.value);
            const text = String(payload.value).length > 22 ? `${String(payload.value).slice(0, 21)}…` : String(payload.value);
            return (
              <g transform={`translate(${x},${y})`}>
                {href && item ? <Link href={href(item.row)}><text x={-6} y={4} textAnchor="end" fontSize={12.5} fill="#1d2939" style={{ cursor: "pointer" }}>{text}</text></Link> : <text x={-6} y={4} textAnchor="end" fontSize={12.5} fill="#1d2939">{text}</text>}
              </g>
            );
          }} />
          <Tooltip content={<Tip title={(p) => String(p.label)} />} cursor={{ fill: "#f2f4f7" }} />
          <Bar dataKey="v" name={metric === "average" ? "Average" : "Pass %"} radius={[0, 6, 6, 0]} barSize={16}>
            {data.map((d) => <Cell key={d.id} fill={scaleColor(d.v)} />)}
            <LabelList dataKey="v" position="right" formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)}%` : "")} style={{ fontSize: 12, fontWeight: 700, fill: "#1d2939" }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A tiny trend line for table rows. */
export function Sparkline({ values, width = 110, height = 30 }: { values: (number | null)[]; width?: number; height?: number }) {
  const pts = values.map((v, i) => ({ i, v }));
  const valid = values.filter((v): v is number => v !== null);
  if (valid.length < 2) return <span className="muted" style={{ fontSize: 12.5 }}>—</span>;
  const up = valid[valid.length - 1] >= valid[0];
  return (
    <div style={{ width, height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pts} margin={{ top: 3, right: 3, left: 3, bottom: 3 }}>
          <YAxis hide domain={["dataMin - 4", "dataMax + 4"]} />
          <Line type="monotone" dataKey="v" stroke={up ? "#0d7a69" : "#c2352a"} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** One student's percentages across assessments, against the pass mark. */
export function StudentLine({ points, passMark, classMeans, height = 260 }: { points: { name: string; pct: number | null; state?: string }[]; passMark: number; classMeans?: Record<string, number | null>; height?: number }) {
  const data = points.map((p) => ({ ...p, cls: classMeans?.[p.name] ?? null }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 22, right: 18, left: -6, bottom: 0 }}>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="name" {...AXIS} tick={{ fontSize: 12.5 }} />
          <YAxis domain={[0, 100]} {...AXIS} tick={{ fontSize: 12.5 }} tickFormatter={(v) => `${v}%`} width={48} />
          <ReferenceLine y={passMark} stroke="#c2352a" strokeDasharray="4 4" label={{ value: `Pass ${passMark}%`, position: "insideTopRight", fontSize: 12, fill: "#c2352a" }} />
          <Tooltip content={<Tip />} />
          {classMeans && <Line type="monotone" dataKey="cls" name="Class mean" stroke="#8894a6" strokeDasharray="5 4" strokeWidth={1.8} dot={false} connectNulls />}
          <Line type="monotone" dataKey="pct" name="Student" stroke="#0b3b66" strokeWidth={2.8} dot={{ r: 5, fill: "#fff", strokeWidth: 2.4 }} connectNulls={false}>
            <LabelList dataKey="pct" position="top" formatter={(v) => (typeof v === "number" ? v.toFixed(0) : "")} style={{ fontSize: 12, fontWeight: 700, fill: "#0e1a2b" }} />
          </Line>
          <Legend verticalAlign="bottom" height={26} wrapperStyle={{ fontSize: 13 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Rows x assessment columns, coloured by mean %. */
export function Heatmap({ columns, rows, href, max = 60 }: { columns: { key: string; name: string }[]; rows: { id: string; label: string; values: Record<string, number | null> }[]; href?: (id: string) => string; max?: number }) {
  if (!rows.length || !columns.length) return null;
  const shown = rows.slice(0, max);
  return (
    <div>
      <div className="heatmap" style={{ gridTemplateColumns: `minmax(90px, 160px) repeat(${columns.length}, minmax(56px, 1fr))` }}>
        <div />
        {columns.map((c) => <div className="hm-head" key={c.key} title={c.name}>{c.name}</div>)}
        {shown.map((r) => (
          <HeatRow key={r.id} row={r} columns={columns} href={href} />
        ))}
      </div>
      {rows.length > max && <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Showing {max} of {rows.length}. Open the comparison table for all.</p>}
      <HeatScale />
    </div>
  );
}

function HeatRow({ row, columns, href }: { row: { id: string; label: string; values: Record<string, number | null> }; columns: { key: string; name: string }[]; href?: (id: string) => string }) {
  return (
    <>
      <div className="hm-row" title={row.label}>{href ? <Link href={href(row.id)}>{row.label}</Link> : row.label}</div>
      {columns.map((c) => {
        const v = row.values[c.key];
        return <div className="hm-cell" key={c.key} style={{ background: scaleColor(v) }} title={`${row.label} · ${c.name}: ${v === null || v === undefined ? "no data" : `${v.toFixed(1)}%`}`}>{v === null || v === undefined ? "" : v.toFixed(0)}</div>;
      })}
    </>
  );
}

export function HeatScale() {
  const steps = [["<45", "var(--heat-1)"], ["45", "var(--heat-2)"], ["55", "var(--heat-3)"], ["62", "var(--heat-4)"], ["70", "var(--heat-5)"], ["78+", "var(--heat-6)"]];
  return <div className="heat-scale" style={{ marginTop: 12 }}>Mean %{steps.map(([l, c]) => <span key={l} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><i style={{ background: c }} />{l}</span>)}</div>;
}

/** Counts per attention rule, as bars. */
export function RuleBars({ counts, names, height = 240 }: { counts: Record<string, number>; names: Record<string, { short: string }>; height?: number }) {
  const data = Object.entries(counts).sort().map(([rule, count]) => ({ rule, name: names[rule]?.short ?? rule, count }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 20, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="name" {...AXIS} tick={{ fontSize: 11.5 }} interval={0} angle={-28} textAnchor="end" height={62} />
          <YAxis {...AXIS} tick={{ fontSize: 12 }} allowDecimals={false} width={56} />
          <Tooltip content={<Tip unit="" title={(p) => String(p.name)} />} cursor={{ fill: "#f2f4f7" }} />
          <Bar dataKey="count" name="Students" radius={[6, 6, 0, 0]} fill="#b86e00">
            <LabelList dataKey="count" position="top" style={{ fontSize: 11.5, fontWeight: 700, fill: "#3a475a" }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Grouped bars: e.g. semester or course comparison on average and pass %. */
export function GroupedBars({ rows, height = 260 }: { rows: CompareRow[]; height?: number }) {
  const data = rows.map((r) => ({ label: r.label, Average: r.average.value, "Pass %": r.pass_percent.value, Completion: r.completion_percent.value }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 16, right: 8, left: -10, bottom: 0 }}>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="label" {...AXIS} tick={{ fontSize: 12.5 }} />
          <YAxis domain={[0, 100]} {...AXIS} tick={{ fontSize: 12 }} tickFormatter={(v) => `${v}%`} width={48} />
          <Tooltip content={<Tip />} cursor={{ fill: "#f2f4f7" }} />
          <Bar dataKey="Average" fill="#0d7a69" radius={[5, 5, 0, 0]} />
          <Bar dataKey="Pass %" fill="#2459d6" radius={[5, 5, 0, 0]} />
          <Bar dataKey="Completion" fill="#b8c2d0" radius={[5, 5, 0, 0]} />
          <Legend verticalAlign="bottom" height={26} wrapperStyle={{ fontSize: 13 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
