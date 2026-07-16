# Asset & Motion Plan — SettlePay marketing site

The governing rule, learned from the Stripe/Adyen study: **every asset must demonstrate the
product or the market — decoration doesn't earn a slot.** Second rule (DESIGN-SYSTEM §11):
authentic over stock, and nothing AI-obvious. Third: every moving asset has a still,
legible reduced-motion state.

## Media policy by type

| Medium | Use for | Rules |
|---|---|---|
| CSS/SVG mockups | Product UI (checkout, dashboard, templates) | The default. Crisp, tiny, themeable. |
| WebGL canvas islands | Ambient/market life (particles, flow, UK map) | Raw WebGL, no deps; IO-gated RAF; `data-gl-state` contract (live/static/unsupported); DPR ≤ 2. |
| WebM/MP4 loops | Real product *interactions* that CSS can't fake | Muted, `loop playsinline`, poster, ≤ 600 KB, lazy, IO-paused, reduced-motion → poster. Only where a real flow is shown. |
| Photography | People and premises only | Real photos only (no stock, no generated people). One asset planned: Finlay, for About. |
| HyperFrames | Social/OG video snippets | Off-page (marketing clips), not the landing page. |

## Section-by-section

| Section | Asset now | Planned addition | Effort |
|---|---|---|---|
| Hero | Compact checkout on navy stage + ParticleField (GL) + glass chips + layers | — (done) | — |
| Trust strip | Text + live-client pill | Lockdales coin mark (`assets/logos/lockdales-coin.png`) beside the pill | XS |
| Bento (Why SettlePay) | Differentiated mockup crops, live loops (chart draw, tick pops, node pulse) | **WebM loops of real flows** recorded from our own demo pages via Playwright (reconcile matching, onboarding advancing) — swap in per tile | M |
| Dark chapter | Live dashboard (sticky, split-scroll) + FlowScene (GL) + step spotlight + text fill | — (done) | — |
| Our Work | Sticky rail + UKMap (GL: Natural-Earth-derived dot silhouette, drawn payment arcs, local-payment blinks, hover ripple) + stacked brand cards with tilt | **Real Lockdales page loop**: 6–8 s scroll capture of the live client page in a browser frame — the single most persuasive asset we can ship. *Needs client permission first.* | S (after permission) |
| Market shift | Scroll-scrubbed counter settling on the true UK Finance figure + sourced stat cards (cash decline, hours chasing invoices) | Re-verify figures when UK Finance publishes 2025 data (annual refresh) | XS (yearly) |
| Calculator | Live sliders/results | Nothing — the calculator is the asset | — |
| CTA band | PayCard: brand-art ribbon, gold contact-pad chip with its own glint, directional face gloss, holographic SettlePay monogram | — (done) | — |
| About | Prose | **One real photo of Finlay** — calm, cool-neutral, professional. Sole-trader trust hinges on a face. | S (needs the photo) |
| OG/social | Single static og-default | Per-page OG cards in the new visual language (navy stage + chips) — static PNGs | S |

## Interactive backlog (nice-to-haves, in taste order)

1. **Line-burst hover** (Stripe's radiating lines) — candidate for the 404 page or FAQ header;
   an easter egg, not a core section.
2. **Magnetic primary buttons** — 2–3 px pointer attraction, desktop only. Test against the
   45–65 audience before keeping.
3. **Calculator spring-count** — results animate through intermediate values on slider release.
4. **UKMap city tooltips** — hovering a city dot names the sector ("Auctioneers — live").

## Explicitly rejected

- Stock photography of any kind (handshakes, headsets, skylines).
- AI-generated people, premises, or "abstract fintech" art.
- Autoplaying video with sound; background video heroes.
- A WebGL-first page. Canvas stays in islands; the page stays HTML.
