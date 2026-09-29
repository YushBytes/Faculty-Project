import Link from "next/link";
import { ArrowDown, ArrowRight, ArrowUpRight, BarChart3, ChevronRight, CircleDot, FileSpreadsheet, Layers3, ShieldCheck, Sparkles } from "lucide-react";
import { AnimatedCounter, BlurReveal, CursorSpotlight, FadeUp, MagneticButton, MeshBackground, TextReveal, TiltCard } from "@/components/animations/motion-primitives";
import { ScrollStory } from "@/components/sections/scroll-story";
import { SocialProof } from "@/components/sections/social-proof";

const steps = [
  { number: "01", title: "Bring the marks you already have", body: "Import a spreadsheet, review every row, and confirm only when the data is ready." },
  { number: "02", title: "See what changed", body: "Compare assessment outcomes across your classes with clear, traceable summaries." },
  { number: "03", title: "Follow through", body: "Record an intervention, then review performance after the next assessment." },
];

export default function Home() {
  return (
    <main className="landing">
      <nav className="landing-nav" aria-label="Main navigation">
        <Link className="brand" href="/" aria-label="ACADLYTICS home"><span className="brand-mark"><CircleDot size={18} /></span> ACADLYTICS</Link>
        <div className="landing-links"><a href="#product">Product</a><a href="#workflow">How it works</a><a href="#principles">Principles</a></div>
        <div className="nav-actions"><Link className="nav-login" href="/login">Log in</Link><Link className="button button-primary button-small" href="/dashboard">Explore demo <ArrowUpRight size={15} /></Link></div>
      </nav>

      <section className="hero-wrap">
        <MeshBackground />
        <CursorSpotlight />
        <div className="hero-copy">
          <FadeUp delay={0.05}><div className="eyebrow"><span className="eyebrow-pulse" /> SRM INSTITUTE OF SCIENCE AND TECHNOLOGY <i className="landing-eyebrow-divider" /> A clearer view of class performance</div></FadeUp>
          <h1 className="hero-title"><span className="hero-title-line"><TextReveal delay={0.12}>Make every</TextReveal></span><span className="hero-title-line"><TextReveal delay={0.24}><span className="hero-accent">assessment</span></TextReveal></span><span className="hero-title-line"><TextReveal delay={0.36}>count.</TextReveal></span></h1>
          <BlurReveal delay={0.33}><p className="hero-description">A focused workspace for faculty to review assessment results, spot students who need attention, and measure what happens next.</p></BlurReveal>
          <FadeUp delay={0.42}><div className="hero-actions"><MagneticButton><Link className="button button-primary hero-primary-cta" href="/dashboard">Open the workspace <ArrowRight size={16} /></Link></MagneticButton><a className="text-link" href="#workflow">See how it works <ArrowDown size={15} /></a></div></FadeUp>
          <FadeUp delay={0.53}><div className="hero-note"><ShieldCheck size={15} /> Clear data. Traceable decisions. Faculty-led action.</div></FadeUp>
        </div>
        <div className="hero-visual" id="product" aria-label="Illustrative class performance dashboard preview">
          <div className="visual-orbit orbit-a" /><div className="visual-orbit orbit-b" />
          <TiltCard className="preview-tilt"><div className="preview-window">
            <div className="preview-top"><div className="window-dots"><i /><i /><i /></div><span>ACADEMIC OVERVIEW</span><span className="live-label"><b /> DEMO DATA</span></div>
            <div className="preview-content">
              <div className="preview-heading"><div><span className="micro-label">MONDAY, 26 SEPTEMBER</span><h2>Good morning, Dr. Rao</h2></div><div className="avatar">AR</div></div>
              <div className="preview-stats"><div><span>ASSESSMENTS</span><strong><AnimatedCounter value="08" /></strong><small>Across 3 courses</small></div><div><span>STUDENTS</span><strong><AnimatedCounter value="124" /></strong><small>Active this term</small></div><div><span>NEEDS REVIEW</span><strong className="warning-number"><AnimatedCounter value="12" /></strong><small>Below threshold</small></div></div>
              <div className="preview-chart-head"><div><b>Assessment average</b><small>Recent assessments · illustrative</small></div><span>+4.2 pts</span></div>
              <div className="chart-art"><div className="chart-grid"><i /><i /><i /><i /></div><svg viewBox="0 0 560 136" role="img" aria-label="Illustrative assessment average trend"><defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#42d6ca" stopOpacity=".23"/><stop offset="1" stopColor="#42d6ca" stopOpacity="0"/></linearGradient></defs><path d="M0 104 C48 88 64 99 104 76 S165 87 205 65 S270 88 309 54 S370 70 410 45 S471 65 511 30 S540 34 560 15 L560 136 L0 136Z" fill="url(#area)"/><path d="M0 104 C48 88 64 99 104 76 S165 87 205 65 S270 88 309 54 S370 70 410 45 S471 65 511 30 S540 34 560 15" fill="none" stroke="#55e1d1" strokeWidth="2.2"/><circle cx="410" cy="45" r="4" fill="#0b1116" stroke="#55e1d1" strokeWidth="2"/></svg><div className="chart-months"><span>WEEK 01</span><span>WEEK 02</span><span>WEEK 03</span><span>WEEK 04</span><span>WEEK 05</span></div></div>
              <div className="preview-footer"><div className="mini-pill"><span className="pill-dot" /> Data checked</div><span>Updated just now</span></div>
            </div>
          </div></TiltCard>
          <div className="floating-callout"><span className="callout-icon"><BarChart3 size={16} /></span><div><b>Latest assessment</b><small>Average increased 4.2 points</small></div><ArrowUpRight size={14} /></div>
          <span className="visual-index">01 <i /> 03</span>
        </div>
      </section>

      <div className="ticker"><span>ACADEMIC PERFORMANCE, IN CONTEXT</span><i /><span>FACULTY-LED INSIGHT</span><i /><span>BUILT AROUND YOUR RECORDS</span><i /><span>ACADEMIC PERFORMANCE, IN CONTEXT</span></div>

      <ScrollStory />

      <section className="section workflow" id="workflow">
        <div className="section-kicker">THE WORKFLOW <span>01 — 03</span></div>
        <div className="section-title-row"><h2>From a marksheet<br />to a meaningful next step.</h2><p>One place to move from the records you maintain to clear, considered action with your students.</p></div>
        <div className="workflow-grid">{steps.map((step, index) => <article className={`workflow-step step-${index + 1}`} key={step.number}><div className="step-number">{step.number}<span><ArrowUpRight size={14} /></span></div><div className="step-rule" /><h3>{step.title}</h3><p>{step.body}</p></article>)}</div>
        <div className="workflow-foot"><span>Designed for the way academic teams work</span><span className="foot-mark">AC / 01</span></div>
      </section>

      <section className="principles" id="principles"><div className="principles-inner"><div className="principles-copy"><div className="section-kicker">BUILT ON TRUST <span>02 — 03</span></div><h2>Insight you can<br /><em>stand behind.</em></h2><p>Academic decisions deserve more than a black box. ACADLYTICS keeps the evidence visible and the next step in faculty hands.</p><Link className="text-link" href="/analytics">Explore analytics <ArrowRight size={15} /></Link></div><div className="principles-list"><article><span className="principle-icon"><FileSpreadsheet size={17} /></span><div><b>Work from existing records</b><p>Bring the assessment data your department already maintains.</p></div><span className="principle-no">01</span></article><article><span className="principle-icon"><Layers3 size={17} /></span><div><b>Keep context close</b><p>Review outcomes by class and assessment, with the underlying records nearby.</p></div><span className="principle-no">02</span></article><article><span className="principle-icon"><ShieldCheck size={17} /></span><div><b>Faculty stay in control</b><p>Use measured language and decide what action makes sense for your class.</p></div><span className="principle-no">03</span></article></div></div></section>

      <SocialProof />

      <section className="closing-cta"><div><div className="section-kicker">YOUR CLASSES, IN CLEARER FOCUS <span>03 — 03</span></div><h2>Start with the data<br />you already have.</h2></div><MagneticButton><Link className="button button-light" href="/dashboard">Enter the workspace <ChevronRight size={17} /></Link></MagneticButton><Sparkles className="cta-spark" size={28} /></section>
      <footer className="landing-footer"><Link className="brand" href="/"><span className="brand-mark"><CircleDot size={17} /></span> ACADLYTICS</Link><span>SRM Institute of Science and Technology · Academic Performance Intelligence</span><span>© 2026 ACADLYTICS</span></footer>
    </main>
  );
}
