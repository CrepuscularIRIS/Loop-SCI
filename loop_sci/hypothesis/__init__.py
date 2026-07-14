"""loop_sci.hypothesis — hypothesis schema and lifecycle sub-package."""

from loop_sci.hypothesis.config import HypothesisConfig
from loop_sci.hypothesis.coordinator import HypothesisCoordinator
from loop_sci.hypothesis.executor import HypothesisExecutor
from loop_sci.hypothesis.ledger import VerdictLedger
from loop_sci.hypothesis.ranked import RankedHypothesis, RankedHypothesisStore
from loop_sci.hypothesis.schemas import (
    Autopsy,
    Contract,
    DerivationStep,
    HypothesisHyp,
    HypothesisRefs,
    Iteration,
    ProblemCard,
    Scores,
    Verdict,
    build_card_refs,
    build_hyp_refs,
    refs_from_dict,
)
from loop_sci.hypothesis.tools import register_hypothesis_tools

__all__ = [
    "Autopsy",
    "Contract",
    "DerivationStep",
    "HypothesisConfig",
    "HypothesisCoordinator",
    "HypothesisExecutor",
    "HypothesisHyp",
    "HypothesisRefs",
    "Iteration",
    "ProblemCard",
    "RankedHypothesis",
    "RankedHypothesisStore",
    "Scores",
    "Verdict",
    "VerdictLedger",
    "build_card_refs",
    "build_hyp_refs",
    "refs_from_dict",
    "register_hypothesis_tools",
]
