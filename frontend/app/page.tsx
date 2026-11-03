import Link from "next/link";
import { ArrowRight, BarChart3, FileCheck2, FileSpreadsheet, GraduationCap, HeartHandshake, Layers3, ShieldAlert, ShieldCheck } from "lucide-react";
import { FadeUp, MagneticButton, TextReveal, TiltCard } from "@/components/animations/motion-primitives";

const features = [
  { icon: FileSpreadsheet, title: "Imports the TLP reports you already have", body: "SRM TLP5 mark reports as Excel, CSV or PDF. Each file is checked against the course, semester, test name and component maximum, previewed, corrected and only then written." },
  { icon: BarChart3, title: "One analytics engine for every level", body: "Class, section, course, faculty, department and institution views pool the same per-student results. The dashboard and the downloaded report never disagree." },
  { icon: ShieldAlert, title: "Attention you can explain", body: "Seven deterministic rules — low performance, failed latest, sharp decline and more — each with its evidence. No opaque risk score." },
  { icon: HeartHandshake, title: "Interventions with observed outcomes", body: "Record the support given and see what happened at the next assessment, alongside peers — reported, never claimed as cause." },
  { icon: FileCheck2, title: "Reports in PDF, Excel and CSV", body: "Presentation-ready reports for a class, section, course, coordinator, department or the institution, for either semester or the full year." },
  { icon: ShieldCheck, title: "Absent is not zero", body: "Absent, exempt and missing marks are kept apart from a real 0 everywhere — in storage, analytics, charts and exports." },
];

const hierarchy = [
  ["Administrator", "The whole institution", "01"],
  ["Head of Department", "Every section, course and faculty member of the department", "02"],
  ["Academic Head", "The course portfolio and its coordinators", "03"],
  ["Course Coordinator", "One course across every section and faculty member", "04"],
  ["Faculty", "Their own classes and students", "05"],
];

export default function Landing() {
  return (
    <main className="landing">
      <header className="l-nav">
        <Link className="brand" href="/"><span className="brand-mark"><GraduationCap size={19} /></span>ACADLYTICS</Link>
        <nav aria-label="Sections"><a href="#product">Product</a><a href="#hierarchy">Hierarchy</a><a href="#workflow">Workflow</a></nav>
        <div className="right"><Link className="btn btn-primary" href="/login">Sign in <ArrowRight size={16} /></Link></div>
      </header>

      <section className="l-hero">
        <div>
          <FadeUp><span className="l-kicker"><i /> SRM Institute of Science and Technology</span></FadeUp>
          <h1>
            <TextReveal>Academic performance,</TextReveal><br />
            <TextReveal delay={0.12}><span className="hl">clearly measured.</span></TextReveal>
          </h1>
          <FadeUp delay={0.2}><p className="lead">From the TLP marks each faculty member uploads to the view the HOD presents — one institutional system for ingestion, analytics, attention, interventions and reports.</p></FadeUp>
          <FadeUp delay={0.3}><div className="cta"><MagneticButton><Link className="btn btn-primary" href="/login">Open the workspace <ArrowRight size={17} /></Link></MagneticButton><a className="btn" href="#workflow">How it works</a></div></FadeUp>
        </div>
        <FadeUp delay={0.15}>
          <TiltCard>
            <div className="l-preview" aria-label="Illustration of the assessment trend view">
              <div className="bar"><i /><i /><i /><span>Course overview · illustration</span></div>
              <svg viewBox="0 0 560 250" role="img" aria-label="Illustrative trend across four assessments with a dip at the second">
                <defs><linearGradient id="lg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#0d7a69" stopOpacity=".22" /><stop offset="1" stopColor="#0d7a69" stopOpacity="0" /></linearGradient></defs>
                {[40, 90, 140, 190].map((y) => <line key={y} x1="30" x2="540" y1={y} y2={y} stroke="#eef1f5" />)}
                <path d="M40 92 L200 150 L360 104 L520 78 L520 220 L40 220 Z" fill="url(#lg)" />
                <path d="M40 92 L200 150 L360 104 L520 78" fill="none" stroke="#0d7a69" strokeWidth="3" />
                <path d="M40 60 L200 108 L360 70 L520 52" fill="none" stroke="#2459d6" strokeWidth="2" strokeDasharray="6 5" />
                {[[40, 92, "FJ-I"], [200, 150, "FJ-II"], [360, 104, "FJ-III"], [520, 78, "LLJ-II"]].map(([x, y, l]) => (
                  <g key={String(l)}><circle cx={Number(x)} cy={Number(y)} r="6" fill="#fff" stroke="#0d7a69" strokeWidth="3" /><text x={Number(x)} y={238} textAnchor="middle" fontSize="13" fill="#5e6b7e">{l}</text></g>
                ))}
                <rect x="170" y="160" rx="8" width="120" height="30" fill="#fcebea" /><text x="230" y="180" textAnchor="middle" fontSize="13" fontWeight="700" fill="#c2352a">−9.8 pp drop</text>
              </svg>
            </div>
          </TiltCard>
        </FadeUp>
      </section>

      <section className="l-section" id="product">
        <h2>Everything a department needs to understand its results.</h2>
        <p className="sub">Built on the institution&apos;s own records and rules. Every number is traceable to the marks behind it.</p>
        <div className="l-feature-grid">{features.map((f, i) => <FadeUp key={f.title} delay={i * 0.05}><article className="l-feature"><span className="ic"><f.icon size={21} /></span><h3>{f.title}</h3><p>{f.body}</p></article></FadeUp>)}</div>
      </section>

      <section className="l-section" id="hierarchy" style={{ background: "var(--bg)" }}>
        <h2>One system, five levels of responsibility.</h2>
        <p className="sub">Each person sees exactly their part of the institution — enforced by the server, not the menu.</p>
        <div className="l-hier">{hierarchy.map(([t, d, n]) => <div key={t}><span>{n}</span><br /><b>{t}</b><p>{d}</p></div>)}</div>
      </section>

      <section className="l-section l-band" id="workflow">
        <h2>From a TLP report to a decision.</h2>
        <p className="sub">The same path for one section or all ninety-seven.</p>
        <div className="l-steps">
          <div><span>01 · UPLOAD</span><br /><b>Drop the reports</b><p>Many files at once; each is routed to its section and assessment automatically.</p></div>
          <div><span>02 · CHECK</span><br /><b>Preview and correct</b><p>Wrong maximum, wrong course, a mark above the maximum — caught before anything is written.</p></div>
          <div><span>03 · ANALYSE</span><br /><b>See what moved</b><p>Trends, distributions and comparisons update the moment marks are confirmed.</p></div>
          <div><span>04 · ACT</span><br /><b>Support and report</b><p>Review attention, record interventions and download the report for the meeting.</p></div>
        </div>
      </section>

      <section className="l-section" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div><h2>Start with the marks you already have.</h2><p className="sub">Sign in with your institutional account.</p></div>
        <Link className="btn btn-dark" style={{ height: 50, padding: "0 26px" }} href="/login"><Layers3 size={17} /> Sign in to ACADLYTICS</Link>
      </section>
      <footer className="l-footer"><span>ACADLYTICS · Academic Performance Intelligence</span><span>SRM Institute of Science and Technology</span></footer>
    </main>
  );
}
