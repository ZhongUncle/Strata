// Offline test of the Monitor's `expertsCached` helper in serve/web/app.js: the slots actually holding an
// expert, with the arena's capacity when they differ - an underfilled cache used to show its capacity here.
// The functions are lifted out of app.js verbatim (the file wires up the DOM at load, so importing it
// whole would need a browser).  Run: node tools/test_experts_cached.mjs
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {dirname, join} from "node:path";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../serve/web/app.js"), "utf8");

const lift = (startMark, endMark) => {
  const start = src.indexOf(startMark);
  if (start < 0) throw new Error(`app.js no longer contains: ${startMark}`);
  const end = src.indexOf(endMark, start);
  if (end < 0) throw new Error(`app.js: ${startMark} is not closed by ${endMark}`);
  return src.slice(start, end + endMark.length);
};

// `fmt` is one line; `expertsCached` ends at its closing "};"
const {fmt, expertsCached} = new Function(`
  ${lift("const fmt = ", "\n")}
  ${lift("const expertsCached = ", "\n};")}
  return {fmt, expertsCached};
`)();

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed = 1;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}: ${JSON.stringify(got)}${ok ? "" : ` (want ${JSON.stringify(want)})`}`);
};

// an older engine sends only the capacity: the display is exactly what it always was
check("old engine (capacity only)", expertsCached({expert_slots: 1280}), fmt(1280));
// a full cache: resident == capacity, so the plain number stays (no redundant "N of N")
check("full cache", expertsCached({expert_slots: 64, expert_slots_resident: 64}), fmt(64));
// an underfilled cache: the resident count leads, the capacity follows
check("underfilled cache", expertsCached({expert_slots: 1280, expert_slots_resident: 37}), `${fmt(37)} of ${fmt(1280)}`);
// freshly started, nothing admitted yet: "0 of N", not the old inflated N
check("empty cache", expertsCached({expert_slots: 1280, expert_slots_resident: 0}), `${fmt(0)} of ${fmt(1280)}`);

process.exit(failed);
