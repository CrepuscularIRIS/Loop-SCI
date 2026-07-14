"""loop_sci.literature.extract — fact extraction sub-package."""
from __future__ import annotations

from loop_sci.literature.extract.extractor import FactExtractor
from loop_sci.literature.extract.fact import Fact, SourceRef, VerificationStatus

__all__ = ["Fact", "FactExtractor", "SourceRef", "VerificationStatus"]
