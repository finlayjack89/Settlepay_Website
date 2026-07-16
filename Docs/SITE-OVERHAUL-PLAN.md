# SettlePay Site Overhaul Plan — July 2026

Produced from a 17-agent audit + research workflow (8 page/dimension audits with 162 evidence
screenshots, 4 external research sweeps, synthesis, adversarial critique, 3 verification gap-fills)
plus a 4-agent inspiration-collection pass. Evidence lives OUTSIDE the repo (to survive worktree
cleanup without bloating git) at `/Users/finlaysalisbury/Documents/SettlePay/inspiration/`:
`_current-state/` (baseline screenshots of every page) and one folder per research topic
(external reference captures + INDEX.md mapping each image to the plan item it supports).

**The one-line verdict:** the landing page is rich but has weak final beats and two illegible
canvases; the interior pages don't feel like the same product; the conversion surfaces (booking,
modal, preview tool) are the flattest and most defect-ridden pages on the site; and the single
biggest asset — Lockdales, the real client — is the thinnest page on the site. Fix the broken,
propagate the motion language, spend the real client, and only then add new spectacle.

---

## Phase 0 — Sequencing (before any new work)

Verified by gap-fill agents against git/gh and live probes:

1. **Merge PR #17** (this redesign branch — gh reports MERGEABLE against main).
2. **Then merge PR #24** (`feat/booking-calendar-ui`) — verified: auto-merges over #17 with zero
   conflicts (merge-tree `1286356`), merged tree builds all 20 pages, merged /book/ renders a
   coherent two-pane calendar. **PR #24 supersedes this plan's original booking-rebuild items** —
   adopt it as the booking vehicle; remaining booking work becomes polish on top of it.
3. **Close PR #22** as superseded (its nav-frost fix is in #17 verbatim — comment with evidence).
4. Every subsequent fix lands on **fresh post-merge main**, one worktree per task
   (`../worktrees/<scope>`). Nothing more lands in the root clone.
5. **Enquiry pipeline: FULLY verified end-to-end** (2026-07-16): Supabase endpoint returns 200,
   lead row inserted, branded autoreply delivered, and Finlay confirmed the internal notification
   reached hello@settlepay.uk. No blockers remain on the enquiry path.
6. **Record the performance baseline now** (Lighthouse throttled-mobile on /, /work/, /book/,
   /faq/: LCP, CLS, JS bytes, media bytes) — every phase re-runs it as a regression gate.
7. **Send Lockdales ONE consolidated permission request** covering all four uses: outbound link to
   the live page, an attributed quote, a 6–8s screen capture of the live page, and case-study
   material. Pre-agreed fallback if declined: mechanics-only case page, "Live since [month year]"
   from SettlePay's own records, CSS reconstruction stays primary.
8. **Decide /book/ noindex** (book.astro:34 sets it with no comment). If unintentional, remove; if
   intentional, document why inline.

## Phase 1 — Fix the broken before adding the beautiful (~1 week)

