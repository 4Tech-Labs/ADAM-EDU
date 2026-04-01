"""Internal assignment blueprint schema retained for compatibility.

The published repository is teacher-only, but authoring still persists this
structure alongside canonical_output for continuity of internal contracts.
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Any

# 1. Config Object
class ConfigObject(BaseModel):
    """Global configuration metadata for the assignment."""
    language: str = Field(default="es")
    difficulty: str = Field(default="intermediate")
    industry_context: str | None = None
    target_audience: str | None = None

# 2. Routing Manifest
class RoutingManifest(BaseModel):
    """
    Defines UI behavior and module visibility.
    Valid structural policies:
    - harvard_only: Only narrative case, NO EDA.
    - charts_only: Narrative + EDA charts dashboard. No code solutions allowed.
    - charts_plus_solution: Narrative + EDA + guided technical explanation (no raw code).
    - charts_plus_code: Analytic sandbox mode with interactive code execution allowed.
    """
    policy_type: str = Field(pattern="^(harvard_only|charts_only|charts_plus_solution|charts_plus_code)$")
    enabled_tabs: List[str] = Field(default_factory=list)

# 3. Student Artifacts
class StudentArtifacts(BaseModel):
    """
    References to lightweight artifacts explicitly granted to the student.
    Heavy artifacts only exist as referencing IDs to the ArtifactManifest table.
    """
    narrative_text: str | None = None
    eda_summary: str | None = None
    attached_datasets_manifest_ids: List[str] = Field(default_factory=list)

# 4. Module Manifests
class ModuleManifest(BaseModel):
    """
    Internal context boundary metadata retained inside the blueprint contract.
    """
    module_id: str
    twin_role_system_prompt: str
    allowed_context_keys: List[str] = Field(default_factory=list)
    isolated_memory: bool = True

class ModuleManifests(BaseModel):
    """Container for the 5 interactive modules (or subsets depending on routing)."""
    modules: List[ModuleManifest] = Field(default_factory=list)

# 5. Grading Contract
class DeterministicCheck(BaseModel):
    check_id: str
    requirement: str
    weight: float

class GradingContract(BaseModel):
    """Algorithmic rules for the Rubric-based Scoring layer."""
    deterministic_checks: List[DeterministicCheck] = Field(default_factory=list)
    qualitative_rubric: Dict[str, Any] = Field(default_factory=dict)
    time_limit_minutes: int | None = None

# 6. Validation Contract
class ValidationContract(BaseModel):
    """Rules for transversal Final Validation across modules."""
    passing_threshold_global: float
    required_modules_passed: int

# 7. Artifact Manifest Projection
class ArtifactManifestProjection(BaseModel):
    """
    Projection of artifact IDs stored in ArtifactManifest.
    This remains an internal reference layer rather than the source of truth.
    """
    artifact_ids: List[str] = Field(default_factory=list)

# The Core 8-Key Assignment Blueprint Contract + Transitional Legacies
class TransitionalMetadata(BaseModel):
    """
    Metadata flagging blueprint fields synthesized for compatibility with the
    current internal contract.
    """
    is_transitional: bool = True
    origin: str = "langgraph_monolith"
    placeholders_used: List[str] = Field(default_factory=lambda: ["module_manifests", "grading_contract", "validation_contract", "artifact_manifest"])

class AssignmentBlueprint(BaseModel):
    """
    Internal blueprint persisted with authoring results.
    Retained alongside canonical_output for compatibility and schema continuity.
    """
    version: str = Field(default="adam-v8.0")
    transitional_metadata: TransitionalMetadata | None = None
    config_object: ConfigObject
    routing_manifest: RoutingManifest
    student_artifacts: StudentArtifacts
    module_manifests: ModuleManifests
    grading_contract: GradingContract
    validation_contract: ValidationContract
    artifact_manifest: ArtifactManifestProjection
