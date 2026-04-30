"""SLCML IR Schema Validator v2.0 — Structural integrity verification for SLCML intermediate representation."""

from typing import List, Tuple, Dict, Set
import re


class SchemaValidationError:
    def __init__(self, field: str, error_type: str, message: str):
        self.field = field
        self.error_type = error_type
        self.message = message

    def __repr__(self):
        return f"[{self.error_type}] {self.field}: {self.message}"


class SLCMLSchemaValidator:
    """Validates SLCML IR against the quintuple output schema specification."""

    VALID_ROLES = {
        "DataProvider", "DataConsumer", "ModelTrainer", "ModelUser",
        "Auditor", "Arbitrator", "Regulator", "Beneficiary",
        "Guarantor", "ThirdPartyEvaluator"
    }

    VALID_OBJECT_TYPES = {
        "Dataset", "Model", "ModelParameters", "ComputeResource",
        "APIAccess", "IntellectualProperty", "DigitalAsset",
        "ServiceRight", "EvaluationReport", "DerivativeWork"
    }

    VALID_CONDITION_CATEGORIES = {
        "Temporal", "Geographic", "Performance", "Procedural",
        "Quantitative", "Qualitative", "Consent", "Compliance", "TriggerEvent"
    }

    VALID_BREACH_TYPES = {
        "Geographic_Breach", "Temporal_Breach", "Performance_Breach",
        "Privacy_Breach", "Authorization_Breach", "Quality_Breach",
        "Procedural_Breach", "Payment_Breach", "Confidentiality_Breach"
    }

    VALID_RULE_TYPES = {
        "Obligation", "Prohibition", "Permission", "Penalty",
        "Reward", "Termination", "Exception"
    }

    VALID_SEVERITY_LEVELS = {"Minor", "Moderate", "Major", "Critical"}

    VALID_TEMPLATE_LAYERS = {
        "FactStatement", "BreachIdentification",
        "ProceduralRecord", "JudicialSummary"
    }

    VALID_CREDENTIAL_TYPES = {
        "BusinessLicense", "MedicalLicense", "DataLicense",
        "QualificationCert", "IdentityVerification", "None"
    }

    VALID_EVALUATION_TIMINGS = {
        "BeforeExecution", "DuringExecution", "AfterExecution", "Continuous"
    }

    VALID_SOURCE_TYPES = {"OnChain", "Oracle", "ManualInput", "SystemGenerated"}

    CLAUSE_INDEX_PATTERN = re.compile(r'^Clause_\d+(\.\d+)?$')
    CONDITION_ID_PATTERN = re.compile(r'^COND_[A-Z]+_\d+$')
    RULE_ID_PATTERN = re.compile(r'^RULE_[A-Z]+_\d+$')
    TEMPLATE_ID_PATTERN = re.compile(r'^EVID_[A-Z]+_\d+$')

    def validate(self, ir_json: Dict) -> Tuple[bool, List[SchemaValidationError]]:
        """Execute full schema validation. Returns (is_valid, error_list)."""
        errors: List[SchemaValidationError] = []

        required_top = ["Subject", "Object", "Condition", "Rule", "Audit"]
        for field in required_top:
            if field not in ir_json:
                errors.append(SchemaValidationError(field, "MISSING_FIELD", f"Missing required top-level field: {field}"))

        if len(errors) > 2:
            return (False, errors)

        all_clause_indices: Set[str] = set()
        all_condition_ids: Set[str] = set()
        all_rule_ids: Set[str] = set()

        for i, s in enumerate(ir_json.get("Subject", [])):
            prefix = f"Subject[{i}]"
            self._check_required_str(s, "subject_id", prefix, errors)
            role = s.get("role", "")
            if role not in self.VALID_ROLES:
                errors.append(SchemaValidationError(f"{prefix}.role", "INVALID_ENUM", f"Role '{role}' not in valid set {self.VALID_ROLES}"))
            self._check_required_str(s, "natural_language_description", prefix, errors)
            self._check_required_str(s, "address_placeholder", prefix, errors)
            cred_type = s.get("credential_type", "")
            if cred_type and cred_type not in self.VALID_CREDENTIAL_TYPES:
                errors.append(SchemaValidationError(f"{prefix}.credential_type", "INVALID_ENUM", f"Credential type '{cred_type}' not in valid set"))
            rep = s.get("initial_reputation_score", 100)
            if not (0 <= rep <= 100):
                errors.append(SchemaValidationError(f"{prefix}.initial_reputation_score", "OUT_OF_RANGE", f"Reputation {rep} outside [0, 100]"))
            self._check_source_clause(s, prefix, errors, all_clause_indices)

        for i, o in enumerate(ir_json.get("Object", [])):
            prefix = f"Object[{i}]"
            self._check_required_str(o, "object_id", prefix, errors)
            otype = o.get("object_type", "")
            if otype not in self.VALID_OBJECT_TYPES:
                errors.append(SchemaValidationError(f"{prefix}.object_type", "INVALID_ENUM", f"Object type '{otype}' not in valid set"))
            self._check_required_str(o, "natural_language_description", prefix, errors)
            qa = o.get("quantifiable_attributes", {})
            if qa:
                slevel = qa.get("sensitivity_level", 0)
                if not (1 <= slevel <= 5):
                    errors.append(SchemaValidationError(f"{prefix}.quantifiable_attributes.sensitivity_level", "OUT_OF_RANGE", f"Sensitivity {slevel} outside [1, 5]"))
                budget = qa.get("privacy_budget_total", 0)
                if budget < 0:
                    errors.append(SchemaValidationError(f"{prefix}.quantifiable_attributes.privacy_budget_total", "INVALID_VALUE", "Privacy budget cannot be negative"))
            else:
                errors.append(SchemaValidationError(f"{prefix}.quantifiable_attributes", "MISSING_FIELD", "Missing quantifiable attributes structure"))
            jc = o.get("jurisdiction_constraints", {})
            if not jc:
                errors.append(SchemaValidationError(f"{prefix}.jurisdiction_constraints", "MISSING_FIELD", "Missing jurisdiction constraints structure"))
            self._check_source_clause(o, prefix, errors, all_clause_indices)

        for i, c in enumerate(ir_json.get("Condition", [])):
            prefix = f"Condition[{i}]"
            cid = c.get("condition_id", "")
            if cid:
                all_condition_ids.add(cid)
                if not self.CONDITION_ID_PATTERN.match(cid):
                    errors.append(SchemaValidationError(f"{prefix}.condition_id", "INVALID_FORMAT", f"Condition ID '{cid}' does not match COND_TYPE_NUM format"))
            else:
                errors.append(SchemaValidationError(f"{prefix}.condition_id", "EMPTY_FIELD", "Condition ID must not be empty"))
            cat = c.get("condition_category", "")
            if cat not in self.VALID_CONDITION_CATEGORIES:
                errors.append(SchemaValidationError(f"{prefix}.condition_category", "INVALID_ENUM", f"Condition category '{cat}' not in valid set"))
            self._check_required_str(c, "natural_language_expression", prefix, errors)
            self._check_required_str(c, "formal_predicate", prefix, errors)
            ds = c.get("data_source", {})
            if ds:
                st = ds.get("source_type", "")
                if st and st not in self.VALID_SOURCE_TYPES:
                    errors.append(SchemaValidationError(f"{prefix}.data_source.source_type", "INVALID_ENUM", f"Source type '{st}' not in valid set"))
            timing = c.get("evaluation_timing", "")
            if timing and timing not in self.VALID_EVALUATION_TIMINGS:
                errors.append(SchemaValidationError(f"{prefix}.evaluation_timing", "INVALID_ENUM", f"Evaluation timing '{timing}' not in valid set"))
            self._check_source_clause(c, prefix, errors, all_clause_indices)

        for i, r in enumerate(ir_json.get("Rule", [])):
            prefix = f"Rule[{i}]"
            rid = r.get("rule_id", "")
            if rid:
                all_rule_ids.add(rid)
                if not self.RULE_ID_PATTERN.match(rid):
                    errors.append(SchemaValidationError(f"{prefix}.rule_id", "INVALID_FORMAT", f"Rule ID '{rid}' does not match RULE_TYPE_NUM format"))
            else:
                errors.append(SchemaValidationError(f"{prefix}.rule_id", "EMPTY_FIELD", "Rule ID must not be empty"))
            rtype = r.get("rule_type", "")
            if rtype and rtype not in self.VALID_RULE_TYPES:
                errors.append(SchemaValidationError(f"{prefix}.rule_type", "INVALID_ENUM", f"Rule type '{rtype}' not in valid set"))
            trigger_ids = r.get("trigger_condition_ids", [])
            for tid in trigger_ids:
                if all_condition_ids and tid not in all_condition_ids:
                    errors.append(SchemaValidationError(f"{prefix}.trigger_condition_ids", "REFERENCE_ERROR", f"Trigger condition ID '{tid}' not found in Condition set"))
            bc = r.get("breach_classification", {})
            if bc:
                btype = bc.get("breach_type", "")
                if btype and btype not in self.VALID_BREACH_TYPES:
                    errors.append(SchemaValidationError(f"{prefix}.breach_classification.breach_type", "INVALID_ENUM", f"Breach type '{btype}' not in valid set"))
                severity = bc.get("severity_level", "")
                if severity and severity not in self.VALID_SEVERITY_LEVELS:
                    errors.append(SchemaValidationError(f"{prefix}.breach_classification.severity_level", "INVALID_ENUM", f"Severity '{severity}' not in valid set"))
            self._check_source_clause(r, prefix, errors, all_clause_indices)

            pj = r.get("procedural_justice")
            if pj is None:
                errors.append(SchemaValidationError(f"{prefix}.procedural_justice", "MISSING_FIELD", "Missing procedural justice structure — all rules require three-phase control flow"))
            else:
                fp = pj.get("freeze_phase")
                if not fp:
                    errors.append(SchemaValidationError(f"{prefix}.procedural_justice.freeze_phase", "MISSING_FIELD", "Missing freeze phase"))
                else:
                    self._check_required_str(fp, "freeze_action_description", f"{prefix}.procedural_justice.freeze_phase", errors)
                    self._check_required_str(fp, "freeze_timestamp_field", f"{prefix}.procedural_justice.freeze_phase", errors)
                cp = pj.get("challenge_phase")
                if not cp:
                    errors.append(SchemaValidationError(f"{prefix}.procedural_justice.challenge_phase", "MISSING_FIELD", "Missing challenge phase"))
                else:
                    self._check_required_str(cp, "challenge_window_duration", f"{prefix}.procedural_justice.challenge_phase", errors)
                    if not cp.get("challenge_window_seconds"):
                        errors.append(SchemaValidationError(f"{prefix}.procedural_justice.challenge_phase.challenge_window_seconds", "EMPTY_FIELD", "Challenge window seconds must not be empty"))
                    cs = cp.get("challenge_submission", {})
                    if not cs:
                        errors.append(SchemaValidationError(f"{prefix}.procedural_justice.challenge_phase.challenge_submission", "MISSING_FIELD", "Missing challenge submission structure"))
                ap = pj.get("adjudication_phase")
                if not ap:
                    errors.append(SchemaValidationError(f"{prefix}.procedural_justice.adjudication_phase", "MISSING_FIELD", "Missing adjudication phase"))
                else:
                    auth = ap.get("adjudication_authority", {})
                    if not auth:
                        errors.append(SchemaValidationError(f"{prefix}.procedural_justice.adjudication_phase.adjudication_authority", "MISSING_FIELD", "Missing adjudication authority definition"))
                    outcomes = ap.get("adjudication_outcomes", [])
                    if not outcomes:
                        errors.append(SchemaValidationError(f"{prefix}.procedural_justice.adjudication_phase.adjudication_outcomes", "MISSING_FIELD", "Missing adjudication outcome paths"))
                    if not ap.get("default_outcome_on_timeout"):
                        errors.append(SchemaValidationError(f"{prefix}.procedural_justice.adjudication_phase.default_outcome_on_timeout", "EMPTY_FIELD", "Missing default timeout outcome"))

            smt = r.get("state_machine_transition", {})
            if not smt:
                errors.append(SchemaValidationError(f"{prefix}.state_machine_transition", "MISSING_FIELD", "Missing state machine transition definition"))

        audit = ir_json.get("Audit", {})
        if not audit:
            errors.append(SchemaValidationError("Audit", "MISSING_FIELD", "Missing audit structure"))
        else:
            templates = audit.get("evidence_templates", [])
            if not templates:
                errors.append(SchemaValidationError("Audit.evidence_templates", "MISSING_FIELD", "Missing evidence templates"))
            else:
                covered_layers = set()
                for j, t in enumerate(templates):
                    tp = f"Audit.evidence_templates[{j}]"
                    tid = t.get("template_id", "")
                    if tid and not self.TEMPLATE_ID_PATTERN.match(tid):
                        errors.append(SchemaValidationError(f"{tp}.template_id", "INVALID_FORMAT", f"Template ID '{tid}' does not match EVID_TYPE_NUM format"))
                    layer = t.get("template_layer", "")
                    if layer not in self.VALID_TEMPLATE_LAYERS:
                        errors.append(SchemaValidationError(f"{tp}.template_layer", "INVALID_ENUM", f"Template layer '{layer}' not in valid set"))
                    else:
                        covered_layers.add(layer)
                    self._check_required_str(t, "template_content", tp, errors)
                    mappings = t.get("placeholder_mappings", [])
                    if not mappings:
                        errors.append(SchemaValidationError(f"{tp}.placeholder_mappings", "MISSING_FIELD", "Missing placeholder mappings"))
                missing_layers = self.VALID_TEMPLATE_LAYERS - covered_layers
                if missing_layers:
                    errors.append(SchemaValidationError("Audit.evidence_templates", "INCOMPLETE_COVERAGE", f"Audit templates missing layers: {missing_layers}"))

            registry = audit.get("clause_index_registry", [])
            if not registry:
                errors.append(SchemaValidationError("Audit.clause_index_registry", "MISSING_FIELD", "Missing clause index registry (required for bidirectional semantic anchoring)"))
            else:
                registered_clauses = set()
                for k, entry in enumerate(registry):
                    rp = f"Audit.clause_index_registry[{k}]"
                    ci = entry.get("clause_index", "")
                    if ci:
                        registered_clauses.add(ci)
                        if not self.CLAUSE_INDEX_PATTERN.match(ci):
                            errors.append(SchemaValidationError(f"{rp}.clause_index", "INVALID_FORMAT", f"Clause index '{ci}' does not match Clause_X.Y format"))
                for clause_idx in all_clause_indices:
                    if clause_idx and clause_idx not in registered_clauses:
                        errors.append(SchemaValidationError("Audit.clause_index_registry", "REFERENCE_ERROR", f"Rule references '{clause_idx}' but it is not registered in clause index registry"))

            log_schema = audit.get("judicial_log_schema", {})
            if not log_schema:
                errors.append(SchemaValidationError("Audit.judicial_log_schema", "MISSING_FIELD", "Missing on-chain judicial log schema definition"))

        is_valid = len(errors) == 0
        return (is_valid, errors)

    def _check_required_str(self, obj: Dict, key: str, prefix: str, errors: List[SchemaValidationError]):
        if not obj.get(key):
            errors.append(SchemaValidationError(f"{prefix}.{key}", "EMPTY_FIELD", f"{key} must not be empty"))

    def _check_source_clause(self, obj: Dict, prefix: str, errors: List[SchemaValidationError], collector: Set[str]):
        clause = obj.get("source_clause_index", "")
        if not clause:
            errors.append(SchemaValidationError(f"{prefix}.source_clause_index", "EMPTY_FIELD", "source_clause_index must not be empty (required for bidirectional semantic anchoring)"))
        elif not self.CLAUSE_INDEX_PATTERN.match(clause):
            errors.append(SchemaValidationError(f"{prefix}.source_clause_index", "INVALID_FORMAT", f"Clause index '{clause}' does not match Clause_X.Y format"))
        else:
            collector.add(clause)

    def print_report(self, errors: List[SchemaValidationError]):
        print("\n" + "=" * 60)
        print("  SLCML Schema Validation Report v2.0")
        print("=" * 60)

        if not errors:
            print("\n  Schema validation PASSED:")
            print("     - All fields complete and type-consistent")
            print("     - Three-phase procedural justice structure verified")
            print("     - Four-layer audit template coverage complete")
            print("     - Clause index cross-reference consistent")
            print("=" * 60)
            return

        by_type = {}
        for e in errors:
            by_type.setdefault(e.error_type, []).append(e)

        print(f"\n  Schema validation FAILED: {len(errors)} issues found\n")
        for etype, elist in by_type.items():
            print(f"  [{etype}] ({len(elist)} issues)")
            for e in elist:
                print(f"    {e.field}: {e.message}")
            print()
        print("=" * 60)