| # | Item | Effort |
|---|---|---|
| 1.1 | **Purge competitor recordings from public/**: 568MB of Stripe/Adyen .mov in the ROOT clone's `public/landing_page_inspiration/` is one build away from being deployed to settlepay.uk. Move outside the repo, gitignore the path. Plus asset hygiene: delete orphaned 4320px logo PNGs, 512px JSON-LD logo, recompress lockdales-coin.png, add dark-context monogram SVG. | XS |
| 1.2 | **Credibility copy sweep**: fix Astro whitespace-collapse typos ("Stripe,Adyen" hero trust line, "London,United Kingdom" footer, "Pleasesend"/"emailhello@" booking errors — then grep all .astro for expression-comma-newline); fix the wrong build count ("Six builds… five fictional" → seven/six) in work/index.astro + seo.json + OurWork.astro; standard blue link treatment on error-card links; Title Case FAQ headings. **Extend the sweep to `supabase/functions/*/templates.ts`** (transactional emails carry the same brand rails) and render-test confirmation/reschedule/cancellation emails in Gmail, Outlook, Apple Mail dark mode, verifying the manage link. | XS–S |
| 1.3 | **Contrast token pass on trust-bearing text**: the WCAG failures are precisely the evidence — UK Finance/SBC attributions (4.00:1, 3.41:1), "Live with Lockdales" badge (3.96:1), footer (3.81:1). Replace opacity-dimming with solid tokens ≥4.5:1; dimmed dark-chapter steps floor ≥3:1. | S |
| 1.4 | **Curate booking availability at the source** — real windows provided 2026-07-16 (all Europe/London): Mon/Thu/Fri/Sat/Sun 09:00–20:00, Tue/Wed 16:30–21:00 evenings only; 30-min slots, 15-min buffer around existing calendar events, 12h minimum notice, 14-day horizon, `blackoutDates: []`. Set in the availability function config + redeploy booking functions. | S |
| 1.5 | **A11y quick-wins patch**: reduced-motion override for smooth scroll; gate modal spRise; Escape-to-close + focus return on mobile drawer; OurWork tab-order; demote mockup h3s; focus + aria-live on booking success; 24px footer hit targets. | S |
| 1.6 | **First-party cookieless analytics before Phase 2** (critic-mandated): one Supabase beacon endpoint (`navigator.sendBeacon`), pageviews + funnel events (enquiry_open with source attribution, booking steps, preview generate/share/download), day-salted anonymous hash, no cookies → no consent banner; funnel view in the existing ops console; truthful same-PR rewrite of cookies.md/privacy.md. Server-side bottom-of-funnel tables already exist (leads, bookings, brand_preview_requests/shares) — instrument only the missing edges. | M |
| 1.7 | **Edge-function guardrails before driving traffic**: error-rate alerting (email/webhook) on availability/book/enquiry/brand-preview; register brand-preview's per-generation Claude+Brandfetch cost in a tracked budget with a daily cap alarm; 24h unactioned-leads digest via pg_cron; lock CORS to https://settlepay.uk at go-live; codify the safe smoke-probe trio (OPTIONS 200 / honeypot silent-ok / invalid 400) as the post-deploy check. | S–M |

## Phase 2 — Conversion surfaces that close (~2 weeks)

| # | Item | Effort |
|---|---|---|
| 2.1 | **Booking polish on top of PR #24's calendar**: selected-chip physics (hover tint, press scale, 180ms settle), skeleton loader instead of spinner, "First available: … — Book it" quick-pick, branded inline confirm cards on /manage/ (kill native confirm()/alert()), /manage/ page furniture. | S–M |
| 2.2 | **Commitment summary card** on /book/ details step: calendar glyph, bold slot, "30 minutes · Google Meet · with Finlay, SettlePay's founder", "Free — no obligation", and under the submit: "No payment details needed. Reschedule or cancel any time from your confirmation email." + the same privacy consent line the modal has. | S |
| 2.3 | **Pin the modal's booking fork**: move "or — Pick a Time Now" + privacy line into a non-scrolling modal footer (it currently hides below an unindicated scroll fold at BOTH 1440 and 390). Add a zone-local reassurance row at the submit button (no card details / reply time / FCA-regulated partners process payments). | S |
| 2.4 | **Landing → preview tool front door**: quiet hero tertiary text link ("Or paste your website address and see your own page first →") + slim navy teaser band after Our Work with a single-field GET form to /preview/ (PreviewStudio already auto-generates from ?url= — zero new backend, works no-JS). *Gate: preview go-live prerequisites (keys, deploy, migration) + 1.7 cost alarm first.* | S |
| 2.5 | **Preview-aware enquiry prefill**: carry the generated slug + "I generated a preview for X" into the modal (endpoint verified live; server must accept the extra field — it currently drops unknown FormData fields). Single post-generation CTA (hide the static mini-cta when .is-generated); relocate Copy Link/Download beside device toggles; /p/ recipient loop link; noscript fix. | S |
| 2.6 | **Propagate data-reveal/data-tilt to interior pages** — markup-only; the JS already binds globally (work index pf-cards are the same markup that tilts on the landing page). | S |
| 2.7 | **Sticky CTA on interior mobile pages** (work/about/faq; keep off book/manage/legal/preview). A reader mid-case-study on a phone currently has NO visible CTA anywhere. | S |
| 2.8 | **FAQ conversion pass**: slugified ids + :target auto-open + copy-link (deep-linkable objection answers for outreach emails); "Top Objections" strip (hold my money? / FCA? / cost?); CSS-only accordion animation (interpolate-size, @supports-gated); inline enquiry link in the cost answer. Sync FAQPage JSON-LD with the new ids. | M |
| 2.9 | **Sourced-claim footnote counters** (Mercury pattern, zero JS): CSS-counter superscripts linking every sourced figure to one Sources block above the footer; methodology strapline under MarketShift stats. | XS |

## Phase 3 — Proof assets and surfaces (~2–3 weeks, permission-dependent)

| # | Item | Effort |
|---|---|---|
| 3.1 | **Link to the live Lockdales page** (verifiable > asserted trust). Production URL confirmed 2026-07-16: `https://lockdalespayments.netlify.app/` (SettlePay-built). Resolve the copy contradiction by showing/linking the real URL and softening the "on the Lockdales domain" claim. Quote + capture still need Lockdales' sign-off. | XS |
| 3.2 | **Real Lockdales quote** — pull-quote on the case page beside the reconstruction + reused as the missing free-scrolling beat on the landing page between Our Work and the dark chapter. Fallback: "Live since [month year]". *Needs: permission.* | S |
| 3.3 | **Real Lockdales capture loop**: 6–8s WebM (≤600KB, VP9, muted/loop/IO-gated, poster for no-JS/reduced-motion) of the live page being used, gradient-mask feathered into the page. *Needs: permission.* | S |
| 3.4 | **Rebuild Lockdales as the flagship case page**: dedicated layout, full-bleed navy/gold hero stage, checkout reconstruction with scroll-revealed annotated callouts, "How the page actually works" walkthrough (mechanics are facts — legally safe), countable before/after (steps/redirects/fields removed), bento for the capability tiles. | L |
| 3.5 | **Work index upgrade**: per-brand CSS mini-checkout thumbnails (data already in portfolio.mjs — kills the seven-identical-grey-skeletons problem), Lockdales 2-col hero card with live pulse, "Interactive demo — test mode" chips. | M |
| 3.6 | **Founder photo ×2**: About split header (founder-first lead + bordered photo card + two quiet fact rows) and small circular version in the /book/ aside ("Your call is with Finlay — not a sales team"). *Needs: one real photo. No stock, no AI.* | M |
| 3.7 | **About restructure**: wire the built-but-unused .about-grid cards into "How We're Different" (2×2), "What We Do" as a three-step flow strip, add missing lead paragraph. | M |
| 3.8 | **Preview reveal moment**: ticking progress checklist in the skeleton (honest stage timings already exist), ~600ms clip-path unveil + "Designed from X's public branding" stamp, extracted-ingredients strip (their logo, colour chips, font name) as evidence of "we read your actual site". | M |
| 3.9 | **WorkflowTheatre attract state**: promoted "pick a customer" instruction, one-shot IO attract sweep, step-only controls under reduced motion. | S |

