"""contract' stage — freeze a derivation contract onto a hypothesis node.

Freezes a ``Contract{HYPOTHESIS, LATENT_ROOT, ACCEPT_IF, KILL_IF}`` by
prompting the LLM provider.  The contract is returned as a :class:`Contract`
dataclass and must be recorded on the node's ``refs["contract"]`` BEFORE any
adversarial verdict is produced (osp 2.1).

Key invariants
--------------
* **Freeze-before-verdict**: this stage writes the contract and must not
  depend on or read any verdict field.
* **Plan-grade tripwires**: ACCEPT_IF / KILL_IF are logical/formula-derived
  derivation conditions — NOT executable commands.  The prompt explicitly
  instructs the model to return logical/formula tripwires only.
* **Retry-once → drop / fallback**: if the provider returns malformed JSON
  on both attempts, a deterministic fallback Contract is returned (no crash).
* **Idempotent-safe**: calling freeze_contract twice with the same refs is
  safe; the second call returns a fresh Contract without corrupting any
  external state.
* **Provider discipline**: mirrors forge.py / prospect.py exactly —
  ``provider.create(system=, messages=[{role, content}], max_tokens=).get_text()``,
  ``json.loads``, retry-once → fallback.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from loop_sci.hypothesis.schemas import Contract

log = logging.getLogger(__name__)

_CONTRACT_SYSTEM = (
    "You are a derivation contract writer. Freeze a concise falsifiability "
    "contract for the hypothesis below. "
    "Return ONLY a JSON object with exactly these keys: "
    '{"HYPOTHESIS": "...", "LATENT_ROOT": "...", '
    '"ACCEPT_IF": "logical/formula tripwire for acceptance — NOT a shell command", '
    '"KILL_IF": "logical/formula tripwire for rejection — NOT a shell command"}. '
    "ACCEPT_IF and KILL_IF must be derivation tripwires (logical conditions or "
    "formulae derived from the hypothesis), never executable run commands."
)


async def freeze_contract(hyp_refs: dict[str, Any], provider: Any) -> Contract:
    """Freeze a derivation contract for a hypothesis node.

    Prompts *provider* to produce ``{HYPOTHESIS, LATENT_ROOT, ACCEPT_IF, KILL_IF}``
    and returns the result as a :class:`~loop_sci.hypothesis.schemas.Contract`.
    On JSON parse failure (both attempts), returns a deterministic fallback
    Contract derived from the mechanism field so callers never crash.

    Args:
        hyp_refs: The ``Node.refs`` dict of the hypothesis node.  Expected to
            contain at least ``hyp.MECHANISM`` and ``topic``.  No verdict key
            is read — this stage runs before any verdict exists.
        provider: LLM provider implementing
            ``await create(*, system, messages, max_tokens) -> LLMResponse``
            with a ``.get_text()`` method on the response.

    Returns:
        A :class:`Contract` with all four fields populated.
    """
    hyp: dict[str, Any] = (hyp_refs.get("hyp") or {})
    mechanism: str = hyp.get("MECHANISM", "")
    topic: str = hyp_refs.get("topic", "")

    prompt = (
        f"Hypothesis mechanism: {mechanism}\n"
        f"Topic: {topic}\n\n"
        "Produce the derivation contract JSON."
    )

    # Retry-once → fallback (mirrors forge.py / prospect.py discipline)
    for attempt in range(2):
        try:
            resp = await provider.create(
                system=_CONTRACT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            raw: str = resp.get_text()
            d: dict[str, Any] = json.loads(raw)
            return Contract(
                HYPOTHESIS=str(d["HYPOTHESIS"]),
                LATENT_ROOT=str(d["LATENT_ROOT"]),
                ACCEPT_IF=str(d["ACCEPT_IF"]),
                KILL_IF=str(d["KILL_IF"]),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("contract: parse failed (attempt %d): %s", attempt, exc)

    # Deterministic fallback — no crash; callers can detect via LATENT_ROOT=="unknown"
    log.warning("contract: both provider attempts failed; returning fallback contract")
    return Contract(
        HYPOTHESIS=mechanism,
        LATENT_ROOT="unknown",
        ACCEPT_IF="(unavailable — provider returned malformed JSON)",
        KILL_IF="(unavailable — provider returned malformed JSON)",
    )
