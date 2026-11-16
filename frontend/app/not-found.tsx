import Link from "next/link";
import { GraduationCap } from "lucide-react";

/** Unmatched URLs: say so in the product's own voice and offer a way back. */
export default function NotFound() {
  return (
    <div className="boot" role="main">
      <div className="boot-card">
        <span className="brand-mark" style={{ width: 52, height: 52, margin: "0 auto", borderRadius: 16 }}>
          <GraduationCap size={26} />
        </span>
        <h1 style={{ fontSize: 22, marginTop: 16 }}>Page not found</h1>
        <p className="boot-step">There is no ACADLYTICS page at this address. It may have been moved, or the link was mistyped.</p>
        <Link className="btn btn-primary" href="/dashboard" style={{ marginTop: 16 }}>Go to your overview</Link>
      </div>
    </div>
  );
}
