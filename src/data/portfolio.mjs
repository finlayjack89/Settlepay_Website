/**
 * SettlePay portfolio — the single source of truth for /work/ and the
 * landing-page Our Work section.
 *
 * CONTRACT (do not rename): the six slugs, the order, and the demoComponent
 * names map 1:1 to files in src/components/portfolio/demos/ and to the static
 * import map in src/pages/work/[slug].astro. Brand agents replace the demo
 * components but must keep these names exactly.
 *
 * IMPORTANT (legal): only Lockdales Auctioneers is a real client (live: true).
 * Every other entry is a fictional brand and must always be presented as an
 * illustrative demo with no real payments taken. SettlePay never holds funds;
 * payments are processed by FCA-regulated partners.
 *
 * Mock entries carry a `caseStudy` object (the real client never does — no
 * invented figures or fabricated infrastructure may be attached to Lockdales):
 * - profile      at-a-glance facts: [{ label, value }]
 * - background   the situation paragraph
 * - painPoints   quantified pain bullets; may contain <strong> (set:html)
 * - setup        { had, access, untouched, note } — the honest map of their
 *                existing IT and what a third party could realistically touch.
 *                This is expectation management: never promise integration
 *                with closed systems.
 * - delivered    scope-of-work list
 * - flow         automation workflow steps: [{ title, detail }]
 * - ops          data for the OpsPanel back-office mockup (fictional rows)
 * - outcome      { stats: [{ value, label, sub }], basis: [sources/assumptions] }
 *                Figures are MODELLED on published UK industry data — the
 *                StatTiles component always renders the disclaimer with them.
 */
