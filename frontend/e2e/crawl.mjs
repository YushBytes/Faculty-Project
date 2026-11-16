// Exploratory crawl: sign in, open every route, record console errors, page errors and failed requests.
// Usage: WEB=http://localhost:3010 API=http://localhost:8010 EMAIL=... PASSWORD=... OUT=dir node e2e/crawl.mjs [mobile]
import { chromium } from "@playwright/test";
import fs from "node:fs";

const WEB = process.env.WEB, API = process.env.API, OUT = process.env.OUT ?? "crawl-out";
const mobile = process.argv.includes("mobile");
fs.mkdirSync(OUT, { recursive: true });

async function apiLogin() {
  const r = await fetch(`${API}/api/v1/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: process.env.EMAIL, password: process.env.PASSWORD }) });
  if (!r.ok) throw new Error(`api login ${r.status}`);
  return (await r.json()).access_token;
}
const token = await apiLogin();
const get = async (p) => { const r = await fetch(`${API}/api/v1${p}`, { headers: { authorization: `Bearer ${token}` } }); return r.ok ? r.json() : { __status: r.status }; };
const first = (page) => page?.items?.[0]?.id;
const ids = {
  department: first(await get("/departments?limit=1")),
  course: first(await get("/courses?limit=1")),
  section: first(await get("/sections?limit=1")),
  offering: first(await get("/offerings?limit=1")),
  student: first(await get("/students?limit=1")),
  faculty: first(await get("/users?role=FACULTY&limit=1")),
};
const iv = await get("/insights/interventions?limit=1&semester=YEAR");
ids.intervention = iv?.items?.[0]?.id; ids.interventionOffering = iv?.items?.[0]?.offering?.id ?? iv?.items?.[0]?.offering_id;
const ov = await get("/insights/overview?semester=YEAR");
ids.assessmentKey = ov?.trend?.[0]?.key ?? ov?.assessments?.[0]?.key;
console.log("ids", JSON.stringify(ids));

const routes = ["/", "/dashboard", "/departments", `/departments/${ids.department}`, "/courses", `/courses/${ids.course}`, "/sections", `/sections/${ids.section}`,
  "/faculty", `/faculty/${ids.faculty}`, "/team", "/classes", `/classes/${ids.offering}`, "/analytics", "/assessments",
  ids.assessmentKey ? `/assessments/${encodeURIComponent(ids.assessmentKey)}` : null, "/students", `/students/${ids.student}`, "/attention", "/interventions",
  ids.intervention ? `/interventions/${ids.intervention}?offering=${ids.interventionOffering}` : null, "/import", `/import?offering_id=${ids.offering}`, "/reports", "/admin/users", "/admin/structure", "/audit", "/settings",
  "/no-such-page", "/classes/00000000-0000-0000-0000-000000000000", "/students/not-a-uuid"].filter(Boolean);

const browser = await chromium.launch();
const context = await browser.newContext(mobile ? { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } : { viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
let current = "";
const findings = [];
page.on("console", (m) => { if (["error", "warning"].includes(m.type())) findings.push({ route: current, kind: `console.${m.type()}`, text: m.text().slice(0, 400) }); });
page.on("pageerror", (e) => findings.push({ route: current, kind: "pageerror", text: String(e).slice(0, 400) }));
page.on("response", (r) => { if (r.status() >= 400) findings.push({ route: current, kind: `http ${r.status()}`, text: `${r.request().method()} ${r.url().replace(WEB, "")}` }); });
page.on("requestfailed", (r) => findings.push({ route: current, kind: "requestfailed", text: `${r.method()} ${r.url().replace(WEB, "")} ${r.failure()?.errorText}` }));

current = "/login";
await page.goto(`${WEB}/login`);
await page.locator('input[type="email"], input[name="email"]').first().fill(process.env.EMAIL);
await page.locator('input[type="password"]').first().fill(process.env.PASSWORD);
await page.getByRole("radio", { name: process.env.ROLE_LABEL ?? "Administrator", exact: true }).check();
await page.getByRole("button", { name: /sign in/i }).click();
await page.waitForURL(/dashboard/, { timeout: 20000 });

const summary = [];
for (const route of routes) {
  current = route;
  const requests = [];
  const onReq = (r) => { if (r.url().includes("/api/")) requests.push(`${r.method()} ${r.url().replace(WEB, "")}`); };
  page.on("request", onReq);
  const t = Date.now();
  await page.goto(`${WEB}${route}`, { waitUntil: "networkidle", timeout: 45000 }).catch((e) => findings.push({ route, kind: "nav", text: String(e).slice(0, 200) }));
  await page.waitForTimeout(600);
  page.off("request", onReq);
  const name = (route.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "root").slice(0, 60);
  await page.screenshot({ path: `${OUT}/${mobile ? "m_" : ""}${name}.png`, fullPage: true });
  const h1 = await page.locator("h1").first().textContent({ timeout: 1500 }).catch(() => null);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  const dup = requests.filter((r, i) => requests.indexOf(r) !== i);
  const text = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  const bad = /\b(NaN|undefined|Infinity|\[object Object\])\b/.exec(text)?.[0] ?? null;
  summary.push({ route, url: page.url().replace(WEB, ""), ms: Date.now() - t, h1: h1?.trim().slice(0, 60), apiCalls: requests.length, duplicates: [...new Set(dup)], overflowX: overflow, badText: bad });
}
fs.writeFileSync(`${OUT}/${mobile ? "m_" : ""}summary.json`, JSON.stringify({ ids, summary, findings }, null, 1));
for (const s of summary) console.log(`${String(s.ms).padStart(5)}ms calls=${String(s.apiCalls).padStart(2)} dup=${s.duplicates.length} ovf=${s.overflowX} bad=${s.badText} ${s.route} -> ${s.url} [${s.h1}]`);
console.log("--- findings"); for (const f of findings) console.log(`${f.route} | ${f.kind} | ${f.text}`);
await browser.close();
