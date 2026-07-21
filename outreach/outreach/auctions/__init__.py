"""Auction-platform lead source.

Turns public auction-platform listings (Easy Live Auction first; the-saleroom,
BidSpotter, i-bidder to follow) into enriched, scored SettlePay leads. The wedge:
these platforms run the *bidding* only — the auctioneer still invoices and collects
payment itself, usually by bank transfer or a manual card link. So every auctioneer
listed is a pre-qualified business with exactly SettlePay's pain.

Design: a thin discovery front-end (a `Source` per platform) produces raw records;
enrichment REUSES the outreach pipeline's primitives (Companies House cross-reference,
website resolve + scrape, decision-maker officers + email verification, the ICP-fit
gate) rather than re-implementing them. Output is a scored CSV + JSON list with a
per-lead email brief, and an optional hand-off into the DB drafting stage.

Compliance is inherited from the pipeline: PECR corporate-vs-individual gate, no phones
ever persisted, and the full art. 14 / art. 21 regime for any named-individual email.
"""
