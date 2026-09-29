import type { CSSProperties } from "react";

function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <span aria-hidden="true" className={`skeleton-shimmer ${className}`} style={style} />;
}

export function SkeletonText({ width = "62%" }: { width?: string }) { return <Skeleton className="skeleton-text" style={{ width }} />; }
export function SkeletonAvatar() { return <Skeleton className="skeleton-avatar" />; }
export function SkeletonMetric() { return <div className="skeleton-metric"><SkeletonText width="44%" /><Skeleton className="skeleton-number" /><SkeletonText width="68%" /></div>; }
export function SkeletonCard() { return <div className="skeleton-card"><SkeletonText width="38%" /><Skeleton className="skeleton-heading" /><SkeletonText /><SkeletonText width="76%" /></div>; }
export function SkeletonChart() { return <div className="skeleton-chart"><SkeletonText width="30%" /><div className="skeleton-chart-art"><i /><i /><i /><i /><i /></div></div>; }
export function SkeletonTable() { return <div className="skeleton-table"><SkeletonText width="24%" />{Array.from({ length: 5 }, (_, index) => <div className="skeleton-table-row" key={index}><SkeletonAvatar /><SkeletonText width="27%" /><SkeletonText width="18%" /><SkeletonText width="13%" /></div>)}</div>; }
export function SkeletonSidebar() { return <aside className="skeleton-sidebar"><Skeleton className="skeleton-brand" />{Array.from({ length: 7 }, (_, index) => <Skeleton className="skeleton-nav" key={index} />)}</aside>; }
export function SkeletonDashboard() { return <div className="skeleton-dashboard" role="status" aria-label="Loading academic workspace"><SkeletonSidebar /><main><Skeleton className="skeleton-topbar" /><div className="skeleton-content"><SkeletonCard /><div className="skeleton-metrics">{Array.from({ length: 4 }, (_, index) => <SkeletonMetric key={index} />)}</div><div className="skeleton-columns"><SkeletonChart /><SkeletonCard /></div><SkeletonTable /></div></main></div>; }
