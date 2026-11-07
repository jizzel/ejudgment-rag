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
    # Occurrences the audit found wrong in an otherwise admitted method, held out by hand
    # with the reason: (chunk id, source start, source end, reason). They become review
    # items, never edges, until a resolver change handles their pattern and is re-audited.
    quarantine: tuple[tuple[str, int, int, str], ...] = ()

    def quarantined(self, record: dict[str, Any]) -> bool:
        key = (record["chunk_id"], int(record["source_start"]), int(record["source_end"]))
        return any(key == (chunk, start, end) for chunk, start, end, _ in self.quarantine)

    def admits(self, record: dict[str, Any]) -> bool:
        return (
            record["status"] in self.statuses
            and record["method"] in self.methods
            and not self.quarantined(record)
        )

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_build": self.source_build,
            "audit_sheet": self.audit_sheet,
            "methods": sorted(self.methods),
            "statuses": sorted(self.statuses),
            "decided": self.decided,
            "rationale": self.rationale,
            # Only when present, so that a policy without one keeps its fingerprint.
            **({"quarantine": [list(q) for q in self.quarantine]} if self.quarantine else {}),
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

PHASE2_V2 = AdmissionPolicy(
    name="phase2-v2",
    source_build="f17184ccb15c",
    audit_sheet="edge_audit_f17184ccb15c.csv",
    methods=frozenset(
        {
            "neutral_exact",
            "name_with_report",
            "name_with_date",
            "name_with_decision_identifier",
            "name_with_dated_proceeding",
        }
    ),
    decided="2026-11-05",
    rationale=(
        "phase2-v1's methods plus the two identifier methods of resolver v5 (R1), which met "
        "the Phase 2 gate on the independent v5 audit (marked by Lexi): "
        "name_with_decision_identifier 20/20 and name_with_dated_proceeding 30/30 complete "
        "edges. The audit's 20 changed edges of admitted methods scored 19/20 complete; the "
        "one failure (row 59: a writ number that contradicts the target, unread because the "
        "name was cut at 'Attorney -General') is quarantined. name_with_proceeding (a "
        "proceeding number alone) and name_only stay candidate evidence."
    ),
    quarantine=(
        (
            "d381fea9-a797-5557-af29-853305d633af",
            34387,
            34420,
            "audit f17184ccb15c row 59: cites Writ No. LL/14/2019, the target is J1/14/2020",
        ),
    ),
)

PHASE2_V3 = AdmissionPolicy(
    name="phase2-v3",
    source_build="e21359336a18",
    audit_sheet="edge_audit_e21359336a18.csv",
    methods=PHASE2_V2.methods,
    decided="2026-11-05",
    rationale=(
        "phase2-v2's methods over resolver v12, whose changes since the audited v5 build "
        "were audited in turn (marked by Lexi): v6's 40 new edges 40/40; v5-to-v6 removals "
        "reviewed (all 8 sampled were correct edges, each restored in v12, as were 3 earlier "
        "audited neutral citations); v10's 35 new edges 31/35, the 4 failures fixed in v12 "
        "and removed; a fresh sample of the methods that failed, name_with_report 17/17 and "
        "neutral_exact 3/3. Row 59 of the v5 audit is now refused by the resolver "
        "(identifier_mismatch), so no quarantine is needed."
    ),
)

PHASE2_V4 = AdmissionPolicy(
    name="phase2-v4",
    source_build="1150e78bbcfb",
    audit_sheet="edge_audit_1150e78bbcfb.csv",
    methods=PHASE2_V3.methods,
    decided="2026-11-06",
    rationale=(
        "phase2-v3's methods over resolver v14 with canonical decisions (decisions-v2): "
        "copies of one decision are one node and one edge target. Both R2 sheets marked by "
        "Lexi: decision_audit_1150e78bbcfb.csv, merges 25/25 (gate 97%; 11 of 20 risky "
        "kept-apart pairs were one decision, the recall given up by blocking on conflicting "
        "numbers or stages); edge_audit_1150e78bbcfb.csv, 47 of the 441 edges R2 added "
        "(decision-level diff against e21359336a18: none removed or retargeted), 47/47 on "
        "every gated check, span 42/47 (boundary defects only)."
    ),
)

POLICIES = {policy.name: policy for policy in (PHASE2_V1, PHASE2_V2, PHASE2_V3, PHASE2_V4)}
