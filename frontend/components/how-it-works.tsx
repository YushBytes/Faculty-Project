/**
 * A short, collapsed-by-default explanation under a page heading (native <details>, so it is
 * keyboard- and screen-reader-accessible with no script). It describes what the backend does;
 * it never restates numbers the engine owns — each flag and measure shows its own values.
 */
import { HelpCircle } from "lucide-react";

export function HowItWorks({ children, label = "How it works" }: { children: React.ReactNode; label?: string }) {
  return (
    <details className="how-it-works">
      <summary><HelpCircle size={15} aria-hidden="true" /> {label}</summary>
      <div className="how-body">{children}</div>
    </details>
  );
}
