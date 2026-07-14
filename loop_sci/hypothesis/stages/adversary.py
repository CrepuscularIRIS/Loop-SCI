"""adversary' stage — deterministic pre-jury gate + Qwen-vs-Qwen adversarial jury.

Implements OpenSpec tasks 2.2, 2.3, 2.4, 2.5.

Key invariants
--------------
* **Deterministic pre-jury gate fires first**: if any load-bearing derivation
  step is ``[guess]`` OR the mechanism CONTRADICTS a grounding fact in the
  FactStore, the candidate receives a DOWN verdict immediately — NO jury/reviewer
  call is spent.  ``Verdict.decided_by`` is ``"deterministic-gate"``.
* **Qwen-vs-Qwen jury**: generator = Qwen-Max config; reviewer = a DISTINCT
  config (Qwen-Plus tier, KILL-biased adversarial persona, varied sampling).
  The reviewer issues the verdict (UP/DOWN) with ``decided_by="jury"``.
* **Structural no-self-acquit (CRITICAL)**: an UP verdict whose
  ``reviewer.model == generator_model`` MUST be rejected.  This is enforced at
  the routing layer before any verdict is recorded — the generator config
  structurally cannot grant the accept.
* **adversary' Checks C/D + evidence-grade anti-fabrication**: derivation steps
  annotated ``[guess]`` are load-bearing failures caught by the gate.  Any claim
  not grounded in a store fact cannot be promoted to accepted.
* **Retry-once → drop**: if the reviewer returns malformed JSON on both attempts,
  a DOWN verdict is returned (no crash).  Mirrors prospect.py / contract.py
  provider-call discipline exactly.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from loop_sci.hypothesis.schemas import DerivationStep, Verdict
from loop_sci.literature.factbase.store import FactStore

log = logging.getLogger(__name__)

_ADVERSARY_SYSTEM = (
    "You are an adversarial scientific reviewer with a KILL bias. "
    "Your job is to rigorously challenge the hypothesis. "
    "Check C: every decomposed claim needs an artifact/fact grounding. "
    "Check D: generalization test — does the mechanism hold beyond the specific finding? "
    "Annotate any claim not grounded in verified facts as [guess] (never promote to accepted). "
    "Return ONLY a JSON object: "
    '{"result": "UP" | "DOWN", "reasons": ["..."]}'
)


# ---------------------------------------------------------------------------
# Deterministic gate helpers
# ---------------------------------------------------------------------------


def _has_load_bearing_guess(derivation: list[DerivationStep]) -> bool:
    """Return True if any derivation step is graded ``[guess]``.

    A ``[guess]`` step is load-bearing by definition — it represents an
    ungrounded inference that has not been tied to a verified fact.
    """
    return any(s.grade == "[guess]" for s in derivation)


def _mechanism_contradicts_facts(mechanism: str, store: FactStore) -> bool:
    """Return True if *mechanism* is contradicted by any fact in *store*.

    Contradiction detection: a stored fact is treated as negating the mechanism
    when:
    1. The fact text contains a negation marker (``"not"`` or ``"no "``).
    2. At least one content keyword from the mechanism appears in that fact.

    This is intentionally conservative — false negatives (missed contradictions)
    are caught by the jury; false positives (spurious gate failures) are the
    wrong direction so the check is kept simple and keyword-based.

    Stopwords are filtered to avoid over-matching on function words.
    """
    _STOPWORDS = frozenset(
        {"the", "a", "an", "is", "are", "of", "in", "and", "or", "to", "that",
         "this", "with", "for", "from", "by", "be", "at", "as", "on", "it"}
    )

    mech_lower = mechanism.lower()
    mech_tokens = {
        tok for tok in mech_lower.split() if tok not in _STOPWORDS and len(tok) > 2
    }
    if not mech_tokens:
        return False

    for fact in store.all():
        fact_lower = fact.claim.lower()
        # Only inspect facts that explicitly negate something
        if "not " not in fact_lower and " no " not in fact_lower:
            continue
        # Check if any mechanism keyword appears in the negating fact
        if any(tok in fact_lower for tok in mech_tokens):
            return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_adversary(
    hyp_refs: dict[str, Any],
    derivation: list[DerivationStep],
    store: FactStore,
    generator_model: str,
    reviewer: Any,
) -> Verdict:
    """Run the adversary' stage for a single hypothesis candidate.

    Args:
        hyp_refs: The ``Node.refs`` dict of the hypothesis node.  Must contain
            at least ``hyp.MECHANISM`` and ``grounding_fact_ids``.
        derivation: Ordered list of :class:`~loop_sci.hypothesis.schemas.DerivationStep`.
            Steps graded ``[guess]`` are load-bearing failures caught by the gate.
        store: :class:`~loop_sci.literature.factbase.store.FactStore` instance
            used for grounding / contradiction checks.
        generator_model: Model-id string of the generator (e.g. ``"qwen-max"``).
            Used for the structural no-self-acquit check.
        reviewer: LLM provider implementing
            ``await create(*, system, messages, max_tokens) -> LLMResponse``
            with a ``.get_text()`` method on the response and a ``.model``
            attribute carrying the reviewer's model id.  The reviewer is
            NEVER called when the deterministic gate fires.

    Returns:
        A :class:`~loop_sci.hypothesis.schemas.Verdict` with all fields
        populated.  ``decided_by`` is ``"deterministic-gate"`` for gate failures
        and ``"jury"`` for all jury-path outcomes.
    """
    mechanism: str = (hyp_refs.get("hyp") or {}).get("MECHANISM", "")

    # ------------------------------------------------------------------
    # 1. Deterministic pre-jury gate (osp 2.2 / Spec Patch)
    #    Fires BEFORE any reviewer call — zero provider tokens spent.
    # ------------------------------------------------------------------
    if _has_load_bearing_guess(derivation):
        log.debug("adversary: gate fired — load-bearing [guess] in derivation")
        return Verdict(
            id=f"det_{uuid.uuid4().hex[:8]}",
            reviewer_model="deterministic-gate",
            result="DOWN",
            reasons=["Deterministic gate: derivation contains a load-bearing [guess] step"],
            decided_by="deterministic-gate",
        )

    if _mechanism_contradicts_facts(mechanism, store):
        log.debug("adversary: gate fired — mechanism contradicts a grounding fact")
        return Verdict(
            id=f"det_{uuid.uuid4().hex[:8]}",
            reviewer_model="deterministic-gate",
            result="DOWN",
            reasons=["Deterministic gate: mechanism contradicts a grounding fact in the store"],
            decided_by="deterministic-gate",
        )

    # ------------------------------------------------------------------
    # 2. Structural no-self-acquit (osp 2.3, CRITICAL)
    #    If reviewer identity == generator identity, an UP is not honored.
    #    This is enforced here at the routing layer — before the jury call —
    #    so that even if the reviewer returns UP, the generator cannot acquit
    #    itself.  We short-circuit and return DOWN immediately.
    # ------------------------------------------------------------------
    reviewer_model: str = getattr(reviewer, "model", "unknown")
    if reviewer_model == generator_model:
        log.debug(
            "adversary: no-self-acquit triggered (reviewer_model=%r == generator_model=%r)",
            reviewer_model,
            generator_model,
        )
        return Verdict(
            id=f"nsa_{uuid.uuid4().hex[:8]}",
            reviewer_model=reviewer_model,
            result="DOWN",
            reasons=[
                f"No-self-acquit: reviewer model '{reviewer_model}' matches generator model "
                f"'{generator_model}' — the generator cannot grant its own accept."
            ],
            decided_by="deterministic-gate",
        )

    # ------------------------------------------------------------------
    # 3. Qwen-vs-Qwen adversarial jury (osp 2.4, 2.5)
    #    KILL-biased reviewer with adversarial persona.
    #    Retry-once → DOWN on persistent JSON failure (mirrors contract.py).
    # ------------------------------------------------------------------
    grounding_ids = hyp_refs.get("grounding_fact_ids", [])
    derivation_text = "\n".join(
        f"  {s.grade} step={s.step!r} fact_ids={s.fact_ids}" for s in derivation
    )
    prompt = (
        f"Mechanism: {mechanism}\n"
        f"Grounding fact_ids: {grounding_ids}\n"
        f"Derivation:\n{derivation_text}"
    )

    for attempt in range(2):
        try:
            resp = await reviewer.create(
                system=_ADVERSARY_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            raw: str = resp.get_text()
            d: dict[str, Any] = json.loads(raw)
            result = str(d["result"]).upper()
            if result not in ("UP", "DOWN"):
                raise ValueError(f"unexpected result value: {result!r}")
            return Verdict(
                id=f"jury_{uuid.uuid4().hex[:8]}",
                reviewer_model=reviewer_model,
                result=result,  # type: ignore[arg-type]
                reasons=list(d.get("reasons", [])),
                decided_by="jury",
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("adversary: reviewer parse failed (attempt %d): %s", attempt, exc)

    # Both attempts failed — fail-closed to DOWN (no crash)
    log.warning("adversary: reviewer returned invalid JSON on both attempts; failing DOWN")
    return Verdict(
        id=f"jury_{uuid.uuid4().hex[:8]}",
        reviewer_model=reviewer_model,
        result="DOWN",
        reasons=["Reviewer returned invalid JSON on both attempts"],
        decided_by="jury",
    )