## Phase 4 — Landing completion and coherence (~2 weeks)

| # | Item | Effort |
|---|---|---|
| 4.1 | **Hero checkout idle demo loop**: after ~4s in view untouched — security code types in, button presses → spinner → green "Payment received", chips sequenced off the same timeline so the story reads in order; first pointer interaction kills it permanently. Grid-rows accordion animation; PayPal mark in the empty icon row. | M |
| 4.2 | **Canvas legibility + seam pass**: ~2× UKMap dot/arc contrast + card-hover → city-dot/arc sync; FlowScene arc brightness + arrival ticks ("+£" at Your Bank, "Invoice marked paid" at Xero) so the never-holds-funds story lands visually; MarketShift navy→white dawn crossfade over the first ~30% of the scrub + centred stage + ghost fact-card skeletons (kills the >60%-empty pinned viewport) + mobile counter starts from the 2014 figure. | M |
| 4.3 | **Cross-document View Transitions** (CSS-only `@view-transition`, ~200ms fade, nav pill persists via view-transition-name; NO ClientRouter — it breaks island lifecycles). Firefox degrades to normal navigation. | S |
| 4.4 | **Footer overhaul**: three link columns in the dead middle, dark-context monogram, one-shot line-draw ending in a green tick + "Invoice settled" as the page's narrative full stop, optional low-opacity ParticleField reuse to bookend the hero. | S |
| 4.5 | **Legal page wayfinding**: sticky left TOC rail ≥1200px + IO scrollspy, :target section highlight, back-to-top pill. | M |
| 4.6 | **Per-page OG cards** (7 static 1200×630 in the navy-stage language, Playwright-generated, regenerable in one command) + `/p/` share-link unfurls via edge middleware injecting og:title + cached render screenshot. | M |
| 4.7 | **Fix the frosted nav pill over dark sections** (renders as an opaque grey slab on .section--dark/.cta-section, worst on mobile) — likely a dark-variant of the frost recipe keyed off a section observer. | S |
| 4.8 | **PayCard holo hue trim** — the monogram reads pink/red against navy at rest; bias the iridescent gradient toward the blue/cyan end at default pointer position. | XS |

