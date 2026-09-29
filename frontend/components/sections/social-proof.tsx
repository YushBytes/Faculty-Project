"use client";

import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight, Quote } from "lucide-react";
import { AnimatedCounter, FadeUp } from "@/components/animations/motion-primitives";

const logos = ["NORTHSTAR / DEMO", "CAMPUS OFFICE", "FACULTY NETWORK", "ACADEMIC GROUP", "LEARNING CENTRE"];
const voices = [
  { quote: "I can get from the marksheet to the records that need a closer look without losing the context of the class.", name: "Dr. Ananya Rao", role: "Faculty · Computer Science" },
  { quote: "The useful part is seeing what changed and keeping the actual assessment records close by.", name: "Prof. Kiran Mehta", role: "Faculty · Applied Mathematics" },
  { quote: "A simple follow-up log makes it easier to return to the next assessment and review the outcome.", name: "Dr. Leena Thomas", role: "Programme coordinator" },
];

export function SocialProof() {
  const [active, setActive] = useState(0);
  const reduced = useReducedMotion();
  const change = (step: number) => setActive((active + step + voices.length) % voices.length);
  const item = voices[active];
  return <section className="social-proof-section" aria-label="Product examples and demo testimonials"><div className="social-proof-inner">
    <FadeUp><div className="section-kicker">A SHARED VIEW OF THE WORK <span>DEMO CONTENT</span></div><div className="logo-marquee" aria-label="Placeholder demo partner logos"><div className="logo-track">{[...logos, ...logos].map((logo, index) => <span className="demo-logo" key={`${logo}-${index}`} aria-hidden={index >= logos.length}><i />{logo}</span>)}</div></div><p className="marquee-caption">Placeholder names for the demo experience · no institutional affiliation implied</p></FadeUp>
    <div className="proof-grid"><FadeUp className="proof-stats"><span className="panel-kicker">DEMO WORKSPACE SNAPSHOT</span><h2>Academic work,<br /><em>in one view.</em></h2><div className="proof-stat-list"><div><b><AnimatedCounter value="124" /></b><span>fictional students</span></div><div><b><AnimatedCounter value="08" /></b><span>assessment records</span></div><div><b><AnimatedCounter value="03" /></b><span>demo course sections</span></div></div><small>Illustrative counts from local mock data.</small></FadeUp>
      <FadeUp className="testimonial-panel" delay={0.1}><div className="testimonial-top"><span className="quote-mark"><Quote size={17} /></span><span className="panel-kicker">DEMO TESTIMONIALS · FICTIONAL</span><span className="testimonial-counter">0{active + 1} / 0{voices.length}</span></div><div className="testimonial-content" aria-live="polite"><AnimatePresence mode="wait"><motion.div key={active} initial={reduced ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={reduced ? undefined : { opacity: 0, y: -8 }} transition={{ duration: reduced ? 0 : 0.28 }}><blockquote>“{item.quote}”</blockquote><div className="testimonial-author"><span className="testimonial-avatar">{item.name.split(" ").slice(-1)[0][0]}R</span><span><b>{item.name}</b><small>{item.role} · sample profile</small></span></div></motion.div></AnimatePresence></div><div className="testimonial-controls"><span>Sample copy for UI preview only</span><div><button aria-label="Previous testimonial" onClick={() => change(-1)}><ArrowLeft size={15} /></button><button aria-label="Next testimonial" onClick={() => change(1)}><ArrowRight size={15} /></button></div></div></FadeUp>
    </div>
  </div></section>;
}

