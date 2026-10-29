"""Phase 2 admission policies: which resolved references become graph edges.

A policy is frozen against one audited build: its admitted methods met the Phase 2 gate on
that build's independent audit (docs/graphrag/coverage-report.md). The graph builder
refuses another build, since a different resolver output was not what was audited.
"""

from dataclasses import dataclass
from typing import Any

RESOLVED = frozenset({"resolved_exact", "resolved_unique_fuzzy"})


@dataclass(frozen=True)
class AdmissionPolicy:
    name: str
    source_build: str  # the profile whose audit justified this policy
    audit_sheet: str
    methods: frozenset[str]
    decided: str
    rationale: str
    statuses: frozenset[str] = RESOLVED  # temporal conflicts and the rest are review items

    def admits(self, record: dict[str, Any]) -> bool:
        return record["status"] in self.statuses and record["method"] in self.methods

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_build": self.source_build,
            "audit_sheet": self.audit_sheet,
            "methods": sorted(self.methods),
            "statuses": sorted(self.statuses),
            "decided": self.decided,
            "rationale": self.rationale,
        }


PHASE2_V1 = AdmissionPolicy(
    name="phase2-v1",
    source_build="3325b81913b3",
    audit_sheet="edge_audit_3325b81913b3.csv",
    methods=frozenset({"neutral_exact", "name_with_report", "name_with_date"}),
    decided="2026-10-28",
    rationale=(
        "Methods that met the Phase 2 gate on the independent v3 audit (marked by Lexi): "
        "neutral_exact 39/40, name_with_report 21/21, name_with_date 15/15 complete edges. "
        "name_with_identifier (22/24) is held back until its running-header failure is "
        "fixed and re-audited; name_only (17/20) stays candidate evidence."
    ),
)

POLICIES = {policy.name: policy for policy in (PHASE2_V1,)}
