"""SLCML Three-Phase Pipeline Orchestrator v2.1 — Phase A/B/C lifecycle management."""

import json
import os
import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts.slcml_phase_a import PHASE_A_SYSTEM, PHASE_A_TASK, PHASE_A_COT, PHASE_A_CONSTRAINTS, PHASE_A_EXEMPLAR, PHASE_A_SELF_CHECK, PhaseAValidator
from prompts.slcml_phase_b import PHASE_B_SYSTEM, PHASE_B_TASK, PHASE_B_COT, PHASE_B_SELF_CHECK, PhaseBValidator
from prompts.slcml_phase_c import PHASE_C_SYSTEM, PHASE_C_TASK, PHASE_C_SELF_CHECK, PhaseCValidator, Tier1RuleFilter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SLCML_Pipeline")


class LifecycleStage(str, Enum):
    COMPILE_IR       = "compilation_ir"
    COMPILE_SOLIDITY = "compilation_solidity"
    RUNTIME_ANALYSIS = "runtime_analysis"


@dataclass
class PipelineConfig:
    """Global pipeline configuration."""
    model_name: str = "gpt-4o"
    temperature_ir: float = 0.1
    temperature_solidity: float = 0.0
    temperature_runtime: float = 0.2
    max_tokens_ir: int = 8192
    max_tokens_solidity: int = 8192
    max_tokens_runtime: int = 4096
    schema_version: str = "2.0"
    directive_version_ir: str = "2.1-COMPILE-IR"
    directive_version_sol: str = "2.1-COMPILE-SOL"
    directive_version_runtime: str = "2.1-RUNTIME"


@dataclass
class PhaseResult:
    """Standardized result container for each pipeline phase."""
    phase: LifecycleStage
    directive_version: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    input_hash: str = ""
    output_raw: str = ""
    output_parsed: Optional[Dict] = None
    self_check_passed: bool = False
    self_check_failures: List[str] = field(default_factory=list)


class PromptAssembler:
    """Assembles multi-layer prompts for each pipeline phase."""

    def __init__(self, config: PipelineConfig):
        self.config = config

    def _format(self, template: str, **extra_kwargs) -> str:
        return template.format(
            directive_version=extra_kwargs.get("directive_version", ""),
            schema_version=self.config.schema_version,
        )

    def assemble_phase_a(self, contract_text: str) -> List[Dict[str, str]]:
        dv = self.config.directive_version_ir
        system_prompt = "\n\n".join([
            self._format(PHASE_A_SYSTEM, directive_version=dv),
            self._format(PHASE_A_TASK, directive_version=dv),
            self._format(PHASE_A_COT, directive_version=dv),
            self._format(PHASE_A_CONSTRAINTS, directive_version=dv),
            self._format(PHASE_A_EXEMPLAR, directive_version=dv),
            self._format(PHASE_A_SELF_CHECK, directive_version=dv),
        ])
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please extract the SLCML IR from the following contract:\n\n{contract_text}"}
        ]

    def assemble_phase_b(self, ir_json: str) -> List[Dict[str, str]]:
        dv = self.config.directive_version_sol
        system_prompt = "\n\n".join([
            self._format(PHASE_B_SYSTEM, directive_version=dv),
            self._format(PHASE_B_TASK, directive_version=dv),
            self._format(PHASE_B_COT, directive_version=dv),
            self._format(PHASE_B_SELF_CHECK, directive_version=dv),
        ])
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate the Solidity smart contract from the following verified SLCML IR:\n\n{ir_json}"}
        ]

    def assemble_phase_c(self, ir_json: str, filtered_events: str) -> List[Dict[str, str]]:
        dv = self.config.directive_version_runtime
        system_prompt = "\n\n".join([
            self._format(PHASE_C_SYSTEM, directive_version=dv),
            self._format(PHASE_C_TASK, directive_version=dv),
            self._format(PHASE_C_SELF_CHECK, directive_version=dv),
        ])
        user_content = (
            "## Compilation IR Context (read-only)\n\n"
            f"{ir_json}\n\n"
            "## Tier-1 Filtered Events\n\n"
            f"{filtered_events}\n\n"
            "Please analyze the events and provide dispute-unit aggregation recommendations."
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]


