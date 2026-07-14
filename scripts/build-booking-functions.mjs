// Copies the canonical booking libs (scripts/lib/) into each Edge Function dir as
// self-contained, _-prefixed .ts files. The repo has no _shared/ — functions must
// be self-contained — so this mirrors the templates.ts generation pattern: one
// source of truth, copied per function. Import specifiers between libs are rewritten
// to the copied names. Run after editing scripts/lib/*, then redeploy the functions.
//   node scripts/build-booking-functions.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const LIB = path.join(ROOT, 'scripts/lib');
const FN = path.join(ROOT, 'supabase/functions');

// canonical source file -> copied name inside each function directory
const MAP = {
  'booking-config.mjs': '_config.ts',
  'slots.mjs': '_slots.ts',
  'ics.mjs': '_ics.ts',
  'google-auth.ts': '_google.ts',
  'calendar.ts': '_calendar.ts',
};

const rewrite = (src) =>
  src
    .replace(/(['"])\.\/booking-config\.mjs\1/g, "'./_config.ts'")
    .replace(/(['"])\.\/slots\.mjs\1/g, "'./_slots.ts'")
    .replace(/(['"])\.\/ics\.mjs\1/g, "'./_ics.ts'")
    .replace(/(['"])\.\/google-auth\.ts\1/g, "'./_google.ts'")
    .replace(/(['"])\.\/calendar\.ts\1/g, "'./_calendar.ts'");

const HEADER = '// AUTO-GENERATED from scripts/lib — DO NOT EDIT. Regenerate: node scripts/build-booking-functions.mjs\n';
const TARGETS = ['availability', 'book', 'booking-manage', 'booking-reminders'];

let copied = 0;
for (const fn of TARGETS) {
  const dir = path.join(FN, fn);
  if (!fs.existsSync(dir)) continue; // only populate functions that exist yet
  for (const [src, dest] of Object.entries(MAP)) {
    fs.writeFileSync(path.join(dir, dest), HEADER + rewrite(fs.readFileSync(path.join(LIB, src), 'utf8')));
    copied++;
  }
  console.log('libs ->', fn);
}
console.log(`Done (${copied} files).`);
