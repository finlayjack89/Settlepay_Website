---
name: settlepay-design
description: Use when building, editing or extending ANY SettlePay-branded UI, page, component, email, social asset, or visual — in this repo or as a throwaway mock. Loads SettlePay's brand rules, design tokens, component catalogue and the load-bearing legal/compliance constraints.
user-invocable: true
---

# SettlePay design skill

You are designing for **SettlePay** — bespoke, branded payment-page development & integration for
small UK businesses. Optimise for **calm competence and trust before persuasion** (audience: sceptical
45–65+ UK business owners).

## Always read the canonical docs first
- `docs/DESIGN-SYSTEM.md` — brand, voice, colour (60/30/10), light/dark rhythm, type (Satoshi),
  spacing, radii, shadows, frosted glass, motion doctrine + canvas-island contract (§9),
  iconography, logos, payment marks, imagery.
- `docs/COMPONENTS.md` — every component, its props, and when to use it.
- `src/data/site.mjs` — business facts, nav, footer, SEO defaults.
- Live tokens: `src/styles/styles.css` `:root`.

## Non-negotiable rules (legal + brand — never break)
- SettlePay is a **trading name of Finlay Salisbury, a sole trader**. No "Ltd", no company number, not
  "registered in England & Wales".
- Never claim SettlePay is "FCA authorised/regulated" or "PCI DSS compliant" — payments are processed
  by **FCA-regulated partners**; PCI is handled by the client's processor (hosted page → usually SAQ A).
- No FSCS badge, no "Powered by [processor]", no fake urgency, no invented metrics. SettlePay **never
  holds funds**. Only **Lockdales Auctioneers** is a real client; label anything else "Illustrative".
- UK English, Title Case headings, **no emoji**.

## Visual non-negotiables
- Colour **~60/30/10** (neutral / navy `#0F172A` / blue `#3B82F6`). **Blue is reserved for the single
  primary action** — never decorative. One primary + one secondary button per view.
- **Light/dark rhythm:** mostly light bands, punctuated by deliberate navy "dark chapters" (hero
  stage, product-evidence moments, the CTA band). At most ONE full-bleed `.section--dark` between
  hero and CTA band. A section earns navy only to stage product evidence or the final ask.
- Font **Satoshi**; body 16–18px, line-height 1.6–1.75, measure ~50–75ch.
- Radii: **buttons = pill 100px** (`--radius-button`), inputs = 8px (`--radius-input`), cards = 24px
  (`--radius-card`), icon tiles ~12px, soft cards 16px (`--radius-soft`).
- Shadows: soft, blue-tinted (`--shadow-sm/md/lg`), CTA glow only for the primary action.
- **Frosted glass is a system** (`--blur-glass-*`): nav pill 18px, sticky CTA bar 16px, status chips
  14px, modal veil 4px. Always `-webkit-backdrop-filter` first / standard last; never `overflow` on
  the nav's ancestors; never `view-transition-name` on the nav.
- **Motion is evidence, not decoration** — if it proves nothing about the product, cut it. Physics
  over easing tricks (world-fixed light, momentum springs, odometer rolls); enhancement never
  dependency — the static/no-JS/reduced-motion state is a finished render. Three curves
  (`--curve-snappy/cinematic/spring` × `--duration-*`; `--ease-*` shorthands) — never paste a
  `cubic-bezier()` literal. Canvas islands follow the DESIGN-SYSTEM §9 contract: `data-gl-state`,
  IO-gated rAF, DPR ≤ 2, reduced-motion = one still frame, context-lost → permanent DOM fallback.
  Still banned: carousels, scroll-hijacking, fake urgency, meaningless motion.
- Icons: **Heroicons v2 outline** via `Icon.astro` only. Never inline ad-hoc SVGs or use emoji.

## How to build
Reuse components (`Button`, `Icon`, `SectionHeader`, sections/, layouts) — don't hand-roll. To add a
page or section, follow `docs/COMPONENTS.md` → "Adding a new page" / "new section". Use design tokens,
never hardcoded colours/radii/spacing. Run `npm run build` to verify; check `npm run dev` for behaviour.

Before finishing, run the compliance checklist in `docs/DESIGN-SYSTEM.md` §16.
