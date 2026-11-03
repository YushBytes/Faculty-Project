"use client";

import { animate, motion, useInView, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { useEffect, useRef, useState } from "react";

type ChildrenProps = { children: React.ReactNode; className?: string; delay?: number };

export function MeshBackground({ className = "" }: { className?: string }) {
  const reduce = useReducedMotion();
  return <motion.div aria-hidden="true" className={`mesh-background ${className}`} animate={reduce ? undefined : { backgroundPosition: ["0% 0%", "100% 55%", "0% 0%"] }} transition={reduce ? undefined : { duration: 26, repeat: Infinity, ease: "linear" }} />;
}

export function CursorSpotlight({ className = "" }: { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    const host = el?.parentElement;
    if (!el || !host || reduce) return;
    const move = (event: PointerEvent) => {
      if (!(event.target instanceof Node) || !host.contains(event.target)) return;
      const rect = host.getBoundingClientRect();
      el.style.setProperty("--spot-x", `${event.clientX - rect.left}px`);
      el.style.setProperty("--spot-y", `${event.clientY - rect.top}px`);
      el.style.setProperty("--spot-opacity", "1");
    };
    const leave = () => el.style.setProperty("--spot-opacity", "0");
    window.addEventListener("pointermove", move, { passive: true });
    host.addEventListener("pointerleave", leave);
    return () => { window.removeEventListener("pointermove", move); host.removeEventListener("pointerleave", leave); };
  }, [reduce]);
  return <div ref={ref} aria-hidden="true" className={`cursor-spotlight ${className}`} />;
}

export function FadeUp({ children, className = "", delay = 0 }: ChildrenProps) {
  const reduce = useReducedMotion();
  return <motion.div className={className} initial={reduce ? false : { opacity: 0, y: 22 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.16 }} transition={{ duration: reduce ? 0 : 0.65, delay: reduce ? 0 : delay, ease: [0.22, 1, 0.36, 1] }}>{children}</motion.div>;
}

export function BlurReveal({ children, className = "", delay = 0 }: ChildrenProps) {
  const reduce = useReducedMotion();
  return <motion.div className={className} initial={reduce ? false : { opacity: 0, filter: "blur(10px)", y: 12 }} whileInView={{ opacity: 1, filter: "blur(0px)", y: 0 }} viewport={{ once: true, amount: 0.2 }} transition={{ duration: reduce ? 0 : 0.8, delay: reduce ? 0 : delay, ease: "easeOut" }}>{children}</motion.div>;
}

export function TextReveal({ children, className = "", delay = 0 }: ChildrenProps) {
  const reduce = useReducedMotion();
  return <motion.span className={`text-reveal ${className}`} initial={reduce ? false : { opacity: 0, y: "110%" }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduce ? 0 : 0.72, delay: reduce ? 0 : delay, ease: [0.22, 1, 0.36, 1] }}>{children}</motion.span>;
}

export function MagneticButton({ children, className = "" }: ChildrenProps) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 220, damping: 18, mass: 0.18 });
  const sy = useSpring(y, { stiffness: 220, damping: 18, mass: 0.18 });
  return <motion.div className={`magnetic-wrap ${className}`} style={reduce ? undefined : { x: sx, y: sy }} onPointerMove={reduce ? undefined : (event) => { const rect = event.currentTarget.getBoundingClientRect(); x.set((event.clientX - rect.left - rect.width / 2) * 0.12); y.set((event.clientY - rect.top - rect.height / 2) * 0.16); }} onPointerLeave={() => { x.set(0); y.set(0); }}>{children}</motion.div>;
}

export function TiltCard({ children, className = "" }: ChildrenProps) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const rotateX = useSpring(useTransform(y, [-0.5, 0.5], [3, -3]), { stiffness: 180, damping: 24 });
  const rotateY = useSpring(useTransform(x, [-0.5, 0.5], [-3, 3]), { stiffness: 180, damping: 24 });
  return <motion.div className={`tilt-card ${className}`} style={reduce ? undefined : { rotateX, rotateY, transformPerspective: 900 }} onPointerMove={reduce ? undefined : (event) => { const rect = event.currentTarget.getBoundingClientRect(); x.set((event.clientX - rect.left) / rect.width - 0.5); y.set((event.clientY - rect.top) / rect.height - 0.5); }} onPointerLeave={() => { x.set(0); y.set(0); }}>{children}</motion.div>;
}

export function AnimatedCounter({ value, className = "" }: { value: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const visible = useInView(ref, { once: true, amount: 0.7 });
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(value);
  useEffect(() => {
    if (!visible) return;
    const match = value.match(/^([^\d]*)(\d+(?:\.\d+)?)(.*)$/);
    if (!match || value.includes("–") || value.includes("-") || reduce) return;
    const [, prefix, raw, suffix] = match;
    const target = Number(raw);
    const controls = animate(0, target, { duration: 0.9, ease: [0.16, 1, 0.3, 1], onUpdate: (latest) => setDisplay(`${prefix}${Number.isInteger(target) ? Math.round(latest) : latest.toFixed(1)}${suffix}`), onComplete: () => setDisplay(value) });
    return () => controls.stop();
  }, [visible, value, reduce]);
  return <span ref={ref} className={className}>{display}</span>;
}

export function RevealOnScroll({ children, className = "", delay = 0 }: ChildrenProps) {
  return <FadeUp className={className} delay={delay}>{children}</FadeUp>;
}