export const PORTFOLIO = [
  {
    slug: 'lockdales-auctioneers',
    name: 'Lockdales Auctioneers',
    live: true,
    vertical: 'Fine Art & Antiquities',
    pattern: 'Branded "Pay Your Invoice" page',
    tagline:
      'A bespoke, branded payment page for a long-established Suffolk coin and medal auction house — giving buyers a secure card option alongside bank transfer, on a page that looks like Lockdales.',
    summary:
      'Buyers once paid by bank transfer or read card details down the phone. Now they settle their invoice on a secure, Lockdales-branded page — by BACS or card — entering their bidder number as the reference.',
    story: {
      challenge:
        'A long-established Suffolk coin, medal and collectables auction house taking buyer payments by bank transfer or by card details read out over the phone after each sale — no branded, secure way for a buyer to simply pay their invoice online.',
      solution:
        'A bespoke, Lockdales-branded "Pay Your Invoice" page processed by Stripe on the Lockdales account: buyers choose BACS (with the account details shown) or pay securely by card, entering their name and bidder number as the reference so Lockdales can match the payment to their invoice. Funds settle straight to the Lockdales bank account.',
      impact: [
        'A branded, secure payment page live on the Lockdales domain',
        'Buyers can pay by card instead of reading details down the phone',
        'Funds settle straight to the Lockdales bank account',
      ],
    },
    capabilities: [
      {
        icon: 'card',
        title: 'Branded Card Checkout',
        text: 'A payment page in Lockdales colours on the Lockdales domain — not a generic processor screen buyers have never seen.',
      },
      {
        icon: 'scale',
        title: 'BACS or Card, One Page',
        text: 'Bank transfer details and a secure card option side by side, so every buyer can pay the way that suits them.',
      },
      {
        icon: 'phone',
        title: 'No More Phone Payments',
        text: 'Buyers pay on a secure page instead of reading long card numbers down the line to staff.',
      },
      {
        icon: 'shield',
        title: 'FCA-Regulated Processing',
        text: 'Card payments run through Stripe, an FCA-regulated processor, on the Lockdales account — SettlePay never holds the funds.',
      },
      {
        icon: 'lock',
        title: 'Direct Settlement',
        text: 'Money moves from the processor straight to the Lockdales bank account, exactly as it did with bank transfers.',
      },
    ],
    /* Navy/gold/cream to match the real Lockdales payment page. Gold accent is
       never SettlePay's reserved action blue (#3B82F6). */
    brand: { bg: '#1B3A5B', surface: '#F7F3EA', accent: '#C2A24E', ink: '#15304C' },
    methods: ['Bank Transfer', 'Visa', 'Mastercard'],
    demoComponent: 'LockdalesCheckout',
  },

  {
    slug: 'harbourside-lettings',
    name: 'Harbourside Lettings',
    live: false,
    vertical: 'Estate & Lettings',
    pattern: 'Holding deposit by pay-by-link',
    tagline:
      'A fictional coastal lettings agency, showing how holding deposits move from "transfer it and email us the receipt" to a branded link paid in minutes — without touching the agency’s CRM.',
    summary:
      'Holding deposits paid by branded link the moment an applicant is approved — matched to the tenancy automatically, with a live deposit log replacing the Excel sheet.',
    brand: { bg: '#134E4A', surface: '#F2F7F5', accent: '#0F766E', ink: '#113B36' },
    methods: ['Visa', 'Mastercard', 'Apple Pay', 'Google Pay'],
    demoComponent: 'HarboursideCheckout',
    caseStudy: {
      profile: [
        { label: 'Team', value: '3 staff' },
        { label: 'Portfolio', value: '~90 managed tenancies' },
        { label: 'New lets', value: '~40 a year' },
        { label: 'Paid by, before', value: 'Bank transfer, occasional cheque' },
      ],
      background:
        'Harbourside Lettings is a fictional three-person coastal agency of a very real shape: a high-street office, around ninety managed tenancies, and a steady stream of applicants. When an applicant was approved, a staff member emailed over the client-account details, the applicant transferred the holding deposit "when they got home", and the office checked the bank statement the next morning — and the morning after that. Until the money landed, the property was held on a promise.',
      hook:
        'An applicant says yes — and the property is held on a promise while the office refreshes the bank statement, waiting for a holding deposit to “land when they get home”.',
      painPoints: [
        'Each deposit collected by transfer meant <strong>25–35 minutes</strong> of emails, statement checks and manual matching, spread across two or three working days',
        'Transfers arrived labelled <strong>"FLAT DEPOSIT"</strong> or a misspelt surname, then someone matched them to the right tenancy by hand in the Excel log',
        'The holding deposit starts a <strong>statutory 15-day</strong> deadline for agreement under the Tenant Fees Act — days lost waiting for a transfer came straight out of that window',
        'While the deposit was "on its way", the property sat informally reserved — applicants could simply go quiet and the listing went stale',
      ],
      setup: {
        had: [
          'A cloud lettings CRM on a small-agency plan — with no API access at that tier',
          'Rightmove and Zoopla listings',
          'A client account at the bank',
          'A shared office inbox and an Excel deposit log',
        ],
        access: [
          'Tenancy references — exported from the CRM as a list, or typed into a one-field link generator',
          'The office inbox, for receipts and a daily summary',
          'The agency’s own processor account — their name on the statement, settlement to their client account',
        ],
        untouched: [
          'The CRM and its database — no API on their plan, so nothing was wired into it and nothing pretended to be',
          'The client account and its banking — money arrives exactly as it did before',
          'Applicant personal data — SettlePay’s layer holds the payment reference, not the file',
        ],
        note: 'This is the honest IT shape of most small agencies: a closed CRM, an inbox and a spreadsheet. So the build works alongside the CRM rather than inside it — staff turn a tenancy reference into a branded payment link in seconds, and the matching that used to happen by hand travels inside the payment itself. No integration was promised that the CRM could not deliver.',
      },
      delivered: [
        'A branded pay-by-link deposit page (the demo below)',
        'A one-field link generator: paste the tenancy reference, get the link',
        'Automatic receipts to the applicant and the office',
        'A live deposit log that replaced the Excel sheet — exportable as CSV any time',
        'A plain-English validity date on every request — no countdowns, no pressure',
        'A daily summary email listing anything still unpaid',
      ],
      flow: [
        { title: 'Applicant Approved', detail: 'Staff paste the tenancy reference into the link generator.' },
        { title: 'Link Sent', detail: 'The applicant sees the property, their name, the amount and a plain validity date.' },
        { title: 'Paid in Minutes', detail: 'Card, Apple Pay or Google Pay — often before the congratulations call ends.' },
        { title: 'Matched Automatically', detail: 'The payment carries its reference; the deposit log updates itself.' },
        { title: 'Office Notified', detail: 'Receipts go out and the daily summary flags anything still outstanding.' },
      ],
      ops: {
        url: 'app.settlepay.uk/harbourside',
        title: 'Deposit Requests',
        subtitle: 'Harbourside Lettings · week of 8 June',
        sync: 'Live log · CSV export',
        rows: [
          { ref: 'HQ-2218', who: 'Eleanor Hartley', amount: '£450.00', status: 'paid', label: 'Paid', sub: 'Paid 14:22 · matched to tenancy · receipt sent' },
          { ref: 'HQ-2217', who: 'Daniel Okafor', amount: '£495.00', status: 'paid', label: 'Paid', sub: 'Paid the same afternoon · Apple Pay' },
          { ref: 'HQ-2219', who: 'Sophie Mercer', amount: '£415.00', status: 'due', label: 'Awaiting', sub: 'Link sent 11:05 · valid until Fri 19 June' },
          { ref: 'HQ-2214', who: 'James & Anna Whitfield', amount: '£520.00', status: 'reminder', label: 'Nudged', sub: 'Polite reminder sent this morning' },
        ],
        feed: 'This week: six of eight deposit requests paid on the day they were sent.',
      },
      outcome: {
        stats: [
          {
            value: 'Days → minutes',
            label: 'Time to secure a deposit',
            sub: 'Paid by link during the approval phone call, instead of after a weekend of statement-checking.',
          },
          {
            value: '≈ 17 hrs a year',
            label: 'Deposit admin recovered',
            sub: 'Around 25 minutes of emails, statement checks and manual matching removed per let, across roughly 40 lets a year.',
          },
          {
            value: '15-day window',
            label: 'Statutory clock protected',
            sub: 'The Tenant Fees Act deadline for agreement runs from receipt of the deposit — faster receipt leaves more of the window to actually use.',
          },
        ],
        basis: [
          'Roughly 40 new tenancies a year, with 25–35 minutes of combined staff time per transfer-collected deposit — our stated assumption, as no published per-deposit figure exists.',
          'Holding deposits are capped at one week’s rent, with a default 15-day deadline for agreement — Tenant Fees Act 2019, GOV.UK statutory guidance.',
          'Staff time costed at typical UK administrator pay of £12–£14 an hour (Indeed and Reed salary data, 2025).',
        ],
      },
      roi: {
        period: 'year',
        volumeLabel: 'New tenancies you let',
        minutesLabel: 'Minutes of deposit admin per let today',
        rateLabel: 'Your admin hourly rate',
        volume: { default: 40, min: 10, max: 150, step: 5 },
        minutes: { default: 30, min: 10, max: 60, step: 5 },
        rate: { default: 13, min: 11, max: 25, step: 1 },
        lens: 'And the deposit is secured during the approval call — not after a weekend of checking the bank statement, with the statutory 15-day clock already ticking.',
      },
      workflow: {
        intro: 'Pick an applicant to follow their holding deposit — or open The Board to see the week’s deposits at a glance.',
        brand: { mark: 'HL', nameLines: ['Harbourside', 'Lettings'] },
        panes: [
          { key: 'phone', label: 'Applicant’s Phone', tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Harbourside', sync: 'Live log' },
        ],
        board: {
          title: 'Deposit requests · this week',
          sync: 'Live log · CSV',
          caption: 'Every holding deposit and its status in one live log — matched to its tenancy automatically. The Excel sheet is gone.',
          feed: 'This week: six of eight deposit requests paid on the day they were sent.',
          rows: [
            { ref: 'HQ-2218', who: 'Eleanor Hartley — Flat 2, Anchor Quay', amount: '£450.00', status: 'paid', label: 'Matched' },
            { ref: 'HQ-2217', who: 'Daniel Okafor — 14 Mariners Row', amount: '£495.00', status: 'paid', label: 'Paid' },
            { ref: 'HQ-2220', who: 'J & A Whitfield — 6 Cliff Court', amount: '£520.00', status: 'paid', label: 'Paid' },
            { ref: 'HQ-2219', who: 'Sophie Mercer — Flat 1, Pier View', amount: '£415.00', status: 'reminder', label: 'Day 2' },
            { ref: 'HQ-2212', who: 'T. Bremner — 9 Harbour Walk', amount: '£430.00', status: 'overdue', label: 'Expired' },
          ],
        },
        scenarios: [
          {
            id: 'hartley', tab: 'Paid in the call', customer: 'Eleanor Hartley', blurb: 'Apple Pay during approval',
            steps: [
              {
                caption: 'Approved for Flat 2, 18 Anchor Quay. A staff member pastes the tenancy reference into the link generator — that’s the whole job.',
                phone: { title: 'Eleanor Hartley’s Phone', idle: { clock: '11:04', hint: 'No new messages' } },
                ops: { sync: true, rows: [{ ref: 'HQ-2218', sub: 'Generating branded deposit link…', badge: { label: 'Ready', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'The link arrives by text — the property, her name, £450 and a plain validity date. No bank details to copy out.',
                phone: { title: 'Eleanor Hartley’s Phone', items: [{ type: 'sms', text: 'Harbourside Lettings: congratulations! Your holding deposit for Flat 2, 18 Anchor Quay (£450.00) secures the property — pay securely at pay.harbourside-lettings.co.uk/d/2218', time: '11:05' }] },
                ops: { rows: [{ ref: 'HQ-2218', sub: 'Link sent 11:05 · awaiting payment', badge: { label: 'Awaiting', tone: 'due' }, active: true }] },
              },
              {
                caption: 'She opens the link: the property, itemised, on a page in Harbourside’s name — and taps Apple Pay before the call has even ended.',
                phone: { title: 'Eleanor Hartley’s Phone', items: [{ type: 'invoice', label: 'Holding deposit · Flat 2, 18 Anchor Quay', amount: '£450.00', note: 'Valid until Fri 19 June', cta: 'applepay' }] },
                ops: { rows: [{ ref: 'HQ-2218', sub: 'Link opened · awaiting payment', badge: { label: 'Awaiting', tone: 'due' }, active: true }] },
              },
              {
                caption: 'Paid in minutes. The reference travels with the payment, so it matches the right tenancy on its own and settles to the client account — no statement to check.',
                phone: { title: 'Eleanor Hartley’s Phone', items: [{ type: 'invoice', label: 'Holding deposit · Flat 2, 18 Anchor Quay', amount: '£450.00', paid: { amount: '£450.00', time: '11:09 · Apple Pay' } }] },
                ops: { sync: true, rows: [{ ref: 'HQ-2218', sub: 'Matched to tenancy · settled to client account', badge: { label: 'Matched', tone: 'matched' } }], feed: 'No surname to match by hand — the reference did the work.' },
              },
            ],
          },
          {
            id: 'mercer', tab: 'Needed a nudge', customer: 'Sophie Mercer', blurb: 'Pays after an automatic reminder',
            steps: [
              {
                caption: 'Sophie’s link went out yesterday and the deposit is still open — the property held on a promise. On the old way, this is the awkward chase call.',
                phone: { title: 'Sophie Mercer’s Phone', items: [{ type: 'sms', text: 'Harbourside Lettings: your holding deposit for Flat 1, Pier View (£415.00) secures the property — pay at pay.harbourside-lettings.co.uk/d/2219', time: 'Tue 16:20' }] },
                ops: { rows: [{ ref: 'HQ-2219', sub: 'Due · valid until Fri 19 June', badge: { label: 'Due', tone: 'due' }, active: true }] },
              },
              {
                caption: 'A polite reminder sends itself this morning — no one had to remember it, no one had to phone.',
                phone: { title: 'Sophie Mercer’s Phone', items: [{ type: 'sms', text: 'Harbourside Lettings: a gentle reminder — your holding deposit (£415.00) is still open and your offer is being held. Pay any time at pay.harbourside-lettings.co.uk/d/2219', time: '09:00 · day 2' }] },
                ops: { rows: [{ ref: 'HQ-2219', sub: 'Day-2 reminder sent 09:00 — automatically', badge: { label: 'Day 2', tone: 'remind' }, active: true }] },
              },
              {
                caption: 'The nudge does the work. She taps through and pays £415.00 by card.',
                phone: { title: 'Sophie Mercer’s Phone', items: [{ type: 'invoice', label: 'Holding deposit · Flat 1, Pier View', amount: '£415.00', paid: { amount: '£415.00', time: 'day 2 · 09:24' } }] },
                ops: { rows: [{ ref: 'HQ-2219', sub: 'Paid · matching tenancy…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Matched to her tenancy automatically and off the daily summary. The property is secured — no one chased it by hand.',
                phone: { title: 'Sophie Mercer’s Phone', items: [{ type: 'invoice', label: 'Holding deposit · Flat 1, Pier View', amount: '£415.00', paid: { amount: '£415.00', time: 'day 2 · 09:24' } }] },
                ops: { sync: true, rows: [{ ref: 'HQ-2219', sub: 'Matched to tenancy · settled', badge: { label: 'Matched', tone: 'matched' } }], feed: 'The reminder did the chasing — the reference did the matching.' },
              },
            ],
          },
          {
            id: 'whitfield', tab: 'Joint applicants', customer: 'James & Anna Whitfield', blurb: 'One link, paid by card',
            steps: [
              {
                caption: 'A joint application for 6 Cliff Court — two names, one deposit, one link. Staff paste the tenancy reference and that’s it.',
                phone: { title: 'The Whitfields’ Phone', idle: { clock: '15:31', hint: 'No new messages' } },
                ops: { sync: true, rows: [{ ref: 'HQ-2220', sub: 'Generating branded deposit link…', badge: { label: 'Ready', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'The branded page shows the property, both their names and £520 — payable by card, Apple Pay or Google Pay.',
                phone: { title: 'The Whitfields’ Phone', items: [{ type: 'sms', text: 'Harbourside Lettings: your holding deposit for 6 Cliff Court (£520.00) secures the property for James & Anna Whitfield — pay at pay.harbourside-lettings.co.uk/d/2220', time: '15:33' }, { type: 'invoice', label: 'Holding deposit · 6 Cliff Court', amount: '£520.00', note: 'James & Anna Whitfield', cta: 'card' }] },
                ops: { rows: [{ ref: 'HQ-2220', sub: 'Link sent 15:33 · awaiting payment', badge: { label: 'Awaiting', tone: 'due' }, active: true }] },
              },
              {
                caption: 'They pay £520.00 by card that evening — one payment, against one tenancy.',
                phone: { title: 'The Whitfields’ Phone', items: [{ type: 'invoice', label: 'Holding deposit · 6 Cliff Court', amount: '£520.00', note: 'James & Anna Whitfield', paid: { amount: '£520.00', time: '19:48' } }] },
                ops: { rows: [{ ref: 'HQ-2220', sub: 'Paid · matching tenancy…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Matched and settled to the client account automatically — the same hands-off path, whoever pays and however they pay.',
                phone: { title: 'The Whitfields’ Phone', items: [{ type: 'invoice', label: 'Holding deposit · 6 Cliff Court', amount: '£520.00', note: 'James & Anna Whitfield', paid: { amount: '£520.00', time: '19:48' } }] },
                ops: { sync: true, rows: [{ ref: 'HQ-2220', sub: 'Matched to tenancy · settled to client account', badge: { label: 'Matched', tone: 'matched' } }], feed: 'One link, one reference, one tidy line in the log.' },
              },
            ],
          },
        ],
      },
      theatre: {
        intro: "An applicant has just been approved for Flat 2, 18 Anchor Quay. Press play to follow the holding deposit.",
        panes: [
          { key: 'applicant', label: "Applicant's Phone", tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Harbourside', sync: 'Live log' },
        ],
        steps: [
          {
            caption: "Approved. A staff member pastes the tenancy reference into the link generator — that is the whole job.",
            active: 'ops',
            rows: {
              applicant: [{ ref: 'HQ-2218', who: 'Eleanor Hartley', sub: 'Approved for Flat 2, 18 Anchor Quay', status: 'due', label: 'New' }],
              ops: [{ ref: 'HQ-2218', who: 'Eleanor Hartley', sub: 'Generating branded deposit link…', status: 'due', label: 'Ready' }],
            },
          },
          {
            caption: "The link arrives by text — the property, her name, £450, and a plain validity date. No bank details to copy out.",
            active: 'applicant',
            rows: {
              applicant: [{ ref: 'HQ-2218', who: 'Pay your holding deposit', sub: '£450 · valid until Fri 19 June', status: 'due', label: 'Link sent' }],
              ops: [{ ref: 'HQ-2218', who: 'Eleanor Hartley', sub: 'Link sent 11:05 · awaiting payment', status: 'due', label: 'Awaiting' }],
            },
          },
          {
            caption: "She pays by Apple Pay before the congratulations call has even ended.",
            active: 'applicant',
            rows: {
              applicant: [{ ref: 'HQ-2218', who: 'Paid £450.00', sub: 'Apple Pay · 11:09 · receipt emailed', status: 'paid', label: 'Paid' }],
              ops: [{ ref: 'HQ-2218', who: 'Eleanor Hartley', sub: 'Payment received · matching tenancy…', status: 'paid', label: 'Paid' }],
            },
          },
          {
            caption: "The reference travels with the payment, so it reconciles against the right tenancy on its own. The Excel log is gone.",
            active: 'ops',
            rows: {
              applicant: [{ ref: 'HQ-2218', who: 'Paid £450.00', sub: 'Receipt emailed to Eleanor', status: 'paid', label: 'Paid' }],
              ops: [{ ref: 'HQ-2218', who: 'Eleanor Hartley', sub: 'Matched to tenancy · settles to client account', status: 'paid', label: 'Matched' }],
            },
          },
          {
            caption: "And the one still unpaid? It sits on the daily summary with a gentle nudge — not in someone's memory.",
            active: 'ops',
            rows: {
              applicant: [{ ref: 'HQ-2219', who: 'Pay your holding deposit', sub: '£415 · reminder sent this morning', status: 'reminder', label: 'Nudged' }],
              ops: [
                { ref: 'HQ-2218', who: 'Eleanor Hartley', sub: 'Matched · settled', status: 'paid', label: 'Matched' },
                { ref: 'HQ-2219', who: 'Sophie Mercer', sub: 'Polite reminder sent · day 2', status: 'reminder', label: 'Nudged' },
              ],
            },
          },
        ],
      },
    },
  },

  {
    slug: 'marsh-vale-plumbing',
    name: 'Marsh & Vale Plumbing & Heating',
    live: false,
    vertical: 'Trades & Home Services',
    pattern: 'Invoices that collect themselves',
    tagline:
      'A fictional sole-trader heating engineer, showing the deep version of the build: Xero raises the invoice, the link sends itself, the payment marks its own invoice paid — and reminders go out so he never has to ask twice.',
    summary:
      'Approve an invoice in Xero and the rest happens on its own: link texted, paid in one tap, marked paid in Xero, reminders only if needed. No more card numbers down the phone.',
    brand: { bg: '#1E3A2F', surface: '#F5F2EB', accent: '#B87333', ink: '#1B2B22' },
    methods: ['Visa', 'Mastercard', 'Apple Pay', 'Google Pay'],
    demoComponent: 'MarshValeCheckout',
    caseStudy: {
      /* Renders the interactive end-to-end workflow theatre in place of the
         static CaseFlow strip — see src/components/portfolio/MarshValeFlow.astro */
      flowDemo: 'MarshValeFlow',
      /* Unified, scenario-selectable workflow — the reference implementation that
         supersedes flowDemo/theatre/ops. Pick a customer, follow their payment;
         the board state folds in the old standalone OpsPanel. Rendered by
         src/components/portfolio/WorkflowTheatre.astro. */
      workflow: {
        intro: 'Pick a customer to follow their payment end to end — or open The Board to see how the week settles itself.',
        brand: { mark: 'M&V', nameLines: ['Marsh & Vale', 'Plumbing & Heating'] },
        panes: [
          { key: 'system', label: 'His Accounting · Xero', tag: 'Simulated view' },
          { key: 'phone', label: 'Customer’s Phone', tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Marsh & Vale', sync: 'Xero' },
        ],
        board: {
          title: 'Invoices · this week',
          sync: 'Connected to Xero',
          caption: 'Every invoice and its live status, in one place — reminders and reconciliation running themselves. Nothing to match by hand.',
          feed: 'This week: 14 of 16 invoices settled — every payment matched to its job automatically.',
          rows: [
            { ref: 'INV-2153', who: 'R. Whittaker — leaking valve', amount: '£120.00', status: 'paid', label: 'Paid' },
            { ref: 'INV-2151', who: 'D. Osei — bathroom re-pipe', amount: '£1,240.00', status: 'paid', label: 'Paid' },
            { ref: 'INV-2150', who: 'S. Klein — boiler, by transfer', amount: '£560.00', status: 'paid', label: 'Matched' },
            { ref: 'INV-2148', who: 'L. Cooper — two radiators', amount: '£410.00', status: 'reminder', label: 'Day 3' },
            { ref: 'INV-2142', who: 'M. Hughes — emergency call-out', amount: '£95.00', status: 'overdue', label: 'Day 9' },
          ],
        },
        scenarios: [
          {
            id: 'whittaker',
            tab: 'Paid on the spot',
            customer: 'R. Whittaker',
            blurb: 'Taps Apple Pay the same evening',
            steps: [
              {
                caption: 'Tuesday, 6:10pm. The valve is fixed. He approves INV-2153 in Xero from the van — the only thing he does in this whole story.',
                system: { rows: [{ ref: 'INV-2153', who: 'R. Whittaker — leaking valve', amount: '£120.00', badge: { label: 'Approved', tone: 'sent' }, active: true }] },
                phone: { title: 'R. Whittaker’s Phone', idle: { clock: '18:10', hint: 'No new messages' } },
                ops: { rows: [{ ref: 'INV-2153', sub: 'Waiting for approval', badge: { label: '—', tone: 'draft' } }] },
              },
              {
                caption: 'SettlePay spots the approved invoice and texts a branded payment link. He’s already driving home.',
                system: { rows: [{ ref: 'INV-2153', who: 'R. Whittaker — leaking valve', amount: '£120.00', badge: { label: 'Approved', tone: 'sent' } }] },
                phone: { title: 'R. Whittaker’s Phone', items: [{ type: 'sms', text: 'Marsh & Vale Plumbing: thanks for having us out today. Your invoice INV-2153 (£120.00) is ready — pay securely at pay.marshandvale.co.uk/i/2153', time: '18:11' }] },
                ops: { sync: true, rows: [{ ref: 'INV-2153', sub: 'Link texted 18:11', badge: { label: 'Sent', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'The customer opens the link: the job, itemised, on a page in Marsh & Vale’s name.',
                system: { rows: [{ ref: 'INV-2153', who: 'R. Whittaker — leaking valve', amount: '£120.00', badge: { label: 'Approved', tone: 'sent' } }] },
                phone: { title: 'R. Whittaker’s Phone', items: [{ type: 'sms', text: 'Marsh & Vale Plumbing: your invoice INV-2153 (£120.00) is ready — pay at pay.marshandvale.co.uk/i/2153', time: '18:11' }, { type: 'invoice', label: 'Invoice INV-2153 · leaking valve repair', amount: '£120.00', cta: 'applepay' }] },
                ops: { rows: [{ ref: 'INV-2153', sub: 'Link opened · awaiting payment', badge: { label: 'Sent', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'One tap of Apple Pay on the sofa. £120.00, paid at 6:42pm.',
                system: { rows: [{ ref: 'INV-2153', who: 'R. Whittaker — leaking valve', amount: '£120.00', badge: { label: 'Approved', tone: 'sent' } }] },
                phone: { title: 'R. Whittaker’s Phone', items: [{ type: 'sms', text: 'Marsh & Vale Plumbing: your invoice INV-2153 (£120.00) is ready — pay at pay.marshandvale.co.uk/i/2153', time: '18:11' }, { type: 'invoice', label: 'Invoice INV-2153 · leaking valve repair', amount: '£120.00', paid: { amount: '£120.00', time: '18:42' } }] },
                ops: { rows: [{ ref: 'INV-2153', sub: 'Paid · matching reference…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'The payment carries INV-2153 home — Xero is marked paid automatically. Nothing to match, nothing to chase.',
                system: { rows: [{ ref: 'INV-2153', who: 'R. Whittaker — leaking valve', amount: '£120.00', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
                phone: { title: 'R. Whittaker’s Phone', items: [{ type: 'invoice', label: 'Invoice INV-2153 · leaking valve repair', amount: '£120.00', paid: { amount: '£120.00', time: '18:42' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-2153', sub: 'Paid · marked paid in Xero', badge: { label: 'Paid', tone: 'paid' } }], feed: 'Nothing to match by hand — the reference did the work.' },
              },
            ],
          },
          {
            id: 'cooper',
            tab: 'Needed a nudge',
            customer: 'L. Cooper',
            blurb: 'Pays after an automatic reminder',
            steps: [
              {
                caption: 'INV-2148 went out three days ago and is still open. On the old way, this is where the awkward chase text gets written.',
                system: { rows: [{ ref: 'INV-2148', who: 'L. Cooper — two radiators', amount: '£410.00', badge: { label: 'Sent', tone: 'sent' }, active: true }] },
                phone: { title: 'L. Cooper’s Phone', items: [{ type: 'sms', text: 'Marsh & Vale Plumbing: your invoice INV-2148 (£410.00) is ready — pay at pay.marshandvale.co.uk/i/2148', time: 'Mon 17:40' }] },
                ops: { rows: [{ ref: 'INV-2148', sub: 'Due · day 3 tomorrow', badge: { label: 'Due', tone: 'due' }, active: true }] },
              },
              {
                caption: 'Day 3, 9am: a polite reminder sends itself — written once, in his voice. He doesn’t lift a finger.',
                system: { rows: [{ ref: 'INV-2148', who: 'L. Cooper — two radiators', amount: '£410.00', badge: { label: 'Sent', tone: 'sent' } }] },
                phone: { title: 'L. Cooper’s Phone', items: [{ type: 'sms', text: 'Marsh & Vale Plumbing: just a gentle reminder — invoice INV-2148 (£410.00) is still open. Pay any time at pay.marshandvale.co.uk/i/2148', time: '09:00 · day 3' }] },
                ops: { rows: [{ ref: 'INV-2148', sub: 'Day-3 reminder sent 09:00 — automatically', badge: { label: 'Day 3', tone: 'remind' }, active: true }] },
              },
              {
                caption: 'The nudge does the work. She taps through and pays £410.00 — no second ask needed.',
                system: { rows: [{ ref: 'INV-2148', who: 'L. Cooper — two radiators', amount: '£410.00', badge: { label: 'Sent', tone: 'sent' } }] },
                phone: { title: 'L. Cooper’s Phone', items: [{ type: 'invoice', label: 'Invoice INV-2148 · two radiators fitted', amount: '£410.00', paid: { amount: '£410.00', time: 'day 3 · 09:18' } }] },
                ops: { rows: [{ ref: 'INV-2148', sub: 'Paid · matching reference…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Marked paid in Xero automatically. He never had to write the awkward message — or send it twice.',
                system: { rows: [{ ref: 'INV-2148', who: 'L. Cooper — two radiators', amount: '£410.00', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
                phone: { title: 'L. Cooper’s Phone', items: [{ type: 'invoice', label: 'Invoice INV-2148 · two radiators fitted', amount: '£410.00', paid: { amount: '£410.00', time: 'day 3 · 09:18' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-2148', sub: 'Paid · marked paid in Xero', badge: { label: 'Paid', tone: 'paid' } }], feed: 'The reminder did the asking — reconciliation did the rest.' },
              },
            ],
          },
          {
            id: 'klein',
            tab: 'Paid by bank transfer',
            customer: 'S. Klein',
            blurb: 'Prefers a transfer — matched by reference',
            steps: [
              {
                caption: 'Some customers still prefer a bank transfer — which used to mean matching “BOILER” to an invoice by memory.',
                system: { rows: [{ ref: 'INV-2150', who: 'S. Klein — boiler replacement', amount: '£560.00', badge: { label: 'Sent', tone: 'sent' }, active: true }] },
                phone: { title: 'S. Klein’s Phone', items: [{ type: 'sms', text: 'Marsh & Vale Plumbing: your invoice INV-2150 (£560.00) is ready — pay by card or bank transfer at pay.marshandvale.co.uk/i/2150', time: '14:02' }] },
                ops: { sync: true, rows: [{ ref: 'INV-2150', sub: 'Link texted 14:02', badge: { label: 'Sent', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'The branded page offers card or transfer — with a unique reference baked in, so the payment can find its own invoice.',
                system: { rows: [{ ref: 'INV-2150', who: 'S. Klein — boiler replacement', amount: '£560.00', badge: { label: 'Sent', tone: 'sent' } }] },
                phone: { title: 'S. Klein’s Phone', items: [{ type: 'invoice', label: 'Invoice INV-2150 · boiler replacement', amount: '£560.00', note: 'Bank transfer · reference MV-2150', cta: 'transfer' }] },
                ops: { rows: [{ ref: 'INV-2150', sub: 'Awaiting payment · reference MV-2150', badge: { label: 'Due', tone: 'due' }, active: true }] },
              },
              {
                caption: 'She pays £560.00 from her banking app. The reference carries the invoice number home.',
                system: { rows: [{ ref: 'INV-2150', who: 'S. Klein — boiler replacement', amount: '£560.00', badge: { label: 'Sent', tone: 'sent' } }] },
                phone: { title: 'S. Klein’s Phone', items: [{ type: 'invoice', label: 'Invoice INV-2150 · boiler replacement', amount: '£560.00', note: 'Bank transfer · reference MV-2150', paid: { amount: '£560.00', time: 'transfer received' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-2150', sub: 'Transfer received · matching reference…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Matched and marked paid automatically — no bank feed to eyeball, even for a transfer.',
                system: { rows: [{ ref: 'INV-2150', who: 'S. Klein — boiler replacement', amount: '£560.00', badge: { label: 'Matched', tone: 'matched' }, active: true }] },
                phone: { title: 'S. Klein’s Phone', items: [{ type: 'invoice', label: 'Invoice INV-2150 · boiler replacement', amount: '£560.00', note: 'Bank transfer · reference MV-2150', paid: { amount: '£560.00', time: 'transfer received' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-2150', sub: 'Matched by reference · marked paid in Xero', badge: { label: 'Matched', tone: 'matched' } }], feed: 'Even bank transfers reconcile themselves when the reference does the work.' },
              },
            ],
          },
        ],
      },
      profile: [
        { label: 'Team', value: 'Sole trader' },
        { label: 'Volume', value: '~30 invoices a month' },
        { label: 'Terms', value: '14 days' },
        { label: 'Paid by, before', value: 'Bank details by text, card numbers by phone' },
      ],
      background:
        'Marsh & Vale is a fictional one-man plumbing and heating business that already did the right things: invoices raised properly in Xero from the van, sent the same day. Getting paid was the broken half. Customers who wanted to "sort it now" read card numbers down the phone; everyone else got bank details by text and paid when they remembered. Evenings went on matching the bank feed by eye and writing chase messages that felt awkward to send to people he might work for again.',
      hook:
        'Every invoice raised properly in Xero — then the money chased by hand: card numbers read down the phone, transfers labelled “BOILER”, and reminders written on his own evenings.',
      painPoints: [
        'About half of UK small-business invoices are paid late (Xero data) — for him that meant <strong>several evenings a month</strong> writing chase texts and matching the bank feed',
        'UK businesses affected by late payment average <strong>86 hours a year</strong> of staff time chasing it (DBT / Small Business Commissioner, 2025) — for a sole trader, those hours are unpaid overtime',
        'Card numbers over the phone are MOTO payments: the riskiest way to take a card — remote-purchase fraud cost the UK <strong>nearly £400m in 2024</strong> (UK Finance) — and they pull his phone and notepad into PCI scope',
        'Transfers arrived as <strong>"BOILER"</strong> or nothing at all, matched to invoices by memory',
      ],
      setup: {
        had: [
          'Xero — invoicing and the bank feed, used properly',
          'A smartphone and a tablet in the van — customers reached by text and WhatsApp',
          'His own business bank account; no website to speak of',
        ],
        access: [
          'Xero’s public API, authorised by him in one click with his own login — the owner-consented integration every major accounting platform supports',
          'His own Stripe account — payments settle as Marsh & Vale, to his account',
          'Customer mobile numbers already sitting on each Xero invoice',
        ],
        untouched: [
          'Card numbers — he never sees, hears or writes one again; the hosted page takes them',
          'His banking — settlement lands in the same account it always did',
          'His customer records — they stay in Xero; the payment layer carries references and amounts, not his books',
        ],
        note: 'A sole trader on Xero is, honestly, the best-served business in the country for this work: the API access is real, owner-authorised, and revocable by him at any time. That is what makes the deep version of the build a fair promise here — where a business runs closed or offline software instead, we say so and build the lighter version, like the other studies on this page.',
      },
      delivered: [
        'The branded invoice page (the demo below)',
        'Auto-send: approving an invoice in Xero texts the customer a payment link',
        'Auto-reconcile: a payment marks its Xero invoice paid the moment it lands',
        'Polite automatic reminders at day 3, 7 and 14 — written once, sent forever',
        'A weekly summary: what’s paid, what’s due, what’s getting a reminder',
        'Apple Pay and Google Pay first, card form as the fallback',
      ],
      flow: [
        { title: 'Job Done, Invoice Approved', detail: 'He approves the invoice in Xero from the van, exactly as he already did.' },
        { title: 'Link Texts Itself', detail: 'The customer gets a branded page showing the work, itemised, with the job address.' },
        { title: 'Paid in One Tap', detail: 'Apple Pay, Google Pay or card — no bank details to copy out of a text.' },
        { title: 'Xero Updates Itself', detail: 'The payment carries INV-2147 home; the invoice is marked paid without him touching it.' },
        { title: 'Reminders Only if Needed', detail: 'Day 3, 7 and 14 nudges go out on schedule. He never has to ask twice in person.' },
      ],
      ops: {
        url: 'app.settlepay.uk/marsh-vale',
        title: 'Invoices',
        subtitle: 'Marsh & Vale · June',
        sync: 'Connected to Xero',
        rows: [
          { ref: 'INV-2147', who: 'K. Patel — boiler service', amount: '£386.40', status: 'paid', label: 'Paid', sub: 'Paid 18:31 · marked paid in Xero' },
          { ref: 'INV-2151', who: 'S. Bryce — bathroom tap', amount: '£95.00', status: 'paid', label: 'Paid', sub: 'Paid in 4 minutes · Apple Pay' },
          { ref: 'INV-2148', who: 'L. Cooper — two radiators', amount: '£410.00', status: 'reminder', label: 'Day 3', sub: 'First reminder sent 09:00' },
          { ref: 'INV-2143', who: 'D. Hale — callout', amount: '£85.00', status: 'overdue', label: 'Day 14', sub: 'Final reminder sent · flagged for a call' },
          { ref: 'INV-2152', who: 'M. Forsyth — annual service', amount: '£120.00', status: 'due', label: 'Sent', sub: 'Link texted today' },
        ],
        feed: 'June so far: 24 of 27 invoices paid without a single manual chase.',
      },
      outcome: {
        stats: [
          {
            value: '≈ 5 hrs a month',
            label: 'Evenings of chasing recovered',
            sub: 'Reminders, matching and "did that transfer come in?" checks now run themselves — the 86-hours-a-year national average was coming out of his evenings.',
          },
          {
            value: 'Up to 2× faster',
            label: 'From invoice to money',
            sub: 'Xero’s own data: invoices offering an online payment option are paid up to twice as fast as those without one.',
          },
          {
            value: '0 card numbers',
            label: 'Taken over the phone',
            sub: 'The hosted page removes him from the riskiest category of UK card fraud — and from the PCI burden that phone payments carry.',
          },
        ],
        basis: [
          '~30 invoices a month on 14-day terms, with roughly a third previously needing at least one chase — consistent with Xero data that about half of UK small-business invoices are paid late.',
          'UK businesses affected by late payment average 86 hours a year of staff time chasing it — DBT / Office of the Small Business Commissioner research, 2025.',
          '"Paid up to twice as fast" with online payment options — Xero platform data, cited as Xero’s.',
          'Remote purchase (card-not-present) fraud: just under £400 million lost in 2024, the largest category of UK card fraud — UK Finance Annual Fraud Report 2025. A hosted payment page also keeps card data away from the business entirely, with PCI DSS handled by the processor.',
        ],
      },
      roi: {
        period: 'month',
        volumeLabel: 'Invoices you raise',
        minutesLabel: 'Minutes chasing & matching each one today',
        rateLabel: 'What your hour is worth',
        volume: { default: 30, min: 5, max: 120, step: 5 },
        minutes: { default: 9, min: 3, max: 25, step: 1 },
        rate: { default: 18, min: 12, max: 45, step: 1 },
        lens: 'On top of the time: invoices with an online payment option are paid up to twice as fast (Xero data) — and not one card number is read down the phone.',
      },
    },
  },

  {
    slug: 'rowan-physiotherapy',
    name: 'Rowan Physiotherapy',
    live: false,
    vertical: 'Independent Practitioners & Clinics',
    pattern: 'Deposits + instalment plans',
    tagline:
      'A fictional one-practitioner clinic, showing deposits that confirm bookings in Cliniko automatically and treatment plans that collect themselves — with clinical records staying exactly where they belong.',
    summary:
      'Booking deposits sent automatically when an assessment is booked, instalment plans that collect on schedule, and a morning summary instead of a spreadsheet.',
    brand: { bg: '#52705C', surface: '#F4F6F1', accent: '#7FA08A', ink: '#2E4034' },
    methods: ['Visa', 'Mastercard', 'Apple Pay'],
    demoComponent: 'RowanCheckout',
    caseStudy: {
      profile: [
        { label: 'Team', value: '1 practitioner + part-time reception' },
        { label: 'Volume', value: '~70 appointments a month' },
        { label: 'Plans', value: 'Six-session courses, paid monthly' },
        { label: 'Paid by, before', value: 'Transfers checked against the diary' },
      ],
      background:
        'Rowan Physiotherapy is a fictional single-practitioner clinic run on Cliniko: diary, notes and invoicing all in one place, a card machine at the front desk, and a part-time receptionist. New patients were asked to "pop the deposit over by bank transfer" before their assessment, and six-session treatment plans were tracked in a spreadsheet — who had paid which instalment, noticed mostly when something looked wrong. Each morning began by checking transfers against the day’s diary.',
      hook:
        'Patients asked to “pop the deposit over by bank transfer”, treatment plans tracked in a spreadsheet, and every morning starting by checking transfers against the day’s diary.',
      painPoints: [
        'No-shows: the NHS alone recorded <strong>8.4 million missed outpatient appointments in 2024–25</strong> — and a missed private slot is unsellable revenue plus a gap in someone’s recovery',
        'An unpaid deposit was only discovered <strong>the morning of the appointment</strong>, when it was too late to refill the slot',
        'Roughly <strong>2 hours a week</strong> of reception time went on matching transfers to bookings and updating the plan spreadsheet',
        'A failed plan instalment surfaced <strong>a month late</strong>, as an awkward conversation mid-treatment',
      ],
      setup: {
        had: [
          'Cliniko — diary, clinical notes and invoicing',
          'A card machine at the front desk for on-the-day payments',
          'A part-time receptionist and a treatment-plan spreadsheet',
        ],
        access: [
          'Cliniko’s public API, authorised by the practice — bookings come out, payment confirmations go back',
          'The clinic’s own processor account — settlement straight to the clinic',
          'Booking references and amounts only — the payment layer is built to need nothing else',
        ],
        untouched: [
          'Clinical records and notes — they never leave Cliniko, and SettlePay’s layer is designed so they never need to',
          'The diary itself — bookings are made exactly as before',
          'The front-desk card machine — still there for patients who pay on the day',
        ],
        note: 'Clinics sit in the middle of the access spectrum: the API is real, but the line that matters is data minimisation. The integration passes booking references and payment states — never notes, never conditions. For a practice, "what can you see?" is the first question a patient would ask, so it is the first question the build answers.',
      },
      delivered: [
        'The deposit and treatment-plan page (the demo below)',
        'New assessment booked in Cliniko → deposit link sent automatically',
        'Deposit paid → the booking is confirmed and marked in the diary',
        'Instalments collected on schedule; a failed card is retried, then flagged by name',
        'A morning summary: today’s list, with anything unpaid highlighted',
        'The plan spreadsheet, retired',
      ],
      flow: [
        { title: 'Booked in Cliniko', detail: 'Reception books the assessment exactly as they always have.' },
        { title: 'Deposit Link Sends Itself', detail: 'The patient gets a calm, branded page — deposit or full plan, their choice.' },
        { title: 'Booking Confirmed', detail: 'Payment lands, the diary entry is marked confirmed, reception does nothing.' },
        { title: 'Plans Collect Monthly', detail: 'Three instalments, shown to the patient up front, collected on their dates.' },
        { title: 'Failures Flagged Early', detail: 'A declined card is retried, then raised the same week — not found in a spreadsheet a month on.' },
      ],
      ops: {
        url: 'app.settlepay.uk/rowan',
        title: 'Bookings & Plans',
        subtitle: 'Rowan Physiotherapy · this week',
        sync: 'Connected to Cliniko',
        rows: [
          { ref: 'RP-0934', who: 'E. Sutton — initial assessment', amount: '£40.00', status: 'paid', label: 'Confirmed', sub: 'Deposit paid · confirmed in Cliniko' },
          { ref: 'RP-0921', who: 'T. Mason — plan, instalment 2 of 3', amount: '£90.00', status: 'paid', label: 'Collected', sub: 'Collected on schedule, 10 June' },
          { ref: 'RP-0936', who: 'A. Devlin — initial assessment', amount: '£40.00', status: 'due', label: 'Awaiting', sub: 'Link sent 10:12 · appointment Tue' },
          { ref: 'RP-0918', who: 'C. Rhodes — plan, instalment 3 of 3', amount: '£90.00', status: 'reminder', label: 'Retrying', sub: 'Card declined · retry tomorrow, then flagged' },
        ],
        feed: 'This month: every plan instalment collected without a phone call.',
      },
      outcome: {
        stats: [
          {
            value: 'Fewer empty slots',
            label: 'Deposits change the no-show maths',
            sub: 'Practices commonly report fewer no-shows once a deposit secures the booking — and when one still happens, the slot is no longer worth zero.',
          },
          {
            value: '≈ 2 hrs a week',
            label: 'Reception time recovered',
            sub: 'The morning transfer-checking ritual becomes a glance at a screen that has already matched everything.',
          },
          {
            value: 'Flagged in days',
            label: 'Failed instalments, not bad debts',
            sub: 'A declined card is retried and raised the same week, instead of surfacing a month later mid-treatment.',
          },
        ],
        basis: [
          '~70 appointments a month for one practitioner, with deposits previously arriving by transfer and checked against the diary by hand — the 2-hours-a-week reception figure is our stated assumption.',
          'Scale of the no-show problem: 8.4 million NHS outpatient appointments were missed in 2024–25 (NHS Digital); the NHS costs a missed appointment at around £160. The effect of deposits is reported by practices rather than measured in published UK studies, so we state it qualitatively.',
          'Reception time costed at typical UK administrator pay of £12–£14 an hour (2025 salary data).',
        ],
      },
      roi: {
        period: 'month',
        volumeLabel: 'Appointments you book',
        minutesLabel: 'Minutes matching & tracking each one today',
        rateLabel: 'Reception hourly rate',
        volume: { default: 70, min: 20, max: 200, step: 5 },
        minutes: { default: 7, min: 2, max: 20, step: 1 },
        rate: { default: 13, min: 11, max: 25, step: 1 },
        lens: 'And the bigger win is off this chart: a deposit that secures the booking changes the no-show maths, and an empty slot is no longer worth nothing.',
      },
      workflow: {
        intro: 'Pick a patient to follow their booking or plan — or open The Board to see the week at a glance.',
        brand: { mark: 'RP', nameLines: ['Rowan', 'Physiotherapy'] },
        panes: [
          { key: 'system', label: 'Diary · Cliniko', tag: 'Simulated view' },
          { key: 'phone', label: 'Patient’s Phone', tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Rowan', sync: 'Cliniko' },
        ],
        board: {
          title: 'Bookings & plans · this week',
          sync: 'Connected to Cliniko',
          caption: 'Deposits, plans and instalments in one place — matched to the diary automatically. The plan spreadsheet is retired.',
          feed: 'This month: every plan instalment collected without a phone call.',
          rows: [
            { ref: 'RP-0934', who: 'E. Sutton — initial assessment', amount: '£40.00', status: 'paid', label: 'Confirmed' },
            { ref: 'RP-0921', who: 'T. Mason — plan 2 of 3', amount: '£90.00', status: 'paid', label: 'Collected' },
            { ref: 'RP-0936', who: 'A. Devlin — initial assessment', amount: '£40.00', status: 'due', label: 'Awaiting' },
            { ref: 'RP-0918', who: 'C. Rhodes — plan 3 of 3', amount: '£90.00', status: 'reminder', label: 'Retrying' },
          ],
        },
        scenarios: [
          {
            id: 'sutton', tab: 'Deposit confirms the booking', customer: 'E. Sutton', blurb: 'Pays the deposit, slot secured',
            steps: [
              {
                caption: 'Reception books E. Sutton’s initial assessment in Cliniko, exactly as always. That’s the only manual step.',
                system: { rows: [{ ref: 'RP-0934', who: 'E. Sutton — initial assessment, Fri 19 Jun', amount: '£40.00', badge: { label: 'Booked', tone: 'sent' }, active: true }] },
                phone: { title: 'E. Sutton’s Phone', idle: { clock: '10:10', hint: 'No new messages' } },
                ops: { sync: true, rows: [{ ref: 'RP-0934', sub: 'New booking seen · sending deposit link…', badge: { label: 'Ready', tone: 'sent' } }] },
              },
              {
                caption: 'A calm, branded page goes out automatically — deposit or full plan, the patient’s choice.',
                system: { rows: [{ ref: 'RP-0934', who: 'E. Sutton — initial assessment, Fri 19 Jun', amount: '£40.00', badge: { label: 'Booked', tone: 'sent' } }] },
                phone: { title: 'E. Sutton’s Phone', items: [{ type: 'sms', text: 'Rowan Physiotherapy: your initial assessment on Fri 19 June is held. Secure it with a £40 deposit (it comes off your fee on the day) at pay.rowanphysio.co.uk/b/0934', time: '10:12' }] },
                ops: { rows: [{ ref: 'RP-0934', sub: 'Link sent 10:12 · awaiting deposit', badge: { label: 'Awaiting', tone: 'due' }, active: true }] },
              },
              {
                caption: 'She pays the £40 deposit by Apple Pay — it comes off her assessment fee on the day.',
                system: { rows: [{ ref: 'RP-0934', who: 'E. Sutton — initial assessment, Fri 19 Jun', amount: '£40.00', badge: { label: 'Booked', tone: 'sent' } }] },
                phone: { title: 'E. Sutton’s Phone', items: [{ type: 'invoice', label: 'Booking deposit · initial assessment, Fri 19 Jun', amount: '£40.00', note: 'Comes off your fee on the day', paid: { amount: '£40.00', time: '10:15 · Apple Pay' } }] },
                ops: { rows: [{ ref: 'RP-0934', sub: 'Paid · confirming booking…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'The booking is marked confirmed in Cliniko automatically — reception never touches it, and the slot is secured.',
                system: { rows: [{ ref: 'RP-0934', who: 'E. Sutton — initial assessment, Fri 19 Jun', amount: '£40.00', badge: { label: 'Confirmed', tone: 'paid' }, active: true }] },
                phone: { title: 'E. Sutton’s Phone', items: [{ type: 'invoice', label: 'Booking deposit · initial assessment, Fri 19 Jun', amount: '£40.00', paid: { amount: '£40.00', time: '10:15 · Apple Pay' } }] },
                ops: { sync: true, rows: [{ ref: 'RP-0934', sub: 'Confirmed in Cliniko · settled to the clinic', badge: { label: 'Confirmed', tone: 'matched' } }], feed: 'No transfer to check against the diary in the morning.' },
              },
            ],
          },
          {
            id: 'mason', tab: 'Treatment plan', customer: 'T. Mason', blurb: 'Six-session course, paid monthly',
            steps: [
              {
                caption: 'T. Mason books a six-session course. The branded page offers the full plan — three monthly instalments of £90, shown up front, no surprises.',
                system: { rows: [{ ref: 'RP-0921', who: 'T. Mason — six-session course', amount: '£270.00', badge: { label: 'Booked', tone: 'sent' }, active: true }] },
                phone: { title: 'T. Mason’s Phone', items: [{ type: 'sms', text: 'Rowan Physiotherapy: your six-session course is booked. Set up your plan — 3 monthly instalments of £90 — at pay.rowanphysio.co.uk/b/0921', time: '09:40' }] },
                ops: { rows: [{ ref: 'RP-0921', sub: 'Plan link sent · awaiting setup', badge: { label: 'Awaiting', tone: 'due' }, active: true }] },
              },
              {
                caption: 'He sets it up and the first instalment is taken today — £90. The next two are scheduled on their dates.',
                system: { rows: [{ ref: 'RP-0921', who: 'T. Mason — six-session course', amount: '£270.00', badge: { label: 'Plan active', tone: 'paid' }, active: true }] },
                phone: { title: 'T. Mason’s Phone', items: [{ type: 'invoice', label: 'Treatment plan · six sessions', amount: '£90.00', note: 'Instalment 1 of 3 · then 10 Jul, 10 Aug', paid: { amount: '£90.00', time: 'today' } }] },
                ops: { rows: [{ ref: 'RP-0921', sub: 'Instalment 1 of 3 paid · plan active', badge: { label: 'Active', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'A month on, instalment 2 collects itself on its date — no reminder, no card machine, no phone call.',
                system: { rows: [{ ref: 'RP-0921', who: 'T. Mason — six-session course', amount: '£270.00', badge: { label: 'Plan active', tone: 'paid' } }] },
                phone: { title: 'T. Mason’s Phone', items: [{ type: 'invoice', label: 'Treatment plan · six sessions', amount: '£90.00', note: 'Instalment 2 of 3 · collected 10 Jul', paid: { amount: '£90.00', time: '10 Jul · automatic' } }] },
                ops: { sync: true, rows: [{ ref: 'RP-0921', sub: 'Instalment 2 of 3 collected on schedule', badge: { label: 'Collected', tone: 'matched' }, active: true }] },
              },
              {
                caption: 'Every instalment matched to the patient and the course automatically. The plan spreadsheet is retired.',
                system: { rows: [{ ref: 'RP-0921', who: 'T. Mason — six-session course', amount: '£270.00', badge: { label: 'On track', tone: 'paid' }, active: true }] },
                phone: { title: 'T. Mason’s Phone', items: [{ type: 'invoice', label: 'Treatment plan · six sessions', amount: '£90.00', note: 'Instalment 2 of 3 · final on 10 Aug', paid: { amount: '£90.00', time: '10 Jul · automatic' } }] },
                ops: { rows: [{ ref: 'RP-0921', sub: '2 of 3 collected · final on 10 Aug', badge: { label: 'On track', tone: 'paid' } }], feed: 'Every plan instalment collected without a phone call.' },
              },
            ],
          },
          {
            id: 'rhodes', tab: 'A card fails', customer: 'C. Rhodes', blurb: 'Declined, retried, flagged early',
            steps: [
              {
                caption: 'C. Rhodes is on the final instalment of her plan — and on the due date, her card declines. On a spreadsheet, this surfaces a month late.',
                system: { rows: [{ ref: 'RP-0918', who: 'C. Rhodes — plan, instalment 3 of 3', amount: '£90.00', badge: { label: 'Active', tone: 'sent' }, active: true }] },
                phone: { title: 'C. Rhodes’s Phone', idle: { clock: '08:01', hint: 'No new messages' } },
                ops: { rows: [{ ref: 'RP-0918', sub: 'Instalment 3 declined · card expired', badge: { label: 'Declined', tone: 'overdue' }, active: true }] },
              },
              {
                caption: 'SettlePay retries the card automatically the next day — most failures are just a temporary glitch.',
                system: { rows: [{ ref: 'RP-0918', who: 'C. Rhodes — plan, instalment 3 of 3', amount: '£90.00', badge: { label: 'Active', tone: 'sent' } }] },
                phone: { title: 'C. Rhodes’s Phone', items: [{ type: 'sms', text: 'Rowan Physiotherapy: we couldn’t take your final plan instalment (£90) today. No action needed yet — we’ll try again tomorrow.', time: '08:05' }] },
                ops: { rows: [{ ref: 'RP-0918', sub: 'Auto-retry scheduled for tomorrow', badge: { label: 'Retrying', tone: 'remind' }, active: true }] },
              },
              {
                caption: 'The retry still fails — so it’s raised by name on this week’s summary, not found in a spreadsheet a month into treatment.',
                system: { rows: [{ ref: 'RP-0918', who: 'C. Rhodes — plan, instalment 3 of 3', amount: '£90.00', badge: { label: 'Action needed', tone: 'overdue' }, active: true }] },
                phone: { title: 'C. Rhodes’s Phone', items: [{ type: 'sms', text: 'Rowan Physiotherapy: your card still didn’t go through. Pop in a new card any time at pay.rowanphysio.co.uk/b/0918 — no rush, just so your plan stays on track.', time: 'day 2 · 08:05' }] },
                ops: { rows: [{ ref: 'RP-0918', sub: 'Retry failed · flagged on this week’s summary', badge: { label: 'Flagged', tone: 'overdue' }, active: true }] },
              },
              {
                caption: 'She updates her card and the instalment clears. A problem caught in days and handled kindly — not an awkward conversation mid-session.',
                system: { rows: [{ ref: 'RP-0918', who: 'C. Rhodes — plan, instalment 3 of 3', amount: '£90.00', badge: { label: 'Complete', tone: 'paid' }, active: true }] },
                phone: { title: 'C. Rhodes’s Phone', items: [{ type: 'invoice', label: 'Treatment plan · final instalment', amount: '£90.00', paid: { amount: '£90.00', time: 'day 2 · 16:20' } }] },
                ops: { sync: true, rows: [{ ref: 'RP-0918', sub: 'New card · instalment cleared · plan complete', badge: { label: 'Collected', tone: 'matched' } }], feed: 'Failed cards surface in days, not a month late.' },
              },
            ],
          },
        ],
      },
      theatre: {
        intro: "A new patient has just booked an initial assessment in Cliniko. Press play to follow the booking and the plan behind it.",
        panes: [
          { key: 'cliniko', label: 'Cliniko Booking', tag: 'Simulated' },
          { key: 'patient', label: "Patient's Phone", tag: 'Simulated', idle: 'No message yet' },
          { key: 'ops', label: 'SettlePay · Rowan', sync: 'Cliniko' },
        ],
        steps: [
          {
            caption: "Reception books the assessment exactly as they always have. SettlePay sees the new booking.",
            active: 'cliniko',
            rows: {
              cliniko: [{ ref: 'RP-0934', who: 'E. Sutton', sub: 'Initial assessment · Tue 10:00', status: 'due', label: 'Booked' }],
              patient: [],
              ops: [{ ref: 'RP-0934', who: 'E. Sutton', sub: 'New booking · sending deposit link', status: 'due', label: 'New' }],
            },
          },
          {
            caption: "A calm, branded page goes out automatically — deposit or full treatment plan, the patient's choice.",
            active: 'patient',
            rows: {
              cliniko: [{ ref: 'RP-0934', who: 'E. Sutton', sub: 'Initial assessment · awaiting deposit', status: 'due', label: 'Pending' }],
              patient: [{ ref: 'RP-0934', who: 'Secure your appointment', sub: '£40 deposit · comes off the fee', status: 'due', label: 'Link sent' }],
              ops: [{ ref: 'RP-0934', who: 'E. Sutton', sub: 'Deposit link sent 10:12', status: 'due', label: 'Awaiting' }],
            },
          },
          {
            caption: "Deposit paid. The booking is confirmed in Cliniko — reception does nothing.",
            active: 'cliniko',
            rows: {
              cliniko: [{ ref: 'RP-0934', who: 'E. Sutton', sub: 'Initial assessment · confirmed', status: 'paid', label: 'Confirmed' }],
              patient: [{ ref: 'RP-0934', who: 'Paid £40.00', sub: 'Appointment secured · receipt sent', status: 'paid', label: 'Paid' }],
              ops: [{ ref: 'RP-0934', who: 'E. Sutton', sub: 'Confirmed in Cliniko automatically', status: 'paid', label: 'Confirmed' }],
            },
          },
          {
            caption: "For treatment plans, the instalments collect themselves on schedule — the patient saw the whole plan up front.",
            active: 'ops',
            rows: {
              cliniko: [{ ref: 'RP-0921', who: 'T. Mason', sub: 'Six-session plan · in progress', status: 'paid', label: 'Active' }],
              patient: [{ ref: 'RP-0921', who: 'Instalment 2 of 3', sub: '£90 collected · 10 June', status: 'paid', label: 'Collected' }],
              ops: [{ ref: 'RP-0921', who: 'T. Mason', sub: 'Instalment 2 of 3 collected on schedule', status: 'paid', label: 'Collected' }],
            },
          },
          {
            caption: "And a failed card? Retried automatically, then flagged the same week — not found in a spreadsheet a month later.",
            active: 'ops',
            rows: {
              cliniko: [{ ref: 'RP-0918', who: 'C. Rhodes', sub: 'Six-session plan · instalment 3', status: 'reminder', label: 'Attention' }],
              patient: [{ ref: 'RP-0918', who: 'Instalment 3 of 3', sub: 'Card declined · retry tomorrow', status: 'reminder', label: 'Retrying' }],
              ops: [{ ref: 'RP-0918', who: 'C. Rhodes', sub: 'Retry scheduled · flagged to reception', status: 'reminder', label: 'Flagged' }],
            },
          },
        ],
      },
    },
  },

  {
    slug: 'stillwater-weddings',
    name: 'Stillwater Weddings',
    live: false,
    vertical: 'Photographers & Event Suppliers',
    pattern: 'Staged payments on a schedule',
    tagline:
      'A fictional wedding photographer with no systems at all — showing what an honest build looks like when there is nothing to integrate with: the payment layer becomes the system of record for money.',
    summary:
      'Deposit charged at booking, balance requested automatically four weeks out, reminders in her own voice — and a season view of every wedding, paid or pending.',
    brand: { bg: '#26231F', surface: '#FAF7F1', accent: '#C8A36A', ink: '#26231F' },
    methods: ['Visa', 'Mastercard', 'Amex'],
    demoComponent: 'StillwaterCheckout',
    caseStudy: {
      profile: [
        { label: 'Team', value: 'Sole trader' },
        { label: 'Volume', value: '~25 weddings a year' },
        { label: 'Per booking', value: '£350 deposit + £1,400 balance' },
        { label: 'Paid by, before', value: 'Bank transfer, chased by email' },
      ],
      background:
        'Stillwater Weddings is a fictional photographer whose entire business ran on an inbox, an enquiry spreadsheet and e-signed contracts — which is to say, like most creative sole traders. Every booking meant two payments to shepherd by hand: a deposit to confirm the date, then a balance chased by email about a month before the wedding, landing in the couple’s most stressful fortnight. Fifty hand-written payment conversations a season, each one a small withdrawal from the client relationship.',
      hook:
        'Two payments to shepherd by hand for every booking — a deposit to hold the date, then a balance chased by email in the couple’s most stressful fortnight.',
      painPoints: [
        'Two payments per wedding × 25 weddings = <strong>~50 hand-typed payment threads</strong> a season, each needing follow-up, checking and a thank-you',
        'Balance chasing lands <strong>four weeks before the wedding</strong> — precisely when couples are most stretched and goodwill matters most',
        'A late balance means <strong>shooting a wedding not yet paid for</strong>, or an ultimatum to people whose day she is about to share',
        'Like all UK small businesses: roughly <strong>half of invoices are paid late</strong> (Xero), and affected businesses average <strong>86 hours a year</strong> chasing (DBT, 2025)',
      ],
      setup: {
        had: [
          'An inbox, an enquiry spreadsheet and e-signed contracts',
          'A portfolio site and Instagram',
          'No CRM, no booking system, no API — nothing to integrate with',
        ],
        access: [
          'Honestly: nothing to plug into — and the build says so rather than pretending otherwise',
          'Her own processor account — settlement straight to her business account',
          'Booking details typed once into a simple season sheet that generates everything else',
        ],
        untouched: [
          'Her contracts, her inbox and her way of working — the payment layer is the only new thing',
          'No software to buy, migrate to or maintain',
        ],
        note: 'The smallest businesses often have no system at all — and the honest offer there is not a fantasy integration, it is a payment layer self-contained enough to BE the money system: every wedding, deposit and balance in one view, with a CSV her accountant can take at year end. When there is nothing to connect to, we say so, and build for that.',
      },
      delivered: [
        'The booking-confirmation page with the open payment schedule (the demo below)',
        'Deposit charged at booking; the balance request sends itself four weeks before the date',
        'Gentle automatic reminders if a balance sits unpaid — written once, in her voice',
        'A season view: every wedding, every deposit, every balance, at a glance',
        'Automatic receipts and thank-yous to every couple',
        'CSV export for the accountant at year end',
      ],
      flow: [
        { title: 'Booking Confirmed', detail: 'She types the couple, date and package into the season sheet — once.' },
        { title: 'Deposit Paid', detail: 'The couple confirm their date on a branded page, schedule shown in full.' },
        { title: 'Balance Asks for Itself', detail: 'Four weeks out, the balance link sends on schedule — no email to compose.' },
        { title: 'Reminders in Her Voice', detail: 'If needed, nudges go out in words she wrote once — warm, not robotic.' },
        { title: 'Season at a Glance', detail: 'Every wedding shows paid or pending; the awkward spreadsheet is gone.' },
      ],
      ops: {
        url: 'app.settlepay.uk/stillwater',
        title: 'Season View',
        subtitle: 'Stillwater Weddings · 2026 season',
        sync: 'Season log · CSV export',
        rows: [
          { ref: 'SW-1106', who: 'Eleanor & James — 19 Sep', amount: '£350.00', status: 'paid', label: 'Deposit', sub: 'Deposit paid · balance scheduled 22 Aug' },
          { ref: 'SW-1102', who: 'Priya & Tom — 11 Jul', amount: '£1,400.00', status: 'paid', label: 'Settled', sub: 'Balance paid five days early' },
          { ref: 'SW-1104', who: 'Megan & Chris — 8 Aug', amount: '£1,400.00', status: 'due', label: 'Requested', sub: 'Balance request sent 11 Jul, on schedule' },
          { ref: 'SW-1099', who: 'Hannah & Will — 27 Jun', amount: '£1,400.00', status: 'reminder', label: 'Nudged', sub: 'Gentle reminder sent · due Friday' },
        ],
        feed: 'This season: every balance so far paid before the wedding, none chased by hand.',
      },
      outcome: {
        stats: [
          {
            value: '~50 → 0',
            label: 'Hand-written payment chases a season',
            sub: 'Requests, reminders and receipts compose themselves — the conversations that strained client goodwill simply stop happening.',
          },
          {
            value: 'On time, every time',
            label: 'Balance requests never slip',
            sub: 'The four-weeks-out request sends itself even in peak season — late asks were the single biggest cause of late balances.',
          },
          {
            value: '≈ 20 hrs a season',
            label: 'Admin recovered',
            sub: 'Roughly 45 minutes of chasing, checking and matching removed per wedding — time that was coming out of editing evenings.',
          },
        ],
        basis: [
          'No reliable published figures exist for wedding suppliers specifically, so this scenario leans only on cross-sector data: roughly half of UK small-business invoices are paid late (Xero), and businesses affected by late payment average 86 hours a year chasing it (DBT / Small Business Commissioner, 2025).',
          '25 weddings a year, two payments each, ~45 minutes of combined chasing and reconciling per booking — our assumptions, stated so you can swap in your own numbers.',
        ],
      },
      roi: {
        period: 'year',
        volumeLabel: 'Weddings you book',
        minutesLabel: 'Minutes chasing deposit + balance per booking',
        rateLabel: 'What your hour is worth',
        volume: { default: 25, min: 8, max: 80, step: 1 },
        minutes: { default: 45, min: 15, max: 90, step: 5 },
        rate: { default: 18, min: 12, max: 45, step: 1 },
        lens: 'And the balance request sends itself four weeks out — even in peak season — so the awkward money chase at the worst possible moment simply stops.',
      },
      workflow: {
        intro: 'Pick a wedding to follow its payments — or open The Board to see the whole season at a glance.',
        brand: { mark: 'SW', nameLines: ['Stillwater', 'Weddings'] },
        panes: [
          { key: 'phone', label: 'Couple’s Phone', tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Stillwater', sync: 'Live record' },
        ],
        board: {
          title: 'The season · weddings',
          sync: 'Live record',
          caption: 'With no other system to keep, SettlePay is the record for money — every deposit and balance for the season in one place, not fifty email threads.',
          feed: '25 weddings this season — every deposit and balance tracked automatically.',
          rows: [
            { ref: 'SW-1099', who: 'Grace & Tom · 7 Jun', amount: '£1,750.00', status: 'paid', label: 'Settled' },
            { ref: 'SW-1118', who: 'Hannah & Mo · 12 Jul', amount: '£1,400.00', status: 'due', label: 'Balance due' },
            { ref: 'SW-1106', who: 'Eleanor & James · 19 Sep', amount: '£350.00', status: 'paid', label: 'Deposit paid' },
            { ref: 'SW-1121', who: 'Priya & Sam · 30 Aug', amount: '£1,400.00', status: 'reminder', label: 'Balance · Day 3' },
            { ref: 'SW-1124', who: 'New enquiry · 4 Oct', amount: '£350.00', status: 'due', label: 'Deposit sent' },
          ],
        },
        scenarios: [
          {
            id: 'deposit', tab: 'Deposit secures the date', customer: 'Eleanor & James', blurb: 'Paid at booking',
            steps: [
              {
                caption: 'Eleanor & James confirm their date. At booking, the deposit is requested on a branded page — the date isn’t held on a promise.',
                phone: { title: 'Eleanor & James’s Phone', items: [{ type: 'sms', text: 'Stillwater Weddings: so excited for 19 September! Secure your date with your £350 booking deposit at pay.stillwaterweddings.co.uk/b/1106', time: 'Booked · 16:20' }] },
                ops: { rows: [{ ref: 'SW-1106', sub: 'Booking deposit requested · awaiting', badge: { label: 'Awaiting', tone: 'due' }, active: true }] },
              },
              {
                caption: 'They pay the £350 deposit by card that evening. The date is theirs.',
                phone: { title: 'Eleanor & James’s Phone', items: [{ type: 'invoice', label: 'Booking deposit · wedding 19 September', amount: '£350.00', paid: { amount: '£350.00', time: '19:05' } }] },
                ops: { rows: [{ ref: 'SW-1106', sub: 'Deposit paid · date secured', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'With no other system to keep, SettlePay becomes the record: the deposit is logged and the balance scheduled for four weeks out — automatically.',
                phone: { title: 'Eleanor & James’s Phone', items: [{ type: 'invoice', label: 'Booking deposit · wedding 19 September', amount: '£350.00', paid: { amount: '£350.00', time: '19:05' } }] },
                ops: { rows: [{ ref: 'SW-1106', sub: 'Deposit logged · balance scheduled for 22 Aug', badge: { label: 'Scheduled', tone: 'sent' } }], feed: 'No spreadsheet, no inbox thread — one tidy record per wedding.' },
              },
            ],
          },
          {
            id: 'balance', tab: 'Balance, four weeks out', customer: 'Eleanor & James', blurb: 'Requested automatically, no chase',
            steps: [
              {
                caption: 'Four weeks before the wedding — the exact moment a balance chase used to land in a couple’s most stressful fortnight. Here it sends itself, warmly.',
                phone: { title: 'Eleanor & James’s Phone', items: [{ type: 'sms', text: 'Stillwater Weddings: not long now! Your final balance of £1,400 for 19 September is ready whenever you are — pay at pay.stillwaterweddings.co.uk/b/1106', time: '22 Aug · 10:00' }] },
                ops: { rows: [{ ref: 'SW-1106', sub: 'Balance requested automatically · 4 weeks out', badge: { label: 'Sent', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'No ultimatum, no awkward email she had to write. They pay the £1,400 balance the same day.',
                phone: { title: 'Eleanor & James’s Phone', items: [{ type: 'invoice', label: 'Final balance · wedding 19 September', amount: '£1,400.00', paid: { amount: '£1,400.00', time: '22 Aug · 21:14' } }] },
                ops: { rows: [{ ref: 'SW-1106', sub: 'Balance paid · wedding fully settled', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Fully paid four weeks early — she shoots the day knowing it’s settled, the relationship intact.',
                phone: { title: 'Eleanor & James’s Phone', items: [{ type: 'invoice', label: 'Final balance · wedding 19 September', amount: '£1,400.00', paid: { amount: '£1,400.00', time: '22 Aug · 21:14' } }] },
                ops: { rows: [{ ref: 'SW-1106', sub: '£1,750 settled in full · Eleanor & James', badge: { label: 'Settled', tone: 'matched' } }], feed: 'No balance chased in the run-up to the day.' },
              },
            ],
          },
          {
            id: 'nudge', tab: 'Balance needs a nudge', customer: 'Priya & Sam', blurb: 'One gentle reminder, then paid',
            steps: [
              {
                caption: 'Priya & Sam’s balance went out four weeks ago and is still open, with the wedding approaching.',
                phone: { title: 'Priya & Sam’s Phone', items: [{ type: 'sms', text: 'Stillwater Weddings: your final balance of £1,400 for 30 August is ready whenever you are — pay at pay.stillwaterweddings.co.uk/b/1121', time: '2 Aug · 10:00' }] },
                ops: { rows: [{ ref: 'SW-1121', sub: 'Balance due · 4 weeks out', badge: { label: 'Due', tone: 'due' }, active: true }] },
              },
              {
                caption: 'A gentle reminder sends itself, in her own voice — not a panicked chase the week before.',
                phone: { title: 'Priya & Sam’s Phone', items: [{ type: 'sms', text: 'Stillwater Weddings: just a gentle reminder — your final balance (£1,400) for 30 August is still open. No rush, pay any time at pay.stillwaterweddings.co.uk/b/1121', time: '09:00 · day 3' }] },
                ops: { rows: [{ ref: 'SW-1121', sub: 'Day-3 reminder sent 09:00 — automatically', badge: { label: 'Day 3', tone: 'remind' }, active: true }] },
              },
              {
                caption: 'They pay the £1,400 balance the same morning — the nudge did the asking.',
                phone: { title: 'Priya & Sam’s Phone', items: [{ type: 'invoice', label: 'Final balance · wedding 30 August', amount: '£1,400.00', paid: { amount: '£1,400.00', time: 'day 3 · 11:40' } }] },
                ops: { rows: [{ ref: 'SW-1121', sub: 'Paid · wedding fully settled', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Settled, with goodwill intact — and not one email she dreaded sending.',
                phone: { title: 'Priya & Sam’s Phone', items: [{ type: 'invoice', label: 'Final balance · wedding 30 August', amount: '£1,400.00', paid: { amount: '£1,400.00', time: 'day 3 · 11:40' } }] },
                ops: { rows: [{ ref: 'SW-1121', sub: '£1,750 settled in full · Priya & Sam', badge: { label: 'Settled', tone: 'matched' } }], feed: 'The reminder did the chasing — kindly, and on time.' },
              },
            ],
          },
        ],
      },
      theatre: {
        intro: "A couple has just confirmed their wedding date. Press play to follow both payments — without a single chase email.",
        panes: [
          { key: 'couple', label: "The Couple's Phone", tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Season View', sync: 'Season log' },
        ],
        steps: [
          {
            caption: "She types the couple, date and package into the season sheet once. SettlePay handles both payments from here.",
            active: 'ops',
            rows: {
              couple: [{ ref: 'SW-1106', who: 'Eleanor & James', sub: 'Full Day Collection · Sat 19 Sep', status: 'due', label: 'Booked' }],
              ops: [{ ref: 'SW-1106', who: 'Eleanor & James', sub: 'Deposit due now · balance scheduled', status: 'due', label: 'New' }],
            },
          },
          {
            caption: "The couple confirm their date on a branded page — the whole schedule shown openly, nothing hidden.",
            active: 'couple',
            rows: {
              couple: [{ ref: 'SW-1106', who: 'Pay £350 deposit', sub: 'Balance £1,400 due Sat 22 Aug', status: 'due', label: 'Deposit due' }],
              ops: [{ ref: 'SW-1106', who: 'Eleanor & James', sub: 'Deposit page opened', status: 'due', label: 'Awaiting' }],
            },
          },
          {
            caption: "Deposit paid — the date is theirs. The balance sits scheduled, clearly not charged, until four weeks out.",
            active: 'ops',
            rows: {
              couple: [{ ref: 'SW-1106', who: 'Deposit paid £350.00', sub: 'Date confirmed · receipt sent', status: 'paid', label: 'Deposit' }],
              ops: [{ ref: 'SW-1106', who: 'Eleanor & James', sub: 'Deposit paid · balance scheduled 22 Aug', status: 'scheduled', label: 'Scheduled' }],
            },
          },
          {
            caption: "Four weeks before the wedding, the balance request sends itself — in her words, on schedule, even in peak season.",
            active: 'couple',
            rows: {
              couple: [{ ref: 'SW-1106', who: 'Final balance £1,400', sub: 'Due before Sat 19 Sep', status: 'due', label: 'Requested' }],
              ops: [{ ref: 'SW-1106', who: 'Eleanor & James', sub: 'Balance request sent automatically', status: 'due', label: 'Requested' }],
            },
          },
          {
            caption: "Balance settled before the day — no chase, no awkward conversation at the worst possible moment.",
            active: 'ops',
            rows: {
              couple: [{ ref: 'SW-1106', who: 'Balance paid £1,400.00', sub: 'Paid in full · thank-you sent', status: 'paid', label: 'Settled' }],
              ops: [
                { ref: 'SW-1106', who: 'Eleanor & James', sub: 'Paid in full · settles to her account', status: 'paid', label: 'Settled' },
                { ref: 'SW-1104', who: 'Megan & Chris', sub: 'Balance request sent · on schedule', status: 'due', label: 'Requested' },
              ],
            },
          },
        ],
      },
    },
  },

  {
    slug: 'whitmore-accountants',
    name: 'Whitmore & Co. Accountants',
    live: false,
    vertical: 'Professional Services',
    pattern: 'Retainers by Direct Debit',
    tagline:
      'A fictional small practice on closed desktop software — showing the build that works beside a legacy system: mandates and collections through the two platforms with real APIs, the practice software left exactly where it was.',
    summary:
      'A hundred and twenty retainers collected by Direct Debit instead of standing orders, one-off fees collected against the same mandate, and everything reconciled into Xero on its own.',
    brand: { bg: '#332E28', surface: '#F7F4EE', accent: '#C9892B', ink: '#332E28' },
    methods: ['Direct Debit'],
    demoComponent: 'WhitmoreCheckout',
    caseStudy: {
      profile: [
        { label: 'Team', value: '2 partners + 3 staff' },
        { label: 'Clients', value: '~120 on monthly retainers' },
        { label: 'Also billed', value: 'One-off fees by invoice' },
        { label: 'Paid by, before', value: 'Standing orders + bank transfer' },
      ],
      background:
        'Whitmore & Co. is a fictional five-person practice of a familiar kind: client work managed in long-serving desktop practice software, the firm’s own books in Xero, and a hundred and twenty retainer clients paying by standing orders the clients themselves had to set up. Standing orders break silently — a client changes bank and the retainer just stops, discovered two months later in a reconciliation. One-off fees went out as invoices and came back as transfers, eventually. A capable team was spending real hours on credit control for predictable, agreed amounts.',
      hook:
        'A hundred and twenty retainers paid by standing orders the clients set up themselves — and standing orders break silently, found two months later in a reconciliation.',
      painPoints: [
        '<strong>40% of small accountancy practices</strong> spend over an hour every week chasing overdue invoices (GoCardless × FSB survey, 2025)',
        '<strong>57% sometimes write debts off</strong> rather than keep chasing them (same survey) — forfeiting fees that were never in dispute',
        'Standing orders <strong>fail silently</strong>: no notification, no retry, just a gap found at month-end across 120 mandates',
        'Mistyped references meant <strong>manual matching</strong> of retainer payments that should have reconciled themselves',
      ],
      setup: {
        had: [
          'Desktop practice-management software — closed, long-serving, and with no realistic API access for a third party',
          'Xero for the practice’s own ledger',
          'A client list, and engagement letters sent by email',
        ],
        access: [
          'The practice’s own GoCardless account for Direct Debit — set up in their name, collecting to their account',
          'Xero’s API for their own ledger — collections reconcile into it automatically',
          'The client list as a one-off CSV export, used to generate mandate invitations',
        ],
        untouched: [
          'The practice software — we worked beside it, not inside it, and said so from the first meeting',
          'Client tax and accounts data — never touches the payment layer; references and amounts only',
          'The protection itself — every mandate carries the Direct Debit Guarantee, from the client’s own bank',
        ],
        note: 'Legacy desktop practice software is the classic "no — we can’t integrate with that", and saying it up front is part of the service. The build leans instead on the two systems with real, owner-authorised APIs: GoCardless for collection and Xero for the ledger. A one-off CSV did the rest. The result behaves like a deep integration where it counts, without a single promise the old software could not keep.',
      },
      delivered: [
        'The two-step mandate page with the Direct Debit Guarantee in full (the demo below)',
        '120 mandate invitations generated from one CSV export',
        'Retainers collected monthly; failures retried automatically, then flagged by name',
        'One-off fees collected against the same mandate, with proper advance notice each time',
        'Collections reconciled into Xero automatically',
        'A monthly credit-control summary that replaced the chasing list',
      ],
      flow: [
        { title: 'Engagement Accepted', detail: 'The client signs the engagement letter, exactly as before.' },
        { title: 'Mandate in Two Steps', detail: 'Account details, then a calm confirmation with the Guarantee shown in full.' },
        { title: 'Retainers Collect Monthly', detail: 'A hundred and twenty collections happen on their own, on the same day.' },
        { title: 'One-Off Fees, Same Mandate', detail: 'Ad-hoc invoices collect with proper advance notice — no new setup, no chasing.' },
        { title: 'Ledger Updates Itself', detail: 'Collections reconcile into Xero; failures are flagged the same morning, by name.' },
      ],
      ops: {
        url: 'app.settlepay.uk/whitmore',
        title: 'Collections',
        subtitle: 'Whitmore & Co. · July run',
        sync: 'GoCardless + Xero',
        rows: [
          { ref: 'WC-0412', who: 'Hartley Joinery — monthly retainer', amount: '£120.00', status: 'paid', label: 'Collected', sub: 'Collected 1 Jul · reconciled to Xero' },
          { ref: 'WC-0398', who: 'Bramble Café — monthly retainer', amount: '£150.00', status: 'paid', label: 'Collected', sub: 'Collected 1 Jul' },
          { ref: 'WC-0405', who: 'F. Nash — self-assessment fee', amount: '£240.00', status: 'scheduled', label: 'Noticed', sub: 'Advance notice sent · collects 8 Jul' },
          { ref: 'WC-0376', who: 'Orchard Glazing — monthly retainer', amount: '£120.00', status: 'reminder', label: 'Flagged', sub: 'Mandate failed · new invitation sent, partner notified' },
        ],
        feed: 'July run: collected first time for all but one client — flagged and re-invited the same morning.',
      },
      outcome: {
        stats: [
          {
            value: '1+ hr a week → minutes',
            label: 'Credit-control time',
            sub: 'The weekly chasing hour that 40% of small practices report (GoCardless × FSB, 2025) becomes a glance at a flagged-exceptions list.',
          },
          {
            value: 'Fewer write-offs',
            label: 'Debts stopped before they age',
            sub: '57% of small practices sometimes forfeit payment rather than chase it. A failed collection here is flagged the same morning, not discovered at year end.',
          },
          {
            value: '≈ 70% of UK bills',
            label: 'Already collect this way',
            sub: 'Direct Debit covered around 70% of the UK’s regular bill payments in 2024 (UK Finance) — clients already trust the rail, and every mandate carries the Guarantee.',
          },
        ],
        basis: [
          '120 retainer clients previously paying by standing order, with one-off fees invoiced by transfer.',
          '40% of small accountancy practices spend over an hour a week chasing overdue invoices; 57% sometimes write debts off rather than chase — GoCardless × FSB survey, 2025 (accountancy subsample n=100).',
          '4.9 billion Direct Debits were collected in the UK in 2024, around 70% of regular bill payments — UK Finance, UK Payment Markets 2025.',
          'Direct Debit also fails far less often than recurring card payments (GoCardless/IDC research) — one reason the retainer uses a mandate rather than a stored card.',
        ],
      },
      roi: {
        period: 'month',
        volumeLabel: 'Clients on a monthly retainer',
        minutesLabel: 'Minutes of credit control per client a month',
        rateLabel: 'Cost of an hour of fee-earner time',
        volume: { default: 120, min: 20, max: 400, step: 10 },
        minutes: { default: 2, min: 1, max: 8, step: 1 },
        rate: { default: 25, min: 14, max: 60, step: 1 },
        lens: 'And fewer write-offs: 57% of small practices sometimes forfeit a fee rather than chase it — here a failed collection is flagged the same morning, not found at year end.',
      },
      workflow: {
        intro: 'Pick a client to follow their Direct Debit — or open The Board to see the month’s collection run.',
        brand: { mark: 'WC', nameLines: ['Whitmore', '& Co.'] },
        panes: [
          { key: 'phone', label: 'Client’s Phone', tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Collections', sync: 'GoCardless + Xero' },
        ],
        board: {
          title: 'Collections · July run',
          sync: 'GoCardless + Xero',
          caption: 'Every retainer and one-off fee on one rail — collected on schedule, reconciled into Xero, failures flagged the same morning. No chasing list.',
          feed: 'July run: collected first time for all but one client — flagged and re-invited the same morning.',
          rows: [
            { ref: 'WC-0412', who: 'Hartley Joinery — monthly retainer', amount: '£120.00', status: 'paid', label: 'Collected' },
            { ref: 'WC-0398', who: 'Bramble Café — monthly retainer', amount: '£150.00', status: 'paid', label: 'Collected' },
            { ref: 'WC-0405', who: 'F. Nash — self-assessment fee', amount: '£240.00', status: 'scheduled', label: 'Noticed' },
            { ref: 'WC-0376', who: 'Orchard Glazing — monthly retainer', amount: '£120.00', status: 'reminder', label: 'Flagged' },
            { ref: 'WC-0420', who: 'Lentell Ltd — monthly retainer', amount: '£180.00', status: 'paid', label: 'Collected' },
          ],
        },
        scenarios: [
          {
            id: 'hartley', tab: 'New retainer', customer: 'Hartley Joinery', blurb: 'Direct Debit, set up once',
            steps: [
              {
                caption: 'Whitmore generate a mandate invitation from one CSV export — no standing order for the client to set up themselves.',
                phone: { title: 'Hartley Joinery’s Phone', items: [{ type: 'sms', text: 'Whitmore & Co.: set up your monthly retainer by Direct Debit (£120/month, with the Direct Debit Guarantee) at pay.whitmore.co.uk/m/0412', time: '09:30' }] },
                ops: { sync: true, rows: [{ ref: 'WC-0412', sub: 'Mandate invitation sent', badge: { label: 'Invited', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'Two calm steps: bank details, then a clear confirmation with the Direct Debit Guarantee shown in full.',
                phone: { title: 'Hartley Joinery’s Phone', items: [{ type: 'invoice', label: 'Direct Debit · monthly retainer', amount: '£120/month', note: 'Direct Debit Guarantee included', cta: 'mandate' }] },
                ops: { rows: [{ ref: 'WC-0412', sub: 'Mandate being authorised', badge: { label: 'Pending', tone: 'due' }, active: true }] },
              },
              {
                caption: 'Mandate active. From now on the £120 retainer collects itself every month — set up once.',
                phone: { title: 'Hartley Joinery’s Phone', items: [{ type: 'invoice', label: 'Direct Debit · monthly retainer', amount: '£120/month', paid: { label: 'Direct Debit active · £120/month' } }] },
                ops: { rows: [{ ref: 'WC-0412', sub: 'Mandate active · scheduled monthly', badge: { label: 'Active', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'On collection day, £120 lands and reconciles into Xero on its own — no reference to match, no standing order to police.',
                phone: { title: 'Hartley Joinery’s Phone', items: [{ type: 'invoice', label: 'Monthly retainer · 1 July', amount: '£120.00', paid: { label: 'Collected £120.00 · 1 Jul' } }] },
                ops: { sync: true, rows: [{ ref: 'WC-0412', sub: 'Collected 1 Jul · reconciled to Xero', badge: { label: 'Collected', tone: 'matched' } }], feed: '120 retainers collect on the same day — reconciled into Xero automatically.' },
              },
            ],
          },
          {
            id: 'nash', tab: 'One-off fee, same mandate', customer: 'F. Nash', blurb: 'Collected against the existing mandate',
            steps: [
              {
                caption: 'F. Nash already has a mandate. A one-off self-assessment fee can collect against it — no new setup, no invoice to chase.',
                phone: { title: 'F. Nash’s Phone', items: [{ type: 'sms', text: 'Whitmore & Co.: your self-assessment fee of £240 will be collected by Direct Debit on 8 July, under your existing mandate. No action needed.', time: '1 Jul' }] },
                ops: { rows: [{ ref: 'WC-0405', sub: 'One-off fee · advance notice sent', badge: { label: 'Noticed', tone: 'sent' }, active: true }] },
              },
              {
                caption: 'Proper advance notice goes out automatically — the Direct Debit rules require it, and the client always knows what’s coming.',
                phone: { title: 'F. Nash’s Phone', items: [{ type: 'invoice', label: 'Self-assessment fee · one-off', amount: '£240.00', note: 'Collects 8 Jul · existing mandate' }] },
                ops: { rows: [{ ref: 'WC-0405', sub: 'Advance notice given · scheduled 8 Jul', badge: { label: 'Scheduled', tone: 'due' }, active: true }] },
              },
              {
                caption: 'On the 8th it collects against the same mandate — £240, no second setup, no transfer to match.',
                phone: { title: 'F. Nash’s Phone', items: [{ type: 'invoice', label: 'Self-assessment fee · one-off', amount: '£240.00', paid: { label: 'Collected £240.00 · 8 Jul' } }] },
                ops: { rows: [{ ref: 'WC-0405', sub: 'Collected 8 Jul · matched to client', badge: { label: 'Collected', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Reconciled into Xero automatically, against F. Nash. One mandate carries the retainer and the ad-hoc fees alike.',
                phone: { title: 'F. Nash’s Phone', items: [{ type: 'invoice', label: 'Self-assessment fee · one-off', amount: '£240.00', paid: { label: 'Collected £240.00 · 8 Jul' } }] },
                ops: { sync: true, rows: [{ ref: 'WC-0405', sub: 'Reconciled to Xero · one-off fee settled', badge: { label: 'Matched', tone: 'matched' } }], feed: 'Ad-hoc fees collect on the same rail as the retainer — nothing re-keyed.' },
              },
            ],
          },
          {
            id: 'orchard', tab: 'A mandate fails', customer: 'Orchard Glazing', blurb: 'Caught the same morning, re-invited',
            steps: [
              {
                caption: 'Orchard Glazing’s mandate fails — the kind of silent break a standing order would hide until a month-end reconciliation.',
                phone: { title: 'Orchard Glazing’s Phone', idle: { clock: '07:30', hint: 'No new messages' } },
                ops: { rows: [{ ref: 'WC-0376', sub: 'Mandate failed · client changed bank', badge: { label: 'Failed', tone: 'overdue' }, active: true }] },
              },
              {
                caption: 'But it isn’t hidden. The same morning, the partner is notified and a fresh mandate invitation goes out automatically.',
                phone: { title: 'Orchard Glazing’s Phone', items: [{ type: 'sms', text: 'Whitmore & Co.: your Direct Debit needs renewing (a bank change, perhaps). Pop in your new details at pay.whitmore.co.uk/m/0376 — your retainer stays uninterrupted.', time: '08:00' }] },
                ops: { rows: [{ ref: 'WC-0376', sub: 'Partner notified · new invitation sent', badge: { label: 'Re-invited', tone: 'remind' }, active: true }] },
              },
              {
                caption: 'The client re-confirms in two steps. The mandate is live again — the retainer never actually lapsed.',
                phone: { title: 'Orchard Glazing’s Phone', items: [{ type: 'invoice', label: 'Direct Debit · monthly retainer', amount: '£120/month', paid: { label: 'Direct Debit active · £120/month' } }] },
                ops: { rows: [{ ref: 'WC-0376', sub: 'New mandate active · back on schedule', badge: { label: 'Active', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'A break caught the same morning, not at year-end. 57% of small practices write fees off rather than chase — this one doesn’t have to.',
                phone: { title: 'Orchard Glazing’s Phone', items: [{ type: 'invoice', label: 'Direct Debit · monthly retainer', amount: '£120/month', paid: { label: 'Direct Debit active · £120/month' } }] },
                ops: { sync: true, rows: [{ ref: 'WC-0376', sub: 'Reconciled · no fee written off', badge: { label: 'Recovered', tone: 'matched' } }], feed: 'Silent failures become same-morning flags — not year-end write-offs.' },
              },
            ],
          },
        ],
      },
      theatre: {
        intro: "A new client has just accepted their engagement letter. Press play to follow the retainer from setup to a flagged failure.",
        panes: [
          { key: 'client', label: "Client's Screen", tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Collections', sync: 'GoCardless + Xero' },
        ],
        steps: [
          {
            caption: "From one CSV export, a mandate invitation is generated — no standing order for the client to set up themselves.",
            active: 'ops',
            rows: {
              client: [{ ref: 'WC-0412', who: 'Hartley Joinery', sub: 'Mandate invitation received', status: 'due', label: 'Invited' }],
              ops: [{ ref: 'WC-0412', who: 'Hartley Joinery', sub: 'Mandate invitation sent', status: 'due', label: 'Invited' }],
            },
          },
          {
            caption: "Two calm steps: bank details, then a clear confirmation with the Direct Debit Guarantee shown in full.",
            active: 'client',
            rows: {
              client: [{ ref: 'WC-0412', who: 'Set up Direct Debit', sub: '£120/month · Guarantee shown in full', status: 'due', label: 'Confirming' }],
              ops: [{ ref: 'WC-0412', who: 'Hartley Joinery', sub: 'Mandate being authorised', status: 'due', label: 'Pending' }],
            },
          },
          {
            caption: "Mandate active. From now on the £120 retainer collects itself every month — set up once.",
            active: 'ops',
            rows: {
              client: [{ ref: 'WC-0412', who: 'Mandate active', sub: '£120/month · first collection 1 Jul', status: 'paid', label: 'Active' }],
              ops: [{ ref: 'WC-0412', who: 'Hartley Joinery', sub: 'Mandate active · scheduled monthly', status: 'scheduled', label: 'Scheduled' }],
            },
          },
          {
            caption: "On collection day, payments land and reconcile into Xero on their own — and a one-off fee collects against the same mandate.",
            active: 'ops',
            rows: {
              client: [{ ref: 'WC-0405', who: 'F. Nash', sub: 'Self-assessment fee · advance notice sent', status: 'scheduled', label: 'Noticed' }],
              ops: [
                { ref: 'WC-0412', who: 'Hartley Joinery', sub: 'Collected 1 Jul · reconciled to Xero', status: 'paid', label: 'Collected' },
                { ref: 'WC-0405', who: 'F. Nash — one-off fee', sub: 'Advance notice sent · collects 8 Jul', status: 'scheduled', label: 'Noticed' },
              ],
            },
          },
          {
            caption: "And a failed mandate? Flagged the same morning, re-invited automatically — not discovered at year-end. 57% of practices write fees off rather than chase; this practice doesn't have to.",
            active: 'ops',
            rows: {
              client: [{ ref: 'WC-0376', who: 'Orchard Glazing', sub: 'New mandate invitation received', status: 'reminder', label: 'Re-invited' }],
              ops: [
                { ref: 'WC-0412', who: 'Hartley Joinery', sub: 'Collected · reconciled', status: 'paid', label: 'Collected' },
                { ref: 'WC-0376', who: 'Orchard Glazing', sub: 'Mandate failed · re-invited, partner notified', status: 'overdue', label: 'Flagged' },
              ],
            },
          },
        ],
      },
    },
  },

  {
    slug: 'camber-finch-auctions',
    name: 'Camber & Finch Auctioneers',
    live: false,
    vertical: 'Fine Art & Auctions',
    pattern: 'Post-sale lot settlement',
    tagline:
      'A fictional fine-art and antiques auction house, showing the full system an auctioneer can have: every winning lot invoiced with buyer’s premium, paid by branded link, and matched back to its bidder automatically.',
    summary:
      'Hundreds of buyers settling after every sale, once reconciled by hand against bidder numbers — now invoiced with buyer’s premium, paid by branded link, and auto-matched to the lot so it can be released.',
    brand: { bg: '#5A1A2B', surface: '#F5F0E6', accent: '#9C6B3C', ink: '#3A1019' },
    methods: ['Bank Transfer', 'Visa', 'Mastercard', 'Amex'],
    demoComponent: 'CamberFinchCheckout',
    caseStudy: {
      profile: [
        { label: 'Business', value: 'Family-run auction house' },
        { label: 'Sales', value: '~20 auctions a year' },
        { label: 'Per sale', value: '~400 paying buyers' },
        { label: 'Paid by, before', value: 'Bank transfer + card by phone' },
      ],
      background:
        'Camber & Finch is a fictional fine-art, antiques and collectables auction house — country-house sales, jewellery, silver and pictures. After each sale, hundreds of winning buyers owe an invoice of hammer price plus buyer’s premium. Historically they paid by bank transfer (matched by hand against a bidder number) or read card details down the phone to the saleroom office. The week after every sale was a reconciliation marathon, and nothing could be released or shipped until a payment was found and matched.',
      hook:
        'Hundreds of winning buyers after every sale, paying by transfer matched to a bidder number by hand or card details read down the phone — and nothing ships until each one is found.',
      painPoints: [
        'Hundreds of invoices to settle and match by hand against bidder numbers after <strong>every</strong> sale — days of post-sale admin per auction',
        'Card details over the phone are the riskiest way to take payment — remote-purchase fraud cost the UK <strong>nearly £400m in 2024</strong> (UK Finance) — and they pull the saleroom phone line into PCI scope',
        'Overseas buyers (a big share of fine-art bidding) struggled to pay — international transfers were slow and arrived with <strong>mangled references</strong>',
        'Lots couldn’t be <strong>released or shipped</strong> until payment was matched, so staff time went on chasing and checking instead of cataloguing the next sale',
      ],
      setup: {
        had: [
          'A saleroom management system for cataloguing, bidding and invoicing',
          'A website with online bidding',
          'The auction house’s own bank account',
        ],
        access: [
          'Invoice, lot and bidder references via the saleroom system’s API (where one exists) — or a per-sale export where it doesn’t',
          'The auctioneer’s own processor account — settlement straight to the auction house',
          'Buyer contact details already captured at registration',
        ],
        untouched: [
          'The saleroom / catalogue system itself — we work alongside it, not inside it',
          'Consignor accounts and valuations — never touched by the payment layer',
          'Buyer data beyond the reference and amount needed to take and match a payment',
        ],
        note: 'Auction software varies enormously: some platforms expose a clean API (we connect and reconcile automatically), others are closed (we run the branded pay-by-link and match against an exported bidder reference). We scope to what the specific system allows — this illustrative build shows the fuller, API-connected version. Unlike a real client whose build was a payment page only, this is a what-could-be demonstration.',
      },
      delivered: [
        'A branded post-sale "Pay Your Invoice" page (the demo below)',
        'Buyer’s premium and VAT calculated and shown correctly per lot',
        'A pay-by-link sent automatically to each winning bidder after the sale',
        'Payments auto-matched to the bidder and lot, so it can be marked ready to release',
        'A settlement board: who’s paid, what’s outstanding, what’s ready to ship',
        'Automatic reminders for unpaid invoices, in the auction house’s own voice',
      ],
      workflow: {
        intro: 'Pick a buyer to follow their lot from sold to settled — or open The Board to see the whole sale at a glance.',
        brand: { mark: 'C&F', nameLines: ['Camber', '& Finch'] },
        panes: [
          { key: 'system', label: 'Saleroom System', tag: 'Simulated' },
          { key: 'phone', label: 'Buyer’s Phone', tag: 'Simulated' },
          { key: 'ops', label: 'SettlePay · Settlement', sync: 'Saleroom' },
        ],
        board: {
          title: 'Settlement board · Sale 0616',
          sync: 'Connected to saleroom',
          caption: 'Every lot, every invoice and its live status — matched to the lot automatically, reminders sending themselves. No settlement spreadsheet.',
          feed: 'This sale: 316 of 412 invoices settled, every payment matched to its lot automatically.',
          rows: [
            { ref: 'INV-3471', who: 'Bidder 142 — Lot 214', amount: '£2,232.00', status: 'paid', label: 'Released' },
            { ref: 'INV-3470', who: 'Bidder 138 — Lots 207, 209', amount: '£940.00', status: 'paid', label: 'Paid' },
            { ref: 'INV-3468', who: 'Bidder 097 — Lot 198', amount: '£3,410.00', status: 'reminder', label: 'Day 3' },
            { ref: 'INV-3462', who: 'Bidder 061 — Lot 176', amount: '£1,150.00', status: 'overdue', label: 'Day 7' },
            { ref: 'INV-3455', who: 'Bidder 044 — Lot 151', amount: '£680.00', status: 'paid', label: 'Released' },
          ],
        },
        scenarios: [
          {
            id: 'lot214', tab: 'Paid on the spot', customer: 'Bidder 142 · Lot 214', blurb: 'Pays by card in a tap',
            steps: [
              {
                caption: 'Lot 214 sells. The invoice is raised automatically — hammer price plus the 24% buyer’s premium.',
                system: { rows: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks · Bidder 142', amount: '£1,800', badge: { label: 'Sold', tone: 'sent' }, active: true }] },
                phone: { title: 'Buyer’s Phone · Bidder 142', idle: { clock: '14:32', hint: 'No new messages' } },
                ops: { sync: true, rows: [{ ref: 'INV-3471', sub: 'Invoice raised · £2,232.00 (hammer + premium)', badge: { label: 'New', tone: 'sent' } }] },
              },
              {
                caption: 'A branded pay-by-link goes to the winning bidder automatically — no invoice to post, no card read down the phone.',
                system: { rows: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks · Bidder 142', amount: '£2,232.00', badge: { label: 'Invoiced', tone: 'sent' } }] },
                phone: { title: 'Buyer’s Phone · Bidder 142', items: [{ type: 'sms', text: 'Camber & Finch: congratulations on Lot 214. Your invoice (£2,232.00, incl. 24% buyer’s premium) is ready — pay securely at pay.camberfinch.co.uk/i/3471', time: '14:34' }] },
                ops: { rows: [{ ref: 'INV-3471', sub: 'Branded link sent 14:34 · awaiting payment', badge: { label: 'Sent', tone: 'due' }, active: true }] },
              },
              {
                caption: 'The buyer pays by card in a tap — from anywhere in the world, no slow international transfer.',
                system: { rows: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks · Bidder 142', amount: '£2,232.00', badge: { label: 'Invoiced', tone: 'sent' } }] },
                phone: { title: 'Buyer’s Phone · Bidder 142', items: [{ type: 'invoice', label: 'Lot 214 · Georgian silver candlesticks', amount: '£2,232.00', note: 'Hammer £1,800 + 24% premium', paid: { amount: '£2,232.00', time: '14:41' } }] },
                ops: { rows: [{ ref: 'INV-3471', sub: 'Paid · matching to lot…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Matched to the bidder and the lot automatically — the saleroom marks it ready to release, with no hand-reconciliation.',
                system: { rows: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks · Bidder 142', amount: '£2,232.00', badge: { label: 'Ready to release', tone: 'paid' }, active: true }] },
                phone: { title: 'Buyer’s Phone · Bidder 142', items: [{ type: 'invoice', label: 'Lot 214 · Georgian silver candlesticks', amount: '£2,232.00', paid: { amount: '£2,232.00', time: '14:41' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-3471', sub: 'Matched to lot · funds settle to Camber & Finch', badge: { label: 'Released', tone: 'matched' } }], feed: 'Every payment matched to its lot automatically — no settlement spreadsheet.' },
              },
            ],
          },
          {
            id: 'lot198', tab: 'Needed a nudge', customer: 'Bidder 097 · Lot 198', blurb: 'Pays after an automatic reminder',
            steps: [
              {
                caption: 'Lot 198 sold, but two days on the invoice is still open — in a 400-lot sale, this is where chasing slips through the cracks.',
                system: { rows: [{ ref: 'Lot 198', who: 'Pair of famille rose vases · Bidder 097', amount: '£3,410', badge: { label: 'Invoiced', tone: 'sent' }, active: true }] },
                phone: { title: 'Buyer’s Phone · Bidder 097', items: [{ type: 'sms', text: 'Camber & Finch: your invoice for Lot 198 (£3,410.00) is ready — pay at pay.camberfinch.co.uk/i/3468', time: 'Mon 16:10' }] },
                ops: { rows: [{ ref: 'INV-3468', sub: 'Due · still open after 2 days', badge: { label: 'Due', tone: 'due' }, active: true }] },
              },
              {
                caption: 'A polite reminder sends itself — no one had to comb the unpaid list.',
                system: { rows: [{ ref: 'Lot 198', who: 'Pair of famille rose vases · Bidder 097', amount: '£3,410', badge: { label: 'Invoiced', tone: 'sent' } }] },
                phone: { title: 'Buyer’s Phone · Bidder 097', items: [{ type: 'sms', text: 'Camber & Finch: a gentle reminder — your invoice for Lot 198 (£3,410.00) is still open. Pay any time at pay.camberfinch.co.uk/i/3468', time: '09:00 · day 3' }] },
                ops: { rows: [{ ref: 'INV-3468', sub: 'Day-3 reminder sent 09:00 — automatically', badge: { label: 'Day 3', tone: 'remind' }, active: true }] },
              },
              {
                caption: 'The bidder pays £3,410 — the nudge did the asking, not a member of staff.',
                system: { rows: [{ ref: 'Lot 198', who: 'Pair of famille rose vases · Bidder 097', amount: '£3,410', badge: { label: 'Invoiced', tone: 'sent' } }] },
                phone: { title: 'Buyer’s Phone · Bidder 097', items: [{ type: 'invoice', label: 'Lot 198 · pair of famille rose vases', amount: '£3,410.00', paid: { amount: '£3,410.00', time: 'day 3 · 09:22' } }] },
                ops: { rows: [{ ref: 'INV-3468', sub: 'Paid · matching to lot…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Matched and marked ready to release automatically — and off the chase list for good.',
                system: { rows: [{ ref: 'Lot 198', who: 'Famille rose vases · Bidder 097', amount: '£3,410.00', badge: { label: 'Ready to release', tone: 'paid' }, active: true }] },
                phone: { title: 'Buyer’s Phone · Bidder 097', items: [{ type: 'invoice', label: 'Lot 198 · pair of famille rose vases', amount: '£3,410.00', paid: { amount: '£3,410.00', time: 'day 3 · 09:22' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-3468', sub: 'Matched to lot · ready to release', badge: { label: 'Released', tone: 'matched' } }], feed: 'The unpaid invoices chase themselves — the settlement board does the watching.' },
              },
            ],
          },
          {
            id: 'lot176', tab: 'Paid by bank transfer', customer: 'Bidder 061 · Lot 176', blurb: 'Trade buyer, matched by reference',
            steps: [
              {
                caption: 'Trade buyers often settle a larger lot by bank transfer — which used to mean matching a payment to a lot by hand.',
                system: { rows: [{ ref: 'Lot 176', who: 'Victorian mahogany bookcase · Bidder 061', amount: '£1,150', badge: { label: 'Invoiced', tone: 'sent' }, active: true }] },
                phone: { title: 'Buyer’s Phone · Bidder 061', items: [{ type: 'sms', text: 'Camber & Finch: your invoice for Lot 176 (£1,150.00) is ready — pay by card or bank transfer at pay.camberfinch.co.uk/i/3462', time: '15:20' }] },
                ops: { sync: true, rows: [{ ref: 'INV-3462', sub: 'Link sent · card or transfer', badge: { label: 'Sent', tone: 'due' }, active: true }] },
              },
              {
                caption: 'The branded page carries a unique reference, so even a transfer can find its own lot.',
                system: { rows: [{ ref: 'Lot 176', who: 'Victorian mahogany bookcase · Bidder 061', amount: '£1,150', badge: { label: 'Invoiced', tone: 'sent' } }] },
                phone: { title: 'Buyer’s Phone · Bidder 061', items: [{ type: 'invoice', label: 'Lot 176 · Victorian mahogany bookcase', amount: '£1,150.00', note: 'Bank transfer · reference CF-3462', cta: 'transfer' }] },
                ops: { rows: [{ ref: 'INV-3462', sub: 'Awaiting transfer · reference CF-3462', badge: { label: 'Due', tone: 'due' }, active: true }] },
              },
              {
                caption: 'The transfer lands — £1,150 — and the reference carries the lot number home.',
                system: { rows: [{ ref: 'Lot 176', who: 'Victorian mahogany bookcase · Bidder 061', amount: '£1,150', badge: { label: 'Invoiced', tone: 'sent' } }] },
                phone: { title: 'Buyer’s Phone · Bidder 061', items: [{ type: 'invoice', label: 'Lot 176 · Victorian mahogany bookcase', amount: '£1,150.00', note: 'Bank transfer · reference CF-3462', paid: { amount: '£1,150.00', time: 'transfer received' } }] },
                ops: { rows: [{ ref: 'INV-3462', sub: 'Transfer received · matching reference…', badge: { label: 'Paid', tone: 'paid' }, active: true }] },
              },
              {
                caption: 'Matched to the lot automatically — no bank feed to eyeball, even for a transfer.',
                system: { rows: [{ ref: 'Lot 176', who: 'Victorian mahogany bookcase · Bidder 061', amount: '£1,150.00', badge: { label: 'Ready to release', tone: 'paid' }, active: true }] },
                phone: { title: 'Buyer’s Phone · Bidder 061', items: [{ type: 'invoice', label: 'Lot 176 · Victorian mahogany bookcase', amount: '£1,150.00', note: 'Bank transfer · reference CF-3462', paid: { amount: '£1,150.00', time: 'transfer received' } }] },
                ops: { sync: true, rows: [{ ref: 'INV-3462', sub: 'Matched by reference · ready to release', badge: { label: 'Matched', tone: 'matched' } }], feed: 'Even bank transfers reconcile themselves when the reference does the work.' },
              },
            ],
          },
        ],
      },
      theatre: {
        intro: "The hammer has just fallen on Lot 214. Press play to follow it from sold to settled.",
        panes: [
          { key: 'saleroom', label: 'Saleroom System', sync: 'Lot records' },
          { key: 'buyer', label: "Buyer's Phone", tag: 'Simulated', idle: 'No message yet' },
          { key: 'ops', label: 'SettlePay · Settlement', sync: 'Auto-match' },
        ],
        steps: [
          {
            caption: "Lot 214 sells. The invoice is raised automatically — hammer price plus the 24% buyer's premium.",
            active: 'saleroom',
            rows: {
              saleroom: [{ ref: 'Lot 214', who: 'Pair of Georgian silver candlesticks', sub: 'Hammer £1,800 + premium', status: 'due', label: 'Sold' }],
              buyer: [],
              ops: [{ ref: 'INV-3471', who: 'Bidder 142', sub: 'Invoice raised · £2,232.00', status: 'due', label: 'New' }],
            },
          },
          {
            caption: "A branded pay-by-link goes to the winning bidder automatically — no invoice to post, no card read down the phone.",
            active: 'buyer',
            rows: {
              saleroom: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks', sub: 'Awaiting payment', status: 'due', label: 'Invoiced' }],
              buyer: [{ ref: 'INV-3471', who: 'Pay your invoice', sub: '£2,232.00 · card or transfer', status: 'due', label: 'Link sent' }],
              ops: [{ ref: 'INV-3471', who: 'Bidder 142', sub: 'Branded link sent', status: 'due', label: 'Awaiting' }],
            },
          },
          {
            caption: "The buyer pays by card in a tap — from anywhere in the world, no slow international transfer.",
            active: 'buyer',
            rows: {
              saleroom: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks', sub: 'Payment received', status: 'paid', label: 'Paid' }],
              buyer: [{ ref: 'INV-3471', who: 'Paid £2,232.00', sub: 'Card · receipt emailed', status: 'paid', label: 'Paid' }],
              ops: [{ ref: 'INV-3471', who: 'Bidder 142', sub: 'Payment received · matching lot…', status: 'paid', label: 'Paid' }],
            },
          },
          {
            caption: "Matched to the bidder and the lot automatically — the saleroom system marks it ready to release, with no hand-reconciliation.",
            active: 'ops',
            rows: {
              saleroom: [{ ref: 'Lot 214', who: 'Georgian silver candlesticks', sub: 'Matched to Bidder 142 · ready to release', status: 'paid', label: 'Ready' }],
              buyer: [{ ref: 'INV-3471', who: 'Paid £2,232.00', sub: 'Collection details emailed', status: 'paid', label: 'Paid' }],
              ops: [{ ref: 'INV-3471', who: 'Bidder 142', sub: 'Matched to lot · funds settle to Camber & Finch', status: 'paid', label: 'Matched' }],
            },
          },
          {
            caption: "And the unpaid invoices chase themselves. The settlement board shows the whole sale at a glance — no spreadsheet, no marathon.",
            active: 'ops',
            rows: {
              saleroom: [{ ref: 'Sale 0616', who: 'Spring Fine Art & Antiques', sub: '316 of 412 invoices settled', status: 'paid', label: 'Live' }],
              buyer: [{ ref: 'INV-3468', who: 'Payment reminder', sub: 'A gentle nudge · still time to pay', status: 'reminder', label: 'Reminded' }],
              ops: [
                { ref: 'INV-3471', who: 'Bidder 142', sub: 'Settled · ready to release', status: 'paid', label: 'Settled' },
                { ref: 'INV-3468', who: 'Bidder 097', sub: 'Reminder sent automatically · day 3', status: 'reminder', label: 'Nudged' },
              ],
            },
          },
        ],
      },
      ops: {
        url: 'app.settlepay.uk/camber-finch',
        title: 'Settlement Board',
        subtitle: 'Camber & Finch · Sale 0616',
        sync: 'Connected to saleroom',
        rows: [
          { ref: 'INV-3471', who: 'Bidder 142 — Lot 214', amount: '£2,232.00', status: 'paid', label: 'Released' },
          { ref: 'INV-3470', who: 'Bidder 138 — Lots 207, 209', amount: '£940.00', status: 'paid', label: 'Paid' },
          { ref: 'INV-3468', who: 'Bidder 097 — Lot 198', amount: '£3,410.00', status: 'reminder', label: 'Day 3' },
          { ref: 'INV-3462', who: 'Bidder 061 — Lot 176', amount: '£1,150.00', status: 'overdue', label: 'Day 7' },
        ],
        feed: 'This sale: 316 of 412 invoices settled, every payment matched to its lot automatically.',
      },
      outcome: {
        stats: [
          {
            value: 'Days → hours',
            label: 'Post-sale reconciliation',
            sub: 'The week-long matching marathon becomes a settlement board that has already matched each payment to its lot.',
          },
          {
            value: 'Card, worldwide',
            label: 'Overseas buyers pay instantly',
            sub: 'A tap on a branded link replaces slow international transfers with mangled references — lots clear and ship sooner.',
          },
          {
            value: '0 by phone',
            label: 'Card numbers taken on the line',
            sub: 'The saleroom office leaves the riskiest category of UK card fraud behind, and the phone line leaves PCI scope.',
          },
        ],
        basis: [
          'A modelled fine-art auctioneer running ~20 sales a year with several hundred paying buyers each — illustrative volumes, not a real client.',
          'Remote purchase (card-not-present) fraud: just under £400 million lost in 2024, the largest category of UK card fraud — UK Finance Annual Fraud Report 2025. A hosted page also keeps card data out of the saleroom, with PCI handled by the processor.',
          'No published figure exists for auction-house reconciliation time, so the post-sale admin saving is stated as a modelled assumption, not a measured result.',
        ],
      },
      roi: {
        period: 'year',
        volumeLabel: 'Buyer invoices a year',
        minutesLabel: 'Minutes matching & chasing each one today',
        rateLabel: 'Your admin hourly rate',
        volume: { default: 8000, min: 500, max: 16000, step: 250 },
        minutes: { default: 4, min: 1, max: 15, step: 1 },
        rate: { default: 14, min: 11, max: 25, step: 1 },
        lens: 'And lots clear faster: overseas buyers pay by card the moment the sale ends, so items can be released and shipped without waiting days for a transfer to arrive and be matched.',
      },
    },
  },
];
