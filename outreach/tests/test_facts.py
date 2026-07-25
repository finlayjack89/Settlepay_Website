"""The drafting FACTS block — resolved constants with provenance.

The rules encoded here all trace to drafts that actually went into the database: a
greeting naming someone who was never on file, and a business placed in its
registered-office town. The block exists so those are structurally impossible rather
than merely discouraged.
"""
import json

import pytest

from outreach import facts

pytestmark = pytest.mark.floor_e


def test_a_resolved_fact_carries_its_value_source_and_verification():
    block = facts.build(company_name="Acme Joinery", company_name_source="companies_house")
    assert block["company_name"].value == "Acme Joinery"
    assert block["company_name"].source == "companies_house"
    assert block["company_name"].verified is True


def test_an_unknown_is_present_and_explicit_never_absent():
    """The whole point: the drafter is TOLD there is no location, rather than being left
    a gap it fills with something plausible."""
    block = facts.build(company_name="Acme Joinery")
    assert "location" in block
    assert block["location"].value is None
    assert block["location"].verified is False
    assert not block["location"]                      # falsy, so `if fact:` reads naturally


def test_a_registered_office_location_is_dropped_not_merely_unverified():
    """A value that exists is a value a prompt can leak, so an inadmissible location is
    removed outright rather than carried with verified=False."""
    block = facts.build(company_name="Mews Auction Rooms", location="Westbury-On-Severn",
                        location_source="companies_house")
    assert block["location"].value is None
    assert block["location"].source is None


@pytest.mark.parametrize("source", ["places_listing", "own_site", "platform_listing"])
def test_a_trading_location_is_admissible(source):
    block = facts.build(company_name="24hr Electrical", location="Hull",
                        location_source=source)
    assert block["location"].value == "Hull" and block["location"].verified


def test_blank_and_whitespace_values_resolve_to_unknown():
    block = facts.build(company_name="Acme", contact_name="   ", location="",
                        location_source="places_listing")
    assert block["contact_name"].value is None and block["location"].value is None


# --------------------------------------------------------------------------- #
#  Round-trip through the database column
# --------------------------------------------------------------------------- #
def test_round_trips_through_jsonb():
    block = facts.build(company_name="Adam Partridge Auctioneers",
                        contact_name="Robert", contact_name_source="ch_officer",
                        location="Macclesfield", location_source="places_listing")
    back = facts.loads(json.loads(facts.dumps(block)))
    assert back["company_name"].value == "Adam Partridge Auctioneers"
    assert back["contact_name"].value == "Robert"
    assert back["location"].value == "Macclesfield" and back["location"].verified


@pytest.mark.parametrize("raw", [None, "", "not json", 123, [], {"company_name": None}])
def test_a_malformed_block_degrades_to_unknowns_rather_than_raising(raw):
    """A bad facts blob must never take down the drafting loop — it must simply mean
    'we know nothing', which the readiness gate then refuses."""
    block = facts.loads(raw)
    assert set(block) == set(facts.FIELDS)
    assert all(f.value is None for f in block.values())
    assert not facts.is_draftable(block)


def test_a_bare_string_is_accepted_but_never_counted_as_verified():
    block = facts.loads({"company_name": "Acme Joinery"})
    assert block["company_name"].value == "Acme Joinery"
    assert block["company_name"].verified is False


def test_a_value_null_but_verified_true_blob_cannot_claim_verification():
    block = facts.loads({"location": {"value": None, "verified": True}})
    assert block["location"].verified is False


# --------------------------------------------------------------------------- #
#  The readiness gate — what forces enrichment to do its job
# --------------------------------------------------------------------------- #
def test_a_lead_without_a_company_name_is_not_draftable():
    assert not facts.is_draftable(facts.build(company_name=None))
    assert facts.missing_required(facts.build(company_name=None)) == ["company_name"]


def test_known_unknowns_do_not_block_drafting():
    """Resolved, not complete: a block whose optional fields are established-unknown is
    finished — the drafter writes around them."""
    assert facts.is_draftable(facts.build(company_name="Acme Joinery"))


def test_no_facts_at_all_is_not_draftable():
    assert not facts.is_draftable(None)
    assert not facts.is_draftable({})


# --------------------------------------------------------------------------- #
#  The drafter's view
# --------------------------------------------------------------------------- #
def test_the_prompt_block_states_unknowns_outright():
    """Omitting a field reads as 'not mentioned' and the model supplies its own; naming
    it UNKNOWN is an instruction it can follow."""
    text = facts.as_prompt_block(facts.build(company_name="Acme Joinery"))
    assert "company_name: Acme Joinery" in text
    assert "location: UNKNOWN" in text and "do not state one" in text


def test_allowed_tokens_are_every_word_of_every_resolved_fact():
    block = facts.build(company_name="Adam Partridge Auctioneers",
                        location="Macclesfield", location_source="places_listing")
    tokens = facts.allowed_tokens(block)
    assert {"adam", "partridge", "auctioneers", "macclesfield"} <= tokens
    assert "john" not in tokens


def test_allowed_tokens_exclude_unknown_fields():
    block = facts.build(company_name="Acme Joinery", location="Hull",
                        location_source="companies_house")   # unchecked -> dropped
    assert "hull" not in facts.allowed_tokens(block)


def test_summarise_records_provenance_for_the_audit_trail():
    block = facts.build(company_name="Acme Joinery", location="Hull",
                        location_source="places_listing")
    line = facts.summarise(block)
    assert "companies_house" in line and "places_listing" in line
    assert "contact_name=-" in line          # unknowns are visible in the record too


def test_an_unchecked_registered_office_is_still_inadmissible():
    """The shared-office check earns a distinct label. A bare 'companies_house' — an
    address nobody verified — must stay rejected even though a CHECKED one is allowed,
    so a careless caller cannot bypass geo.registered_office_shared()."""
    unchecked = facts.build(company_name="Acme", location="Chester",
                            location_source="companies_house")
    assert unchecked["location"].value is None

    checked = facts.build(company_name="Acme", location="Macclesfield",
                          location_source="companies_house_confirmed")
    assert checked["location"].value == "Macclesfield"


def test_region_is_admissible_from_any_source():
    """A broad geography stays true even when the precise town does not — an accountant
    is nearly always in the same region as the client."""
    block = facts.build(company_name="Acme", location="Chester",
                        location_source="companies_house",      # dropped
                        region="North West", region_source="postcodes_io")
    assert block["location"].value is None
    assert block["region"].value == "North West"