class SLCMLPipeline:
    """Three-phase SLCML pipeline orchestrator: Phase A -> Phase B -> Phase C."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.assembler = PromptAssembler(self.config)
        self.results: Dict[str, PhaseResult] = {}

    def _hash_input(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _call_llm(self, messages: List[Dict[str, str]],
                  temperature: float, max_tokens: int) -> str:
        logger.warning("LLM call is in STUB mode. Replace _call_llm with actual API call.")
        return '{"stub": true, "message": "Replace _call_llm with actual LLM API call"}'

    def run_phase_a(self, contract_text: str) -> PhaseResult:
        """Phase A: Natural language contract -> SLCML five-tuple IR (JSON)."""
        logger.info("=== PHASE A: Legal Semantic Formalization ===")
        result = PhaseResult(
            phase=LifecycleStage.COMPILE_IR,
            directive_version=self.config.directive_version_ir,
            input_hash=self._hash_input(contract_text),
        )
        messages = self.assembler.assemble_phase_a(contract_text)
        logger.info(f"Phase A system prompt: {len(messages[0]['content'])} chars")
        raw_output = self._call_llm(messages, temperature=self.config.temperature_ir, max_tokens=self.config.max_tokens_ir)
        result.output_raw = raw_output
        try:
            parsed = json.loads(raw_output)
            result.output_parsed = parsed
        except json.JSONDecodeError as e:
            result.self_check_failures.append(f"JSON parse error: {e}")
            self.results["phase_a"] = result
            return result
        passed, failures = PhaseAValidator.validate(parsed)
        result.self_check_passed = passed
        result.self_check_failures = failures
        if passed:
            logger.info("Phase A: All self-checks PASSED")
        else:
            logger.warning(f"Phase A: {len(failures)} self-check failures")
            for f in failures:
                logger.warning(f"  {f}")
        self.results["phase_a"] = result
        return result

    def run_phase_b(self, ir_json: Optional[str] = None) -> PhaseResult:
        """Phase B: SLCML IR -> Solidity smart contract code."""
        logger.info("=== PHASE B: Solidity Code Generation ===")
        if ir_json is None:
            phase_a = self.results.get("phase_a")
            if not phase_a or not phase_a.output_parsed:
                raise ValueError("Phase A output not available. Run Phase A first or provide ir_json.")
            ir_json = json.dumps(phase_a.output_parsed, indent=2, ensure_ascii=False)
        result = PhaseResult(
            phase=LifecycleStage.COMPILE_SOLIDITY,
            directive_version=self.config.directive_version_sol,
            input_hash=self._hash_input(ir_json),
        )
        messages = self.assembler.assemble_phase_b(ir_json)
        logger.info(f"Phase B system prompt: {len(messages[0]['content'])} chars")
        raw_output = self._call_llm(messages, temperature=self.config.temperature_solidity, max_tokens=self.config.max_tokens_solidity)
        result.output_raw = raw_output
        code = raw_output
        if "```solidity" in code:
            start = code.index("```solidity") + len("```solidity")
            end = code.index("```", start)
            code = code[start:end].strip()
        elif "```" in code:
            start = code.index("```") + 3
            end = code.index("```", start)
            code = code[start:end].strip()
        result.output_parsed = {"solidity_code": code}
        ir_dict = json.loads(ir_json)
        passed, failures = PhaseBValidator.validate(code, ir_dict)
        result.self_check_passed = passed
        result.self_check_failures = failures
        if passed:
            logger.info("Phase B: All self-checks PASSED")
        else:
            logger.warning(f"Phase B: {len(failures)} self-check failures")
            for f in failures:
                logger.warning(f"  {f}")
        self.results["phase_b"] = result
        return result

    def run_phase_c(self, filtered_events: List[Dict],
                    ir_json: Optional[str] = None) -> PhaseResult:
        """Phase C: Runtime dispute aggregation analysis (off-chain LLM)."""
        logger.info("=== PHASE C: Runtime Dispute Analysis ===")
        if ir_json is None:
            phase_a = self.results.get("phase_a")
            if not phase_a or not phase_a.output_parsed:
                raise ValueError("Phase A output not available. Run Phase A first or provide ir_json.")
            ir_json = json.dumps(phase_a.output_parsed, indent=2, ensure_ascii=False)
        events_json = json.dumps(filtered_events, indent=2, ensure_ascii=False)
        result = PhaseResult(
            phase=LifecycleStage.RUNTIME_ANALYSIS,
            directive_version=self.config.directive_version_runtime,
            input_hash=self._hash_input(events_json),
        )
        messages = self.assembler.assemble_phase_c(ir_json, events_json)
        logger.info(f"Phase C system prompt: {len(messages[0]['content'])} chars")
        raw_output = self._call_llm(messages, temperature=self.config.temperature_runtime, max_tokens=self.config.max_tokens_runtime)
        result.output_raw = raw_output
        try:
            parsed = json.loads(raw_output)
            result.output_parsed = parsed
        except json.JSONDecodeError as e:
            result.self_check_failures.append(f"JSON parse error: {e}")
            self.results["phase_c"] = result
            return result
        input_event_ids = [e.get("event_id", "") for e in filtered_events]
        passed, failures = PhaseCValidator.validate(parsed, input_event_ids)
        result.self_check_passed = passed
        result.self_check_failures = failures
        if passed:
            logger.info("Phase C: All self-checks PASSED")
        else:
            logger.warning(f"Phase C: {len(failures)} self-check failures")
            for f in failures:
                logger.warning(f"  {f}")
        self.results["phase_c"] = result
        return result

    def run_full_compilation(self, contract_text: str) -> Dict[str, PhaseResult]:
        """Run Phase A -> Phase B sequentially."""
        self.run_phase_a(contract_text)
        if self.results["phase_a"].output_parsed:
            self.run_phase_b()
        return self.results

    def export_results(self, output_dir: str = "./slcml_output"):
        """Export all phase results to files."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for phase_key, result in self.results.items():
            ext = ".sol" if result.phase == LifecycleStage.COMPILE_SOLIDITY else ".json"
            raw_path = os.path.join(output_dir, f"{timestamp}_{phase_key}_output{ext}")
            with open(raw_path, "w", encoding="utf-8") as f:
                if result.phase == LifecycleStage.COMPILE_SOLIDITY and result.output_parsed:
                    f.write(result.output_parsed.get("solidity_code", result.output_raw))
                else:
                    f.write(result.output_raw)
            report_path = os.path.join(output_dir, f"{timestamp}_{phase_key}_report.json")
            report = {
                "phase": result.phase.value,
                "directive_version": result.directive_version,
                "timestamp": result.timestamp,
                "input_hash": result.input_hash,
                "self_check_passed": result.self_check_passed,
                "self_check_failures": result.self_check_failures,
            }
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"Exported {phase_key}: {raw_path}")


