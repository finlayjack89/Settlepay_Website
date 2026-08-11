# Legitimate Interests Assessment — naming a decision maker in cold B2B outreach

**Controller:** Finlay Salisbury, trading as SettlePay (sole trader)
**Processing assessed:** identifying the person who runs a UK corporate prospect, and
addressing one introductory business email to them.
**Version:** 1.0 · **Date:** 26 July 2026 · **Review:** every 12 months, or on any change
to the sourcing or sending logic.
**Status:** DRAFT — practitioner-level, written by the controller. Not legal advice.
Given the PECR cap rose to £17.5m on 5 February 2026, this should be reviewed by a
data-protection solicitor before `DECISION_MAKER_ENABLED` is turned on.

> Why this document exists at all: UK GDPR art. 6(1)(f) requires the balancing test to be
> **carried out and recorded before** the processing starts, not reconstructed afterwards.
> The pipeline already stamps `lawful_basis = legitimate_interests` on every officer row
> via `audit.record`; until this file existed, that stamp pointed at an assessment nobody
> had made.

---

## 1. Purpose test — is there a legitimate interest?

**The interest.** SettlePay builds bespoke, branded payment pages for small UK businesses.
To find clients it needs to introduce itself to businesses that plausibly need one. Direct
B2B marketing is expressly recognised as capable of being a legitimate interest
(UK GDPR recital 47).

**Whose interest.** The controller's (finding clients) and, in part, the recipient's — the
message is only sent to businesses whose payment context suggests the product is relevant
(`payment_context = invoice_remote`; fixed-till retail and online-only e-commerce are
disqualified in `targeting.py`).

**Why a NAMED person rather than the company inbox.** Two reasons, and only the second
requires personal data:
1. A decision maker reads and answers; a shared inbox is triaged.
2. Addressing a person by name lets the message be specific and lets them opt out for
   themselves.

**Is it lawful, ethical, sensible?** The message is a single, identified, honest business
introduction with a working opt-out. It makes no claim SettlePay cannot support, offers no
inducement, and creates no urgency. It is not covert, not deceptive and not at scale
(≤50/day/mailbox, a ceiling chosen for complaint-rate reasons, not legal ones).

**If we did not do it:** SettlePay would market only to `info@` mailboxes, which measurably
attract 2–4× the spam-complaint rate — worse for recipients as well as for us.

---

## 2. Necessity test — is this processing necessary for that purpose?

**Yes for the name; no for anything else.** That distinction is enforced in code, not
policy:

| Data available on the public register | Stored? | Why |
|---|---|---|
| Officer name | **Yes** | The purpose is to address a person; without it there is nothing to assess |
| Officer role / occupation | **Yes** | Establishes the *role relevance* the ICO requires for LI in B2B |
| Whether they are a PSC | **Yes — as a BOOLEAN** | Identifies the owner-operator. The *degree* of control is not needed |
| Nature/percentage of control | **No** | Answers "how much do they own" — not a question we need |
| Date of birth (partial) | **No** | No purpose |
| Correspondence / service address | **No** | No purpose; we never post |
| Nationality, country of residence | **No** | No purpose |
| Telephone number | **No — never, from any source** | Standing rule across the whole pipeline |

Enforced by `migrations/0011` and `0016` (the columns do not exist) and asserted by
`test_store_officers_does_not_persist_dob_or_address` and
`test_store_officers_does_not_persist_psc_ownership_detail`.

**Could the purpose be achieved less intrusively?** Partly, and where it can be, it is:

- **The FAO tier is preferred wherever it works.** If we hold a shared mailbox, we address
  it *"FAO John Smith, Director"* rather than obtaining or inferring his personal address.
  On a 20-lead sample of the live corpus this covered **18 of 20** leads. This is the less
  intrusive route and it is the default, not the fallback.
- **A published address beats an inferred one.** `sourced_address()` is tried before any
  derivation: if the business published a personal address, we use the one they chose to
  publish.
- **Derivation is pattern-confirmed only.** We infer an address only where a personal
  address *published on that same domain* proves the convention, and we send only if a
  verifier confirms the mailbox exists. Blind permutation of four guesses per person was
  removed precisely because it is speculative rather than necessary. On the same 20-lead
  sample this produced **0** derivations and therefore **0** verifier spend.

