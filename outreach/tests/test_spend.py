import pytest

from outreach import config, spend

pytestmark = pytest.mark.floor_h


def test_record_inserts_row_and_month_total_sums(db_rollback):
    cur = db_rollback.cursor()
    base = spend.month_total_gbp(cur=cur)
    spend.record(
        "anthropic",
        purpose="unit-test",
        model="claude-sonnet-4-6",
        units_in=1000,
        units_out=500,
        cost_gbp=0.75,
        detail={"k": "v"},
        company_number="TESTCO_SPEND_0001",
        cur=cur,
    )
    spend.record("millionverifier", purpose="unit-test", cost_gbp=0.25, cur=cur)
    cur.execute(
        "select provider, purpose, model, units_in, units_out, cost_gbp "
        "from outreach.spend where company_number = %s",
        ("TESTCO_SPEND_0001",),
    )
    row = cur.fetchone()
    assert row[:5] == ("anthropic", "unit-test", "claude-sonnet-4-6", 1000, 500)
    assert float(row[5]) == pytest.approx(0.75)
    assert spend.month_total_gbp(cur=cur) == pytest.approx(base + 1.0)
    # db_rollback fixture rolls back -> no pollution of the live DB


def test_ensure_under_cap_passes_then_raises(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    monkeypatch.setattr(
        config, "MONTHLY_SPEND_CAP_GBP", spend.month_total_gbp(cur=cur) + 100.0)
    spend.ensure_under_cap(cur=cur)  # under cap: no raise
    spend.record("anthropic", purpose="unit-test cap breach", cost_gbp=0.02, cur=cur)
    monkeypatch.setattr(config, "MONTHLY_SPEND_CAP_GBP", 0.01)
    with pytest.raises(spend.SpendCapExceeded) as exc:
        spend.ensure_under_cap(cur=cur)
    assert "0.01" in str(exc.value)


def test_cap_zero_or_negative_disables_gate(db_rollback, monkeypatch):
    cur = db_rollback.cursor()
    spend.record("anthropic", purpose="unit-test cap disabled", cost_gbp=5.0, cur=cur)
    for cap in (0.0, -1.0):
        monkeypatch.setattr(config, "MONTHLY_SPEND_CAP_GBP", cap)
        spend.ensure_under_cap(cur=cur)  # disabled: no raise


def test_anthropic_cost_gbp_arithmetic(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_INPUT_USD_PER_MTOK", 3.0)
    monkeypatch.setattr(config, "ANTHROPIC_OUTPUT_USD_PER_MTOK", 15.0)
    monkeypatch.setattr(config, "USD_TO_GBP", 0.79)
    assert spend.anthropic_cost_gbp(0, 0) == 0.0
    assert spend.anthropic_cost_gbp(1_000_000, 0) == pytest.approx(3.0 * 0.79)
    assert spend.anthropic_cost_gbp(0, 1_000_000) == pytest.approx(15.0 * 0.79)
    assert spend.anthropic_cost_gbp(250_000, 100_000) == pytest.approx(
        (0.25 * 3.0 + 0.1 * 15.0) * 0.79)
