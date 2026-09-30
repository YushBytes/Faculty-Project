"use client";

import Link from "next/link";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { insightsApi, offeringsApi, type OutcomeGroup } from "@/lib/api/endpoints";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, Card, Empty, ErrorState, Kpi, LoadingDashboard, Notice, PageHead } from "@/components/ui";
import { INTERVENTION_KINDS, date, pct, signed } from "@/lib/format";

export default function InterventionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const offeringId = useSearchParams().get("offering") ?? "";
  const list = useApi(() => insightsApi.interventions({ offering_id: offeringId, semester: "YEAR" }, { limit: 200 }), [offeringId], !!offeringId);
  const outcomes = useApi(() => offeringsApi.interventionOutcomes(offeringId), [offeringId], !!offeringId);
  if (!offeringId) return <Empty title="Open an intervention from the list" />;
  if (list.error) return <ErrorState error={list.error} retry={list.reload} />;
  if (list.loading || !list.data) return <LoadingDashboard />;
  const item = list.data.items.find((i) => i.id === id);
  if (!item) return <Empty title="Intervention not found in your scope" />;
  const outcome = outcomes.data?.outcomes.find((o) => o.intervention_id === id);
  return (
    <>
      <PageHead crumbs={[{ href: "/interventions", label: "Interventions" }, { label: INTERVENTION_KINDS[item.kind] ?? item.kind }]} eyebrow={`Intervention · ${item.offering}`} title={INTERVENTION_KINDS[item.kind] ?? item.kind}
        description={<>Recorded {date(item.recorded_on ?? item.created_at)} by {item.recorded_by ?? "—"} · <Link href={`/classes/${item.offering_id}`} style={{ color: "var(--accent)" }}>{item.offering}</Link></>} actions={<Badge tone={item.status === "completed" ? "green" : "blue"}>{item.status}</Badge>} />
      <div className="grid g-main">
        <Card title="Observed outcome" subtitle={outcome?.follow_up_assessment ? `Before vs ${outcome.follow_up_assessment.code}` : "Measured at the next published assessment"}>
          {!outcome ? <Empty title="Loading outcome…" /> : outcome.net_change.value === null ? (
            <Notice tone="warn">{outcome.label.reason ?? outcome.net_change.reason ?? "Not yet measurable — the next assessment has not been published."}</Notice>
          ) : (
            <>
              <div className="kpis" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
                <Group g={outcome.target} title="Students supported" />
                <Group g={outcome.peers} title="Classmates" />
                <Kpi label="Difference in change" tone="accent" value={signed(outcome.net_change.value)} foot={<Badge tone="violet">{outcome.label.value?.replaceAll("_", " ")}</Badge>} />
              </div>
              <p className="muted" style={{ marginTop: 14 }}>{outcome.explanation.narrative}</p>
              {outcome.explanation.caveats.map((c) => <p key={c} className="muted" style={{ fontSize: 13.5, marginTop: 6 }}>• {c}</p>)}
            </>
          )}
        </Card>
        <Card title="Students">
          <div className="list">{item.students.map((s) => <Link key={s.id} className="list-item" href={`/students/${s.id}`}><div className="grow"><b>{s.name}</b><small>{s.register_number}</small></div></Link>)}</div>
          {item.note && <><div className="label" style={{ marginTop: 14 }}>Note</div><p style={{ marginTop: 4 }}>{item.note}</p></>}
        </Card>
      </div>
    </>
  );
}

function Group({ g, title }: { g: OutcomeGroup; title: string }) {
  return <Kpi label={`${title} (n=${g.n})`} value={signed(g.change.value)} foot={<>{pct(g.pre_mean.value)} → {pct(g.post_mean.value)}</>} />;
}
