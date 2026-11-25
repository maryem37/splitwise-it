"""Decision Provenance model capturing structured justifications for IT carve-out decisions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


class DecisionProvenanceRecord(BaseModel):
    """
    Structured record documenting the exact provenance and justification of a planning decision.
    Separates deterministic facts from narrative explanations.
    """
    decision_id: str
    asset_id: str
    decision_category: Literal["strategy", "wave_assignment", "scc_coupling", "tsa_retention", "scenario_adjustment"]
    selected_action: str
    justification: str
    supporting_dependencies: list[str] = Field(default_factory=list)
    relevant_constraints: list[str] = Field(default_factory=list)
    related_risks: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    responsible_component: str = "deterministic_engine"
    evaluation_status: str = "PASS"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    deterministic_facts: dict[str, Any] = Field(default_factory=dict)
    narrative_explanation: str = ""


class DecisionProvenanceRegistry(BaseModel):
    """Container for all provenance records generated across a planning execution."""
    execution_id: str
    records: list[DecisionProvenanceRecord] = Field(default_factory=list)

    def get_for_asset(self, asset_id: str) -> list[DecisionProvenanceRecord]:
        return [r for r in self.records if r.asset_id == asset_id]

    def add_record(self, record: DecisionProvenanceRecord) -> None:
        self.records.append(record)