## Explicitly rejected (with reasons — do not resurrect casually)

Lenis/GSAP stack (bundle + momentum-scroll motion-sickness vs already-met needs) · scroll-companion
persistent card (spectacle) · Astro ClientRouter (breaks WebGL/IO island lifecycle) ·
scroll-scrubbed video / frame sequences (multi-MB + mid-range stutter) · perpetual marquee columns
(the exact AI-slop aesthetic the brand rejects) · Trustpilot widget now (1–2 reviews reads worse
than nothing) · stepped conversational modal (chat-styled forms hurt 45–65 trust) · full inline
hero generation sandbox (per-preview API cost on the highest-traffic surface) · audience
self-selection tabs (advertises having one client) · fee-comparison/SEO calculator pages (stale
rates damage trust; edges toward financial advice) · third stage-dark use (recorded design
decision: exactly two) · FAQ search field (22 questions don't need it) · 404 canvas easter egg
(low-traffic novelty; keep only the four-link recovery row) · footer curtain peel (stacking-context
risk vs three existing sticky sections).

## Resources needed (the complete external-dependency list)

**From Finlay** (status 2026-07-16):
1. Lockdales permission for quote + screen capture + case material — STILL OPEN (live URL
   provided: lockdalespayments.netlify.app; link unblocked).
2. One real photo of Finlay (calm, professional; not stock/AI) — PROMISED, coming later.
3. ~~Real consulting hours~~ — PROVIDED (see 1.4).
4. ~~Confirm notification email~~ — CONFIRMED, pipeline fully verified.
5. ~~PR landing order~~ — APPROVED (merge #17 → #24, close #22). /book/ noindex intent — STILL OPEN.
6. Preview-tool go-live prerequisites when ready (API keys, deploy, migration) — gates 2.4/2.5.

**Technical (no purchases needed):**
- Official PayPal mark SVG (free brand asset) — 4.1.
- Vercel middleware + small cache store for /p/ OG unfurls — 4.6 (second half only).
- Analytics = first-party on existing Supabase stack — no new vendor, no consent banner.

**Nothing requires:** paid stock, illustration commissions, new JS dependencies, or any external
animation library.

## Guardrails (apply to every phase)

- Perf budget gate: Lighthouse throttled-mobile per route (LCP/CLS/JS/media bytes) vs the Phase 0
  baseline; regression blocks merge.
- Every new animation ships its no-JS and reduced-motion states (existing contract).
- Compliance rails on all new copy incl. transactional emails: sole trader, no FCA/PCI claims,
  only Lockdales real, no invented metrics (sourced footnotes), UK English, Title Case, no emoji,
  blue = primary action only.
- Post-deploy: smoke-probe trio on edge functions; sitemap resubmit + Search Console coverage
  check after each phase.