if __name__ == "__main__":

    config = PipelineConfig(model_name="gpt-4o", temperature_ir=0.1, temperature_solidity=0.0, temperature_runtime=0.2)
    pipeline = SLCMLPipeline(config)

    sample_contract = """
    Article 7.3: The desensitized patient data obtained by Party B shall be used exclusively
    for the model training purposes stipulated in this Project and strictly within the territory
    of the People's Republic of China. Without prior written consent of Party A, Party B shall
    not transmit such data to any overseas servers or disclose it to any third party.
    In the event of any breach, Party A shall have the right to immediately suspend Party B's
    data access privileges and require Party B to submit a written explanation within 5
    business days.

    Article 8.1: Party B shall submit a monthly data usage audit report during data access.
    Failure to submit for two consecutive months shall entitle Party A to suspend data access
    and initiate a breach investigation procedure.
    """

    print("\n" + "=" * 70)
    print("STEP 1: COMPILATION PIPELINE (Phase A -> Phase B)")
    print("=" * 70)

    result_a = pipeline.run_phase_a(sample_contract)
    print(f"\nPhase A passed: {result_a.self_check_passed}")
    if result_a.self_check_failures:
        print(f"Phase A failures: {result_a.self_check_failures}")

    print("\n" + "=" * 70)
    print("STEP 3: RUNTIME PIPELINE (Tier-1 -> Phase C)")
    print("=" * 70)

    mock_ir = {
        "slcml_version": "2.0",
        "contract_id": "MED-COLLAB-2024-073",
        "extraction_metadata": {"directive_version": "2.1-COMPILE-IR", "lifecycle_stage": "compilation_ir"},
        "S_subjects": [
            {"subject_id": "s_party_a", "role": "data_provider"},
            {"subject_id": "s_party_b", "role": "model_trainer"},
        ],
        "O_objects": [
            {"object_id": "o_patient_dataset", "type": "patient_dataset", "sensitivity_level": 4},
            {"object_id": "o_trained_model", "type": "model_parameters", "sensitivity_level": 3},
        ],
        "C_conditions": [],
        "R_rules": [],
        "dispute_unit_templates": [
            {
                "template_id": "dut_geo_breach",
                "ClauseID": "7.3",
                "IssueType": "geographic_compliance_breach",
                "subject_pattern": "role == model_trainer",
                "object_pattern": "type == patient_dataset",
                "time_window_type": "contract_duration",
                "merge_criteria_description": "Events grouped if same subject transfers data outside CN under Clause 7.3.",
                "finality_defaults": {"N_max": 2, "K_max": 3, "theta_safe": 0.6},
                "restricted_recovery_defaults": {"manual_review_required": True, "high_sensitive_access_blocked": True, "privacy_cost_multiplier": 1.5},
            },
        ],
        "A_audit": {"evidence_templates": []},
    }

    mock_raw_events = [
        {"event_id": "evt_001", "timestamp": "2025-06-15T08:30:00Z", "subject_id": "s_party_b", "object_id": "o_patient_dataset", "event_type": "data_transfer", "matched_clause_id": "7.3", "issue_type": "geographic_compliance_breach", "oracle_source": "geo_ip_oracle", "raw_description": "Party B transferred patient dataset to AWS Tokyo region (JP)."},
        {"event_id": "evt_002", "timestamp": "2025-06-15T09:15:00Z", "subject_id": "s_party_b", "object_id": "o_patient_dataset", "event_type": "data_transfer", "matched_clause_id": "7.3", "issue_type": "geographic_compliance_breach", "oracle_source": "geo_ip_oracle", "raw_description": "Party B replicated dataset to backup server in Singapore (SG)."},
        {"event_id": "evt_003", "timestamp": "2025-06-15T10:00:00Z", "subject_id": "s_party_b", "object_id": "o_trained_model", "event_type": "performance_report", "matched_clause_id": "8.1", "issue_type": "audit_report_missing", "oracle_source": "internal_monitor", "raw_description": "Monthly audit report not submitted."},
    ]

    tier1 = Tier1RuleFilter(mock_ir)
    filtered = tier1.filter_events(mock_raw_events)

    print(f"\nTier-1 filtered events: {len(filtered)}")
    for e in filtered:
        print(f"  {e['event_id']} -> template: {e['matched_template_id']}")

    if filtered:
        result_c = pipeline.run_phase_c(filtered_events=filtered, ir_json=json.dumps(mock_ir, indent=2, ensure_ascii=False))
        print(f"\nPhase C passed: {result_c.self_check_passed}")
        if result_c.self_check_failures:
            print(f"Phase C failures: {result_c.self_check_failures}")

    pipeline.export_results("./slcml_output")

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"\nPhases executed: {list(pipeline.results.keys())}")
    print("Output exported to ./slcml_output/")
