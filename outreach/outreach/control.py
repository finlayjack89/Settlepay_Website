"""Runtime operational controls — the knobs, and who is allowed to turn them.

Every gate in this pipeline lived in an environment variable, which means changing one
required a Cloud Run revision. That is the reason the pipeline sat idle for a fortnight:
the single action that would have restarted it — switching stages on — could not be taken
from the console at all, only by someone with gcloud credentials at a terminal.

This module makes those knobs settable at runtime without weakening any of them.

**How it works.** Every `config.X` in this package is an attribute read at CALL time —
there is not one `from .config import X` anywhere, which the test suite already relies on
(`monkeypatch.setattr(run_mod.config, "AUTONOMOUS_STAGES_ENABLED", ...)`). So a resolver
that answers "the operator's value if they set one, else the deployed default" drops in
without reshaping a single call site. Storage is `ops_flags`, the same table that has
backed the kill switch in production all along: key, value, reason, updated_by, updated_at.

**Three classes of knob, because they do not deserve the same trust:**

    runtime   Freely settable. Which stages self-drive, how much they do per tick, what
              the reservoir aims for. Getting these wrong wastes time or credit; it
              cannot email the wrong person.

    ratchet   Settable only in the SAFE direction. A spend cap may be lowered from the
              browser but never raised; a credit floor may be raised but never lowered.
              The deployed env value is the outer bound and the console can only tighten
              inside it, so no amount of clicking can spend more than the deploy allowed.

    env_only  Not settable here at all. G_SEND is human-only by standing rule; the kill
              switch has its own audited path in monitor; AUTO_APPROVE_ENABLED is half of
              a deliberate double gate and must stay a deploy-time decision. These appear
              on the dashboard as state, never as a control.

**Fail direction — deliberate, and the opposite of the kill switch.** `monitor.db_kill_switch`
fails OPEN on a database error (returns False, falls back to env) because a kill switch that
jams on is its own outage. An autonomy allowlist that failed open would do the reverse: a
blip in the database would start running paid stages unattended. So `get()` fails CLOSED —
any error falls back to the deployed env value, which is always the more conservative of the
two. Same table, opposite default, and there is a test for it.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional

from . import config

RUNTIME = "runtime"
RATCHET = "ratchet"
ENV_ONLY = "env_only"


class NotSettable(Exception):
    """The knob exists but this caller may not set it (env_only, or a loosened ratchet)."""


@dataclass(frozen=True)
class Control:
    name: str                       # the ops_flags key, and the dashboard's identifier
    kind: str                       # 'bool' | 'int' | 'float' | 'csv' | 'str'
    klass: str                      # RUNTIME | RATCHET | ENV_ONLY
    label: str
    attr: Optional[str] = None      # config attribute, when it is named differently
    help: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: tuple[str, ...] = ()
    # For RATCHET only: which direction is SAFER. 'min' => a lower number is more
    # restrictive (a spend cap); 'max' => a higher number is (a floor you stop at).
    tighten: str = "min"

    @property
    def config_attr(self) -> str:
        return self.attr or self.name


# The env var is AUTONOMOUS_STAGES, the config constant is AUTONOMOUS_STAGES_ENABLED, and
# `run.AUTONOMOUS_STAGES` is a THIRD thing (the tuple of stages that are gateable at all).
# Getting those confused is easy and silent, so the mapping is declared once, here.
CONTROLS: dict[str, Control] = {c.name: c for c in (
    Control("AUTONOMOUS_STAGES", "csv", RUNTIME, "Self-driving stages",
            attr="AUTONOMOUS_STAGES_ENABLED",
            help="Which stages a scheduled tick may run on its own. An allowlist, not a "
                 "boolean: enable one, watch it for a day, then add the next — so when "
                 "spend or volume moves you know which stage moved it."),
    Control("DM_ENABLED", "bool", RUNTIME, "Decision-maker lookup",
            help="Ask Companies House who runs each firm, and address the email to them."),
    Control("CRITIC_ENABLED", "bool", RUNTIME, "Draft critic",
            help="An independent model reads every draft before you do."),
    Control("CRITIC_MODE", "str", RUNTIME, "Critic mode", choices=("shadow", "gate"),
            help="shadow: records a verdict and decides nothing. gate: a failed draft is "
                 "never auto-approved. Do not leave shadow until the agreement report says so."),
    Control("READY_POOL_TARGET", "int", RUNTIME, "Enriched leads to keep ready",
            minimum=0, maximum=5000,
            help="The demand-pull target. Discovery and enrichment run only to refill "
                 "toward this, then idle at zero cost."),
    Control("DRAFT_BACKLOG_MAX", "int", RUNTIME, "Stop drafting past this review backlog",
            minimum=1, maximum=5000,
            help="Drafting is the last credit-spending stage before a human gate, so "
                 "without this the pipeline writes email nobody has read."),
    Control("PLACES_PER_TICK", "int", RUNTIME, "Places queries / tick", minimum=0, maximum=200),
    Control("CROSSREF_PER_TICK", "int", RUNTIME, "PECR cross-references / tick", minimum=0, maximum=500),
    Control("DISCOVER_PER_TICK", "int", RUNTIME, "Register discoveries / tick", minimum=0, maximum=200),
    Control("ENRICH_PER_TICK", "int", RUNTIME, "Enrichments / tick", minimum=0, maximum=200),
    Control("DM_PER_TICK", "int", RUNTIME, "Decision-maker lookups / tick", minimum=0, maximum=200),
    Control("DRAFT_PER_TICK", "int", RUNTIME, "Drafts / tick", minimum=0, maximum=200),
    Control("CRITIC_PER_TICK", "int", RUNTIME, "Critiques / tick", minimum=0, maximum=200),
    Control("FOLLOWUP_PER_TICK", "int", RUNTIME, "Follow-ups / tick", minimum=0, maximum=200),
    Control("SEND_PER_TICK", "int", RUNTIME, "Sends / tick", minimum=0, maximum=50,
            help="The queue already spaces slots; this bounds the catch-up burst after "
                 "an outage, when several slots fall due at once."),

    # --- ratchets: the console may tighten these, never loosen them ---
    Control("MONTHLY_SPEND_CAP_GBP", "float", RATCHET, "Monthly cash cap (£)",
            tighten="min", minimum=0,
            help="Hard stop across every cash-billed provider. You can lower it here; "
                 "raising it is a deploy decision."),
    Control("PER_INBOX_DAILY_CAP", "int", RATCHET, "Sends / inbox / day",
            tighten="min", minimum=0,
            help="Capacity is the MIN of this and the warm-up ramp, so setting it below "
                 "the ramp pins sending at this number."),
    Control("CREDIT_FLOOR_GBP", "float", RATCHET, "Stop discovery below this credit (£)",
            tighten="max", minimum=0,
            help="Higher is safer — discovery stops sooner and leaves more credit."),

    # --- displayed, never settable from a browser ---
    Control("G_SEND", "bool", ENV_ONLY, "Live sending (G-SEND)",
            help="Human-only by standing rule. The system can never set this."),
    Control("KILL_SWITCH", "bool", ENV_ONLY, "Kill switch (env)",
            help="The DB half has its own audited control on Settings."),
    Control("AUTO_APPROVE_ENABLED", "bool", ENV_ONLY, "Auto-approve (graduation)",
            help="Half of a deliberate double gate; the other half lives in "
                 "sequence_config.json. Both are deploy-time decisions."),
)}

_TRUTHY = {"1", "true", "yes", "on"}


def _parse(kind: str, raw: str) -> Any:
    if kind == "bool":
        return raw.strip().lower() in _TRUTHY
    if kind == "int":
        return int(float(raw))
    if kind == "float":
        return float(raw)
    if kind == "csv":
        return tuple(p.strip() for p in raw.split(",") if p.strip())
    return raw.strip()


def _serialise(kind: str, value: Any) -> str:
    if kind == "bool":
        return "1" if value else "0"
    if kind == "csv":
        return ",".join(value) if not isinstance(value, str) else value
    return str(value)


def env_value(name: str) -> Any:
    """The deployed default — what this knob is when nobody has overridden it."""
    return getattr(config, CONTROLS[name].config_attr)


def get(name: str, *, cur=None) -> Any:
    """The operator's value if they set one, else the deployed default.

    Fails CLOSED: any database problem returns the env value, which is always the more
    conservative of the two. A dashboard override can only ever be LESS restrictive than
    the deploy for runtime knobs, and for ratchets it cannot be less restrictive at all —
    so falling back to env can never widen what the pipeline does.
    """
    spec = CONTROLS[name]
    fallback = env_value(name)
    if spec.klass == ENV_ONLY:
        return fallback                      # never read an override for these
    try:
        from . import monitor
        raw = monitor.get_flag(_key(name), cur=cur)
    except Exception:
        return fallback
    if raw is None or raw == "":
        return fallback
    try:
        value = _parse(spec.kind, raw)
    except (TypeError, ValueError):
        return fallback
    if spec.klass == RATCHET:
        # belt and braces: even a value written directly into the table by hand cannot
        # loosen the deployed bound
        return min(value, fallback) if spec.tighten == "min" else max(value, fallback)
    return value


def _key(name: str) -> str:
    """ops_flags keys are namespaced so a control can never collide with the kill switch,
    the grid cursor, or the digest throttle."""
    return f"control:{name}"


def is_overridden(name: str, *, cur=None) -> bool:
    try:
        from . import monitor
        return bool(monitor.get_flag(_key(name), cur=cur))
    except Exception:
        return False


def set(name: str, value: Any, *, by: str, reason: str = "", cur=None) -> Any:
    """Set a control, or raise NotSettable. Returns the effective value.

    Every change writes provenance (ops_flags.updated_by/reason) AND an audit row, because
    "who turned enrichment on and why" is exactly the question asked after a surprise.
    """
    if name not in CONTROLS:
        raise KeyError(f"unknown control: {name}")
    spec = CONTROLS[name]
    if spec.klass == ENV_ONLY:
        raise NotSettable(f"{name} is set at deploy time only, never from the console")
    if not by:
        raise ValueError("a control change must record who made it")

    value = _parse(spec.kind, value) if isinstance(value, str) else value
    if spec.kind == "str" and spec.choices and value not in spec.choices:
        raise ValueError(f"{name} must be one of {spec.choices}")
    if spec.kind == "csv":
        value = tuple(value)
    if spec.kind in ("int", "float"):
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError(f"{name} must be >= {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError(f"{name} must be <= {spec.maximum}")
    if spec.klass == RATCHET:
        bound = env_value(name)
        loosened = value > bound if spec.tighten == "min" else value < bound
        if loosened:
            raise NotSettable(
                f"{name} may only be tightened from here: the deploy allows "
                f"{bound}, and {value} is less restrictive. Raising it is a deploy decision.")

    from . import audit, monitor
    monitor.set_flag(_key(name), _serialise(spec.kind, value),
                     reason=reason or f"set by {by}", updated_by=by, cur=cur)
    audit.record(None, "control_changed", source="control",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"{name} = {_serialise(spec.kind, value)} by {by}"
                        + (f" — {reason}" if reason else ""),
                 detail={"control": name, "value": _serialise(spec.kind, value),
                         "by": by, "class": spec.klass},
                 cur=cur)
    return value


def clear(name: str, *, by: str, reason: str = "", cur=None) -> Any:
    """Drop the override and return to the deployed default."""
    if name not in CONTROLS:
        raise KeyError(f"unknown control: {name}")
    if CONTROLS[name].klass == ENV_ONLY:
        raise NotSettable(f"{name} has no override to clear")
    from . import audit, monitor
    monitor.set_flag(_key(name), "", reason=reason or f"cleared by {by}",
                     updated_by=by, cur=cur)
    audit.record(None, "control_changed", source="control",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"{name} reverted to the deployed default by {by}",
                 detail={"control": name, "value": None, "by": by}, cur=cur)
    return env_value(name)


# --------------------------------------------------------------------------- #
#  Stage autonomy — the one knob with its own vocabulary
# --------------------------------------------------------------------------- #
def autonomous_stages(*, cur=None) -> tuple[str, ...]:
    """The allowlist the tick honours. `("all",)` means every gateable stage."""
    return tuple(get("AUTONOMOUS_STAGES", cur=cur))


def stage_enabled(stage: str, *, cur=None) -> bool:
    enabled = autonomous_stages(cur=cur)
    return bool(config.PIPELINE_AUTONOMOUS or "all" in enabled or stage in enabled)


def set_stage(stage: str, on: bool, *, by: str, reason: str = "", cur=None) -> tuple[str, ...]:
    """Add or remove ONE stage, leaving the rest of the allowlist alone.

    The dashboard toggles one row at a time, and a read-modify-write of the whole CSV is
    what makes that safe to do repeatedly without the operator having to retype the list.
    """
    current = list(autonomous_stages(cur=cur))
    if "all" in current:
        # expand before editing, or turning one stage OFF would silently do nothing
        from .run import AUTONOMOUS_STAGES
        current = list(AUTONOMOUS_STAGES)
    if on and stage not in current:
        current.append(stage)
    elif not on and stage in current:
        current.remove(stage)
    else:
        return tuple(current)
    set("AUTONOMOUS_STAGES", tuple(current), by=by,
        reason=reason or f"{'enabled' if on else 'disabled'} {stage}", cur=cur)
    return tuple(current)


def snapshot(*, cur=None) -> list[dict]:
    """Every control with its effective value, its deployed default, and whether the
    operator has overridden it — what the control room renders."""
    out = []
    for name, spec in CONTROLS.items():
        effective = get(name, cur=cur)
        out.append({
            "name": name, "label": spec.label, "kind": spec.kind, "class": spec.klass,
            "help": spec.help, "choices": spec.choices,
            "value": effective, "default": env_value(name),
            "overridden": spec.klass != ENV_ONLY and is_overridden(name, cur=cur),
        })
    return out
