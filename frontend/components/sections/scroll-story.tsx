"use client";

import { useRef, useState } from "react";
import { motion, MotionValue, useMotionValueEvent, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { ArrowDown, ArrowRight, ClipboardCheck, FileSpreadsheet, HeartHandshake, LineChart, ShieldAlert, Sparkles } from "lucide-react";

const chapters = [
  { name: "Spreadsheet", icon: FileSpreadsheet, title: "Start with the records you already keep.", detail: "Bring an existing assessment sheet into the workflow." },
  { name: "Validation", icon: ClipboardCheck, title: "Review the data before it becomes a record.", detail: "Check the import preview, errors, and rows before confirmation." },
  { name: "Analytics", icon: LineChart, title: "See what changed across assessments.", detail: "Compare assessment-level outcomes over time." },
  { name: "Attention", icon: ShieldAlert, title: "Make the review queue easy to act on.", detail: "Surface records below the configured threshold for faculty review." },
  { name: "Intervention", icon: HeartHandshake, title: "Keep the next step in faculty hands.", detail: "Record a support action and its intended follow-up." },
  { name: "Outcome", icon: Sparkles, title: "Return to the data and review the outcome.", detail: "Look at subsequent assessment results without implying cause." },
];

function StoryBeat({ chapter, index, progress, reduced, active }: { chapter: (typeof chapters)[number]; index: number; progress: MotionValue<number>; reduced: boolean; active: boolean }) {
  const start = index / chapters.length;
  const end = (index + 1) / chapters.length;
  const scale = useTransform(progress, [start, end], [0.985, 1]);
  const Icon = chapter.icon;
  return <motion.div className={`story-beat ${reduced ? "story-beat-static" : ""}`} initial={false} animate={reduced ? undefined : { opacity: active ? 1 : 0, y: active ? 0 : 13 }} transition={{ duration: reduced ? 0 : 0.24, ease: "easeOut" }} style={reduced ? undefined : { scale }} aria-hidden={reduced ? undefined : !active}><div className="story-beat-meta"><span>0{index + 1} / 0{chapters.length}</span><span><Icon size={14} /> {chapter.name}</span></div><h3>{chapter.title}</h3><p>{chapter.detail}</p></motion.div>;
}

function StoryVisual({ chapter, index }: { chapter: (typeof chapters)[number]; index: number }) {
  const Icon = chapter.icon;
  return <div className={`story-visual story-visual-${index + 1}`}><div className="story-visual-top"><span>ACADLYTICS / WORKFLOW</span><span>DEMO VIEW</span></div><div className="story-flow-node"><span className="story-node-icon"><Icon size={19} /></span><div><small>STEP 0{index + 1}</small><b>{chapter.name}</b><span>{chapter.detail}</span></div><ArrowRight size={15} /></div><div className="story-visual-lines"><i /><i /><i /></div><div className="story-visual-foot"><span>FACULTY-LED</span><span>ASSESSMENT-LEVEL DATA</span></div></div>;
}

export function ScrollStory() {
  const ref = useRef<HTMLElement>(null);
  const [active, setActive] = useState(0);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const progressWidth = useTransform(scrollYProgress, [0, 1], [0, 1]);
  useMotionValueEvent(scrollYProgress, "change", (value) => { if (reduced) return; setActive(Math.min(chapters.length - 1, Math.floor(value * chapters.length))); });
  return <section ref={ref} className={`story-scroll-section ${reduced ? "story-reduced" : ""}`} aria-label="From assessment data to measured outcomes">
    <div className="story-sticky"><div className="story-inner"><div className="story-heading"><div className="section-kicker">THE DATA-TO-ACTION LOOP <span>01 — 06</span></div><h2>Every step stays<br /><em>connected.</em></h2><p>Follow the journey from a spreadsheet to a reviewed outcome, with context visible at every stage.</p><div className="story-current"><span>NOW SHOWING</span><b>0{active + 1} / 0{chapters.length}</b></div><div className="story-hint"><ArrowDown size={13} /> Scroll to follow the workflow</div></div>
      <div className="story-stage" aria-live="polite"><div className="story-stage-orbit" /><div className="story-scenes">{chapters.map((chapter, index) => <StoryBeat key={chapter.name} chapter={chapter} index={index} progress={scrollYProgress} reduced={!!reduced} active={active === index} />)}</div><StoryVisual chapter={chapters[active]} index={active} /><div className="story-progress"><span /><motion.i style={reduced ? undefined : { scaleX: progressWidth, transformOrigin: "left" }} /></div></div>
    </div></div>
  </section>;
}
