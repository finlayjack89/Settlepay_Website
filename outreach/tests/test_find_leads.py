import pytest

from outreach import find_leads
from outreach.companies_house import RateLimiter, RateLimitExceeded

pytestmark = pytest.mark.floor_b


# ---- rate-limit guard (no network) ----
def test_rate_limit_cap_enforced():
    rl = RateLimiter(max_requests=2, min_interval=0)
    rl.acquire()
    rl.acquire()
    with pytest.raises(RateLimitExceeded):
        rl.acquire()


def test_rate_limit_min_interval_waits(monkeypatch):
    sleeps = []
    monkeypatch.setattr("outreach.companies_house.time.sleep", lambda s: sleeps.append(s))
    # fake monotonic so the 2nd acquire sees ~0 elapsed -> must wait ~min_interval
    monkeypatch.setattr("outreach.companies_house.time.monotonic", lambda: 0.0)
    rl = RateLimiter(max_requests=5, min_interval=0.6)
    rl.acquire()
    rl.acquire()
    assert sleeps and sleeps[-1] > 0  # enforced a wait between calls


# ---- dedupe (no network, no DB; dry_run) ----
class _FakeCH:
    def __init__(self, items):
        self._items = items

    def iter_companies(self, *, target, **kwargs):
        for it in self._items[:target]:
            yield it

    def close(self):
        pass


def test_dedupe_and_valid_fields():
    items = [
        {"company_number": "1", "company_name": "Alpha Dental"},
        {"company_number": "1", "company_name": "Alpha Dental (dup)"},
        {"company_number": "2", "company_name": "Bravo Plumbing"},
        {"company_number": None, "company_name": "No Number Ltd"},   # invalid: no number
        {"company_number": "3", "company_name": None},               # invalid: no name
    ]
    res = find_leads.run(target=10, client=_FakeCH(items), dry_run=True)
    assert res["would_insert"] == 2  # only unique, fully-keyed rows


def test_excludes_shell_named_companies():
    items = [
        {"company_number": "1", "company_name": "Smiles Dental Care"},        # keep
        {"company_number": "2", "company_name": "Acme Property Holdings"},    # shell
        {"company_number": "3", "company_name": "Riverside Investments Ltd"}, # shell
        {"company_number": "4", "company_name": "Northgate Plumbing"},        # keep
        {"company_number": "5", "company_name": "Project Bidco Limited"},     # shell
    ]
    res = find_leads.run(target=10, client=_FakeCH(items), dry_run=True)
    assert res["would_insert"] == 2
    assert res["excluded_shells"] == 3
