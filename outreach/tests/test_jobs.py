import pytest

from outreach import db, jobs

pytestmark = pytest.mark.floor_h


@jobs.task(
    "test_jobs_ok", "Test OK task",
    params=(
        jobs.Param("n", "Count", "int", default=1),
        jobs.Param("label", "Label", "str", default="x"),
    ),
)
def _ok(ctx, n=1, label="x"):
    ctx.log("starting")
    for i in range(n):
        ctx.progress(i + 1, n)
    ctx.log("done")
    return {"n": n, "label": label}


@jobs.task("test_jobs_boom", "Test failing task")
def _boom(ctx):
    raise RuntimeError("boom")


@jobs.task("test_jobs_chatty", "Test log-cap task")
def _chatty(ctx):
    for i in range(250):
        ctx.log(f"line {i}")


@jobs.task("test_jobs_selfcancel", "Test cooperative cancel")
def _selfcancel(ctx):
    jobs.cancel(ctx.job_id)
    assert ctx.cancelled()
    return {"stopped": True}


_COERCE_SPEC = jobs.TaskSpec(
    "test_jobs_coerce", "Coerce fixture", "",
    (
        jobs.Param("s", "S", "str", required=True),
        jobs.Param("i", "I", "int", default=3),
        jobs.Param("b", "B", "bool", default=False),
    ),
    lambda ctx: None,
)


@pytest.fixture(autouse=True)
def _clean_test_jobs():
    yield
    with db.cursor() as cur:
        cur.execute(r"delete from outreach.jobs where kind like 'test\_jobs\_%'")


def test_registry_and_decorator():
    spec = jobs.REGISTRY["test_jobs_ok"]
    assert spec.title == "Test OK task"
    assert spec.group == "pipeline" and spec.destructive is False
    assert spec.params[0].kind == "int"
    assert spec.handler is _ok


def test_coerce_params_casts_types():
    got = jobs.coerce_params(_COERCE_SPEC, {"s": "hello", "i": "5", "b": "yes"})
    assert got == {"s": "hello", "i": 5, "b": True}


def test_coerce_params_applies_defaults():
    assert jobs.coerce_params(_COERCE_SPEC, {"s": "hi"}) == {"s": "hi", "i": 3, "b": False}


def test_coerce_params_bool_falsey_string():
    assert jobs.coerce_params(_COERCE_SPEC, {"s": "x", "b": "no"})["b"] is False


def test_coerce_params_missing_required():
    with pytest.raises(ValueError):
        jobs.coerce_params(_COERCE_SPEC, {"i": 2})


def test_enqueue_unknown_kind():
    with pytest.raises(ValueError):
        jobs.enqueue("test_jobs_never_registered")


def test_enqueue_and_dedupe(db_rollback):
    cur = db_rollback.cursor()
    id1 = jobs.enqueue("test_jobs_ok", {"n": 2}, requested_by="unit-test", cur=cur)
    assert jobs.enqueue("test_jobs_ok", dedupe=True, cur=cur) == id1
    id3 = jobs.enqueue("test_jobs_ok", cur=cur)
    assert id3 != id1
    cur.execute(
        "select kind, status, params, requested_by from outreach.jobs where id = %s",
        (id1,),
    )
    assert cur.fetchone() == ("test_jobs_ok", "queued", {"n": 2}, "unit-test")


def test_run_job_inline_success():
    row = jobs.run_job_inline("test_jobs_ok", {"n": "3", "label": "abc"})
    assert row["status"] == "succeeded"
    assert row["result"] == {"n": 3, "label": "abc"}
    assert row["progress"]["done"] == 3 and row["progress"]["total"] == 3
    assert [e["msg"] for e in row["progress"]["log"]] == ["starting", "done"]
    assert all("t" in e for e in row["progress"]["log"])
    assert row["started_at"] is not None and row["finished_at"] is not None


def test_run_job_inline_failure():
    row = jobs.run_job_inline("test_jobs_boom")
    assert row["status"] == "failed"
    assert "RuntimeError: boom" in row["error"]
    assert row["result"] is None


def test_cancel_queued_job_and_runner_skips_it():
    job_id = jobs.enqueue("test_jobs_ok", {"n": 1})
    assert jobs.cancel(job_id) is True
    assert jobs.cancel(job_id) is False
    assert jobs._claim(job_id) is None
    with db.dict_cursor() as cur:
        cur.execute("select status, finished_at from outreach.jobs where id = %s", (job_id,))
        row = cur.fetchone()
    assert row["status"] == "cancelled" and row["finished_at"] is not None


def test_mid_run_cancel_leaves_cancelled():
    row = jobs.run_job_inline("test_jobs_selfcancel")
    assert row["status"] == "cancelled"
    assert row["result"] is None


def test_recover_stale_flips_running_row(db_rollback):
    cur = db_rollback.cursor()
    cur.execute(
        "insert into outreach.jobs (kind, status, started_at) "
        "values ('test_jobs_ok', 'running', now()) returning id"
    )
    job_id = cur.fetchone()[0]
    assert jobs.recover_stale(cur=cur) >= 1
    cur.execute("select status, error from outreach.jobs where id = %s", (job_id,))
    assert cur.fetchone() == ("failed", "instance restarted")


def test_log_cap_keeps_newest_200():
    row = jobs.run_job_inline("test_jobs_chatty")
    assert row["status"] == "succeeded"
    assert row["result"] == {}
    log = row["progress"]["log"]
    assert len(log) == 200
    assert log[0]["msg"] == "line 50"
    assert log[-1]["msg"] == "line 249"