**Proportionality of volume.** One introductory email, plus at most one follow-up. Both are
held to the same grounding checks. No sequence beyond touch 2.

---

## 3. Balancing test — do their interests override ours?

### 3.1 What is their reasonable expectation?

A company director's name and role are on a **public register they are legally required to
file**, and the ICO has confirmed PECR/UK GDPR still apply to data sourced from public
sources. So publication does not equal consent — but it does mean the *existence* of the
name is not private, and a business-role message to a business is broadly within
expectation for an incorporated company.

**Where expectation is weakest:** a director who has never published a personal work
address would not expect us to work one out. That is exactly the case the
pattern-confirmed rule refuses.

### 3.2 Nature of the data

Business-role data about a person acting in a professional capacity. **No special category
data.** No financial, health, or criminal-offence data. No profiling that produces legal or
similarly significant effects (`web.py` / no automated decision-making about the person —
the ICP verdict is about the *business*).

### 3.3 Possible impacts

| Impact | Mitigation in code |
|---|---|
| Unwanted email | One touch + one follow-up; opt-out honoured permanently via `suppressions`, checked before **every** send |
| Message to the wrong person | Officers ranked so the *owner-operator* is chosen (PSC + eponym + occupation); the recipient guard rejects a domain that is not the company's |
| Their name used wrongly in the copy | `check_grounding` rejects any FAO line or greeting whose name is not the resolved `contact_name` constant; roles likewise |
| Address does not exist → bounce | Only verifier-confirmed addresses are ever adopted |
| They cannot tell where we got their details | Art. 14 note in the footer of every named send (`emailfmt.NAMED_FOOTER_NOTE`) linking the privacy notice section "Information We Collect From Public Sources" |
| They want it deleted | Suppression + erasure route in the privacy notice; suppression records retained indefinitely *precisely so the objection is permanent* |

### 3.4 Safeguards beyond the minimum

- **Corporate subscribers only.** Sole traders, unincorporated partnerships and individuals
  are never cold-emailed (PECR). Enforced by `crossref.py`, fail-closed.
- **Retention:** outreach records deleted at 12 months from collection or last meaningful
  contact.
- **Data minimisation** as tabled in §2, enforced structurally.
- **No phone numbers, ever**, from any source.
- **Human review** of every draft before it can be sent; `G_SEND` is a human-only gate the
  system cannot set for itself.
- **Provenance recorded per address** (`contact_method` = `sourced` | `derived`), so a
  subject-access or regulator question can be answered per person rather than per pipeline.

### 3.5 Outcome

**The legitimate interest is not overridden**, on the conditions that the safeguards above
remain in force — in particular corporate-only, the FAO-first preference, verifier
confirmation, the art. 14 footer, and honouring objections permanently.

**Two conditions this assessment does NOT clear:**

1. **Blind derivation.** Guessing a personal address without a domain-confirmed pattern is
   assessed as **failing the necessity test**. It is removed from the code, and this
   assessment does not cover reinstating it.
2. **Companies House terms of use.** There is credible commentary that CH's own terms
   prohibit using register data for unsolicited marketing. That is a **contractual**
   question, separate from data-protection law, and it is **unresolved**. It should be put
   to the solicitor alongside this assessment. If it holds, §2's officer sourcing must be
   reconsidered — though the FAO tier's value (knowing who runs a business, for the CRM and
   for the copy) is not solely dependent on it.

---

## 4. Record

| | |
|---|---|
| Lawful basis relied on | UK GDPR art. 6(1)(f) — legitimate interests |
| PECR basis for the send | Corporate subscriber (reg. 22 consent rule does not apply) |
| Art. 14 disclosure | Privacy notice §"Information We Collect From Public Sources" + named-send footer |
| Right to object | Art. 21 — "reply unsubscribe", honoured permanently |
| Assessment carried out by | Finlay Salisbury (controller) |
| Referenced by | `audit.record(..., lawful_basis=LEGITIMATE_INTERESTS)` |

**Changes that require this to be redone:** enabling derivation beyond a confirmed pattern ·
sending more than two touches · adding a new personal-data source · targeting
non-corporate subscribers · storing any field removed in §2.
