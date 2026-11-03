"use client";

/** A drill-down page for one entity (department, course, section, faculty member): the same
 * dashboard, narrowed by one filter, with breadcrumbs back up the hierarchy. */
import Link from "next/link";
import { FileBarChart } from "lucide-react";
import { useScope } from "@/lib/auth/session";
import type { Overview, ScopeFilters } from "@/lib/api/types";
import { OverviewDashboard, periodQuery, useOverview, type Variant } from "@/components/overview";
import { ErrorState, LoadingDashboard, PageHead } from "@/components/ui";
import { crumbHref } from "@/components/ui";

export function ScopePage({ fixed, variant, eyebrow, title, description, extra, tabs }: {
  fixed: ScopeFilters; variant: Variant; eyebrow: string;
  title: (o: Overview) => React.ReactNode; description?: (o: Overview) => React.ReactNode;
  extra?: (o: Overview) => React.ReactNode; tabs?: (o: Overview) => React.ReactNode;
}) {
  const scope = useScope(fixed);
  const q = periodQuery(scope);
  const { data, error, loading, reload } = useOverview(scope);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading && !data) return <LoadingDashboard />;
  if (!data) return null;
  const crumbs = [{ href: `/dashboard${q}`, label: data.scope.root }, ...data.scope.crumbs.map((c) => ({ href: crumbHref(c, q), label: c.label }))];
  const reportQuery = new URLSearchParams(q.replace("?", ""));
  for (const [key, value] of Object.entries(fixed)) if (value) reportQuery.set(key, value);
  return (
    <>
      <PageHead
        crumbs={crumbs}
        eyebrow={`${eyebrow} · ${data.period}`}
        title={title(data)}
        description={description?.(data)}
        actions={<>{extra?.(data)}<Link className="btn" href={`/reports?${reportQuery.toString()}`}><FileBarChart size={17} /> Report</Link></>}
      />
      {tabs ? tabs(data) : <OverviewDashboard filters={scope} variant={variant} data={data} />}
    </>
  );
}
