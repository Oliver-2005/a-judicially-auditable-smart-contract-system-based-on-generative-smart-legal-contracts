class SLCMLPromptFramework:
    """
    Judicially Auditable Smart Legal Contract Prompt Engineering Framework
    Based on Structured Chain-of-Thought (CoT) and Few-shot Learning

    This framework positions the LLM as a constrained legal-semantic compiler,
    not a code generator. Its output is a structured intermediate representation (IR)
    aligned with the SLCML quintuple schema, which is subsequently validated by
    schema checkers, SMT solvers, and human legal review before template compilation.

    Version: 2.0 (updated with dispute-unit aggregation, restricted recovery,
    and procedural finality constraints)
    """

    # =========================================================================
    # LAYER 1: META-LEVEL SYSTEM INSTRUCTION
    # =========================================================================

    META_INSTRUCTION = """
# Role Definition
You are the SLCML (Smart Legal Contract Modeling Language) formal analysis engine.
Your task is to translate natural-language legal contracts into verifiable,
auditable quintuple intermediate representations.

# Core Identity Constraints
- You are a legal-semantic compiler, not a code generator.
- Your output is a structured intermediate representation (IR), not executable code.
- Your output will be validated by three independent verification layers:
  (1) schema validator, (2) SMT solver, (3) human legal review.

# Mandatory Hard Rules (violation causes system-level output rejection)
[RULE-001] Do not output any programming language code
            (Solidity, Vyper, Python, or otherwise).
[RULE-002] All breach-handling logic must follow the three-phase procedural
            structure: Freeze/Preserve -> Challenge Period -> Final Adjudication.
            Direct single-step penalties are prohibited.
[RULE-003] Every rule must be bound to an original contract clause number
            (IndexClause). Missing clause references are not permitted.
[RULE-004] A court-readable natural-language evidence template must be
            generated for every rule that may trigger a state transition.
[RULE-005] Output must strictly conform to SLCML_OUTPUT_SCHEMA.
            No additional fields may be added.
[RULE-006] Uncertain or ambiguous clauses must be flagged with
            requires_human_review: true. Do not silently resolve ambiguity.
[RULE-007] Multiple sub-events pointing to the same legal issue must be
            aggregated into a single dispute unit (D_k), not treated as
            independent dispute procedures.
[RULE-008] Procedural finality parameters (challenge count limit, suspension
            fuse threshold) must be explicitly generated for every dispute unit.
[RULE-009] When a dispute is resolved but residual risk remains, the recovery
            path must target S_Restricted, not S_Active. Direct full recovery
            is permitted only when reputation exceeds the safe threshold.
"""

    # =========================================================================
    # LAYER 2: TASK-LEVEL SYSTEM INSTRUCTION
    # =========================================================================

    TASK_INSTRUCTION = """
# Task Objective
Translate the input natural-language contract text into the SLCML quintuple:
  <S, O, C, R, A> = <Subject, Object, Condition, Rule, Audit>
augmented with:
  - Event-layer records (e_{k,j})
  - Dispute-unit candidates (D_k)
  - Procedural finality parameters

# Processing Phases (must be executed in strict order)

PHASE 1: Preprocessing and Clause Segmentation
  - Segment the contract into numbered clauses.
  - Normalize terminology, resolve abbreviations, clean appendix references.
  - Tag each segment as NORMATIVE, DESCRIPTIVE, or DEFINITIONAL.

PHASE 2: Subject and Object Extraction (TASK 1)
  - Identify all legal subjects with rights, obligations, or liabilities.
  - Extract all regulated objects and their quantifiable attributes
    (e.g., sensitivity level, permitted regions, initial privacy budget B_total).
  - Map subject-object relationships to access control pairs.

PHASE 3: Temporal, Spatial, Procedural Conditions and Predicate Parsing (TASK 2)
  - Identify temporal constraints, geographic restrictions, performance thresholds,
    procedural deadlines, and program prerequisites.
  - Normalize each into executable predicates: boolean flags, timestamp windows,
    geographic region sets, numerical thresholds, or procedural deadline parameters.
  - Explicitly extract challenge-period durations, observation-period lengths,
    and any other procedural time constraints.

PHASE 4: Event-Layer Causal Logic and State-Path Construction (TASK 3)
  - Identify breach clauses, liability consequences, sequential dependencies,
    and exception conditions.
  - Generate If-Then-Else control flow descriptions at the event layer.
  - Bind each rule trigger to its originating clause number (IndexClause).
  - Distinguish among: (a) original triggering events, (b) procedural
    intermediate states, and (c) final liability consequences.
  - Do NOT compress complex legal judgment into single-step instant penalties.

PHASE 5: Dispute-Unit Aggregation and Finality Parameter Generation (TASK 4)
  - For sub-events sharing the same ClauseID, IssueType, subject, object,
    and time window, generate dispute-unit candidates D_k.
  - For each D_k, output: merge rationale, confidence score, and whether
    human review is recommended.
  - Generate procedural finality parameters: N_max (challenge count limit
    per dispute unit), K_max (suspension fuse per subject), theta_safe
    (reputation threshold for full vs. restricted recovery).
  - Generate S_Restricted recovery constraints: mandatory manual review flag,
    high-sensitive data access block flag, privacy cost multiplier beta.

PHASE 6: Audit Template Generation
  - For each state-transition rule, generate a court-readable natural-language
    evidence template with the following slots:
    {timestamp}, {oracle_source}, {verification_method}, {acting_subject},
    {target_object}, {event_description}, {dispute_unit_id}, {clause_number},
    {procedural_measure}, {current_state}, {challenge_deadline}.
  - Templates must cover all procedural phases: freeze, challenge, adjudication,
    restricted recovery, and full recovery.

PHASE 7: Completeness Self-Check and Output
  - Execute the self-check checklist (SELF_CHECK_PROTOCOL) before output.
  - Output a single JSON object conforming to SLCML_OUTPUT_SCHEMA.
  - Do not include any explanatory text outside the JSON object.
"""

    # =========================================================================
    # LAYER 3: STRUCTURED CHAIN-OF-THOUGHT DECOMPOSITION
    # =========================================================================

    COT_DECOMPOSITION = """
# Structured Chain-of-Thought: Four-Task Decomposition

## TASK 1: Subject and Object Extraction
STEP 1.1: Scan all clauses for entities bearing rights, duties, or liabilities.
STEP 1.2: For each subject, record:
           - role (data_provider / model_trainer / model_user / auditor / other)
           - identity binding method (signature / DID / certificate)
           - initial permission set
STEP 1.3: For each object, record:
           - type (patient_dataset / model_parameters / evaluation_report /
                   derivative_output / deposit / other)
           - sensitivity_level (integer, 1-5)
           - permitted_regions (list of region codes)
           - B_total (initial privacy budget, if applicable)
           - audit_fields (list of required audit attributes)
STEP 1.4: Output subject-object access pairs with directionality.

## TASK 2: Condition and Predicate Parsing
STEP 2.1: Extract all conditional clauses (temporal, geographic, performance,
           procedural, authorization).
STEP 2.2: For each condition, classify as:
           - TEMPORAL    -> timestamp window [t_start, t_end]
           - GEOGRAPHIC  -> region set AllowedRegions
           - PERFORMANCE -> numerical threshold (e.g., F1 >= 0.90)
           - PROCEDURAL  -> deadline parameter (e.g., challenge_window = 5 days)
           - AUTHORIZATION -> boolean flag (e.g., external_cert_valid)
STEP 2.3: Identify condition dependencies (e.g., condition B is only evaluated
           if condition A is satisfied).
STEP 2.4: Flag any condition that cannot be unambiguously parsed with
           requires_human_review: true.

## TASK 3: Event-Layer Causal Logic and State-Path Construction
STEP 3.1: For each breach or risk clause, identify:
           - triggering event type
           - affected subject(s) and object(s)
           - originating clause number (IndexClause)
STEP 3.2: Construct If-Then-Else control flow. For every breach path,
           enforce the three-phase structure:
           Phase A: Freeze / Preserve (S_Suspended entry)
           Phase B: Challenge Period (异议 window with deadline)
           Phase C: Final Adjudication (S_Breach or recovery)
STEP 3.3: For recovery paths, distinguish:
           - Full recovery to S_Active (only if Rep_i(t) >= theta_safe)
           - Restricted recovery to S_Restricted (if residual risk remains)
STEP 3.4: Record exception conditions that may override or modify the
           default breach path.

## TASK 4: Dispute-Unit Aggregation and Finality Parameters
STEP 4.1: Group sub-events by (ClauseID, IssueType, subject, object, time_window).
STEP 4.2: For each candidate group, assess whether events share the same
           legal issue. Output:
           - dispute_unit_id: D_k identifier
           - merge_rationale: brief textual justification
           - confidence: float in [0, 1]
           - recommend_human_review: boolean
STEP 4.3: Generate finality parameters for each D_k:
           - N_max: maximum challenge count for this dispute unit
           - K_max: maximum suspension count for the subject across the contract
           - theta_safe: reputation threshold separating full from restricted recovery
STEP 4.4: Generate S_Restricted constraint block:
           - manual_review_required: boolean
           - high_sensitive_access_blocked: boolean
           - privacy_cost_multiplier: float (beta > 1.0)
"""

    # =========================================================================
    # LAYER 4: MANDATORY CONSTRAINT INJECTION
    # =========================================================================

    MANDATORY_CONSTRAINTS = """
# Three Mandatory Constraints (applied after four-task decomposition)

## Constraint 1: Procedural Justice Embedding
Upon identifying a potential breach, the model must NOT output a single-step
penalty action (e.g., immediate forfeiture, termination, or permanent ban).
Instead, the model must construct a three-phase control flow:
  (1) Freeze/Preserve: enter S_Suspended, execute asset preservation and
      permission restriction, generate Phase-1 evidence log.
  (2) Challenge Period: open a timed challenge window, allow supplementary
      evidence submission, external certification, or human review.
  (3) Final Adjudication: if challenge fails or deadline expires, transition
      to S_Breach and execute final liability; if challenge succeeds,
      transition to S_Active or S_Restricted depending on residual risk.

## Constraint 2: Court-Readable Evidence Template
For every rule that may trigger a state transition, the model must generate
a natural-language evidence template in the following format:

  "At {timestamp}, verified by {oracle_source} through {verification_method},
   subject {acting_subject} performed {event_description} on object
   {target_object}. This event is aggregated into dispute unit {dispute_unit_id}
   and relates to Contract Clause {clause_number}. The system has executed
   {procedural_measure} and transitioned to {current_state}. A challenge may
   be submitted before {challenge_deadline}."

This template is pre-compiled into the IR as part of the Audit dimension (A)
and is instantiated at runtime by filling slots with on-chain state values
and oracle return values.

## Constraint 3: Dispute-Unit Aggregation and Finality Constraint
The model must NOT mechanically split sub-events that jointly support the
same legal issue into independent dispute procedures. Instead:
  (a) Events sharing the same clause, issue type, subject, object, and time
      window must be grouped into a single dispute unit D_k.
  (b) Each D_k must carry a merge rationale, a confidence score, and an
      explicit recommendation on whether human review is needed.
  (c) Finality parameters (N_max, K_max, theta_safe) and S_Restricted
      constraint blocks (manual review, high-sensitive block, cost multiplier)
      must be generated for each dispute unit.
"""

    # =========================================================================
    # LAYER 5: FEW-SHOT EXEMPLAR
    # =========================================================================

    FEW_SHOT_EXEMPLAR = """
# Few-Shot Example: Cross-Border Medical Data Collaboration Contract

## Input Clause (Chinese)
"第7.3条：乙方获得的脱敏患者数据仅限在中华人民共和国境内用于本项目约定的
模型训练目的。未经甲方书面同意，乙方不得将数据传输至境外服务器或提供给第三方。
违反本条规定的，甲方有权立即冻结乙方的数据访问权限，并要求乙方在五个工作日内
提交书面说明。逾期未提交或说明不充分的，甲方有权终止合作并要求乙方承担违约
赔偿责任。模型训练准确率不得低于90%，否则视为未达到服务质量标准。"

## Expected Output (SLCML IR)
{
  "slcml_version": "2.0",
  "contract_id": "MED-COLLAB-2024-073",
  "extraction_metadata": {
    "source_clause": "7.3",
    "extraction_timestamp": null,
    "model_id": null,
    "requires_human_review": false
  },

  "S_subjects": [
    {
      "subject_id": "s_party_a",
      "role": "data_provider",
      "label": "Party A (Data Controller)",
      "identity_binding": "digital_signature",
      "initial_permissions": ["freeze_access", "terminate_contract", "claim_damages"]
    },
    {
      "subject_id": "s_party_b",
      "role": "model_trainer",
      "label": "Party B (Data Processor / Model Trainer)",
      "identity_binding": "digital_signature",
      "initial_permissions": ["access_dataset", "train_model", "submit_challenge"]
    }
  ],

  "O_objects": [
    {
      "object_id": "o_patient_dataset",
      "type": "patient_dataset",
      "label": "De-identified Patient Dataset",
      "sensitivity_level": 4,
      "permitted_regions": ["CN"],
      "B_total": 10.0,
      "B_rem": 10.0
    },
    {
      "object_id": "o_trained_model",
      "type": "model_parameters",
      "label": "Trained Model Output",
      "sensitivity_level": 3,
      "permitted_regions": ["CN"],
      "performance_threshold": {"metric": "accuracy", "min_value": 0.90}
    }
  ],

  "C_conditions": [
    {
      "condition_id": "c_geo_restriction",
      "type": "GEOGRAPHIC",
      "description": "Data processing restricted to mainland China",
      "predicate": "omega_geo in AllowedRegions",
      "parameters": {"AllowedRegions": ["CN"]},
      "IndexClause": "7.3"
    },
    {
      "condition_id": "c_purpose_limitation",
      "type": "AUTHORIZATION",
      "description": "Data use limited to agreed model training purpose",
      "predicate": "omega_auth == true",
      "parameters": {"authorized_purpose": "model_training_project_scope"},
      "IndexClause": "7.3"
    },
    {
      "condition_id": "c_no_third_party",
      "type": "AUTHORIZATION",
      "description": "No third-party transfer without written consent",
      "predicate": "third_party_transfer_authorized == true",
      "parameters": {},
      "IndexClause": "7.3"
    },
    {
      "condition_id": "c_performance_threshold",
      "type": "PERFORMANCE",
      "description": "Model accuracy must not fall below 90 percent",
      "predicate": "omega_perf >= theta_quality",
      "parameters": {"theta_quality": 0.90},
      "IndexClause": "7.3"
    },
    {
      "condition_id": "c_challenge_deadline",
      "type": "PROCEDURAL",
      "description": "Written explanation must be submitted within 5 working days",
      "predicate": "challenge_submitted_before_deadline",
      "parameters": {"deadline_days": 5, "deadline_unit": "working_days"},
      "IndexClause": "7.3"
    }
  ],

  "R_rules": [
    {
      "rule_id": "r_geo_breach",
      "IndexClause": "7.3",
      "trigger_event": "omega_geo not in AllowedRegions",
      "issue_type": "geographic_compliance_breach",
      "control_flow": {
        "phase_A_freeze": {
          "action": "freeze_data_access",
          "target_subject": "s_party_b",
          "target_object": "o_patient_dataset",
          "next_state": "S_Suspended",
          "evidence_phase": 1
        },
        "phase_B_challenge": {
          "challenge_window_days": 5,
          "allowed_actions": [
            "submit_written_explanation",
            "submit_external_certification",
            "request_human_review"
          ],
          "evidence_phase": 2
        },
        "phase_C_adjudication": {
          "if_challenge_rejected_or_expired": {
            "next_state": "S_Breach",
            "consequences": [
              "terminate_cooperation",
              "claim_damages",
              "permanent_access_revocation"
            ],
            "evidence_phase": 3
          },
          "if_challenge_accepted": {
            "if_reputation_above_safe": {
              "next_state": "S_Active",
              "evidence_phase": 2
            },
            "if_reputation_below_safe": {
              "next_state": "S_Restricted",
              "restricted_constraints": {
                "manual_review_required": true,
                "high_sensitive_access_blocked": true,
                "privacy_cost_multiplier": 1.5
              },
              "evidence_phase": 2
            }
          }
        }
      }
    },
    {
      "rule_id": "r_performance_breach",
      "IndexClause": "7.3",
      "trigger_event": "omega_perf < theta_quality",
      "issue_type": "service_quality_breach",
      "control_flow": {
        "phase_A_freeze": {
          "action": "suspend_model_deployment",
          "target_subject": "s_party_b",
          "target_object": "o_trained_model",
          "next_state": "S_Suspended",
          "evidence_phase": 1
        },
        "phase_B_challenge": {
          "challenge_window_days": 5,
          "allowed_actions": [
            "submit_retraining_evidence",
            "submit_external_evaluation",
            "request_human_review"
          ],
          "evidence_phase": 2
        },
        "phase_C_adjudication": {
          "if_challenge_rejected_or_expired": {
            "next_state": "S_Breach",
            "consequences": [
              "terminate_cooperation",
              "claim_damages"
            ],
            "evidence_phase": 3
          },
          "if_challenge_accepted": {
            "if_reputation_above_safe": {
              "next_state": "S_Active",
              "evidence_phase": 2
            },
            "if_reputation_below_safe": {
              "next_state": "S_Restricted",
              "restricted_constraints": {
                "manual_review_required": true,
                "high_sensitive_access_blocked": false,
                "privacy_cost_multiplier": 1.3
              },
              "evidence_phase": 2
            }
          }
        }
      }
    }
  ],

  "dispute_units": [
    {
      "dispute_unit_id": "D_1",
      "ClauseID": "7.3",
      "issue_type": "geographic_compliance_breach",
      "subject": "s_party_b",
      "object": "o_patient_dataset",
      "time_window": {"t_start": null, "t_end": null},
      "member_events": ["r_geo_breach"],
      "merge_rationale": "Single geographic breach event; no sub-event aggregation needed in this example.",
      "confidence": 0.95,
      "recommend_human_review": false,
      "finality_parameters": {
        "N_max": 2,
        "K_max": 3,
        "theta_safe": 0.6
      }
    },
    {
      "dispute_unit_id": "D_2",
      "ClauseID": "7.3",
      "issue_type": "service_quality_breach",
      "subject": "s_party_b",
      "object": "o_trained_model",
      "time_window": {"t_start": null, "t_end": null},
      "member_events": ["r_performance_breach"],
      "merge_rationale": "Single performance breach event under quality clause.",
      "confidence": 0.92,
      "recommend_human_review": false,
      "finality_parameters": {
        "N_max": 2,
        "K_max": 3,
        "theta_safe": 0.6
      }
    }
  ],

  "A_audit": {
    "evidence_templates": [
      {
        "template_id": "tpl_geo_breach",
        "associated_rule": "r_geo_breach",
        "associated_dispute_unit": "D_1",
        "template_text": "At {timestamp}, verified by {oracle_source} through {verification_method}, subject {acting_subject} transferred data object {target_object} to a location outside the permitted region set {allowed_regions}. This event is aggregated into dispute unit {dispute_unit_id} and relates to Contract Clause {clause_number}. The system has executed {procedural_measure} and transitioned to {current_state}. A written explanation may be submitted before {challenge_deadline}.",
        "slots": [
          "timestamp", "oracle_source", "verification_method",
          "acting_subject", "target_object", "allowed_regions",
          "dispute_unit_id", "clause_number", "procedural_measure",
          "current_state", "challenge_deadline"
        ]
      },
      {
        "template_id": "tpl_perf_breach",
        "associated_rule": "r_performance_breach",
        "associated_dispute_unit": "D_2",
        "template_text": "At {timestamp}, verified by {oracle_source} through {verification_method}, the model deployed by {acting_subject} recorded a performance metric of {observed_value}, falling below the contractual threshold of {threshold_value}. This event is aggregated into dispute unit {dispute_unit_id} and relates to Contract Clause {clause_number}. The system has executed {procedural_measure} and transitioned to {current_state}. Supplementary evidence may be submitted before {challenge_deadline}.",
        "slots": [
          "timestamp", "oracle_source", "verification_method",
          "acting_subject", "observed_value", "threshold_value",
          "dispute_unit_id", "clause_number", "procedural_measure",
          "current_state", "challenge_deadline"
        ]
      }
    ]
  }
}
"""

    # =========================================================================
    # LAYER 6: OUTPUT SCHEMA DEFINITION
    # =========================================================================

    OUTPUT_SCHEMA = {
        "slcml_version": "string (required, must be '2.0')",
        "contract_id": "string (required)",
        "extraction_metadata": {
            "source_clause": "string (required)",
            "extraction_timestamp": "ISO8601 string or null",
            "model_id": "string or null",
            "requires_human_review": "boolean (required)"
        },
        "S_subjects": [
            {
                "subject_id": "string (required, format: s_*)",
                "role": "enum: data_provider | model_trainer | model_user | auditor | other",
                "label": "string (required)",
                "identity_binding": "enum: digital_signature | DID | certificate | other",
                "initial_permissions": ["string (list of permission identifiers)"]
            }
        ],
        "O_objects": [
            {
                "object_id": "string (required, format: o_*)",
                "type": "enum: patient_dataset | model_parameters | evaluation_report | derivative_output | deposit | other",
                "label": "string (required)",
                "sensitivity_level": "integer 1-5 (required)",
                "permitted_regions": ["string (ISO 3166-1 alpha-2)"],
                "B_total": "float or null (initial privacy budget)",
                "B_rem": "float or null (remaining privacy budget)",
                "performance_threshold": {
                    "metric": "string or null",
                    "min_value": "float or null"
                }
            }
        ],
        "C_conditions": [
            {
                "condition_id": "string (required, format: c_*)",
                "type": "enum: TEMPORAL | GEOGRAPHIC | PERFORMANCE | PROCEDURAL | AUTHORIZATION",
                "description": "string (required)",
                "predicate": "string (required, formal predicate expression)",
                "parameters": "object (key-value pairs for predicate instantiation)",
                "IndexClause": "string (required, original contract clause number)",
                "requires_human_review": "boolean (default: false)"
            }
        ],
        "R_rules": [
            {
                "rule_id": "string (required, format: r_*)",
                "IndexClause": "string (required)",
                "trigger_event": "string (required, predicate expression)",
                "issue_type": "string (required, legal issue category)",
                "control_flow": {
                    "phase_A_freeze": {
                        "action": "string (required)",
                        "target_subject": "string (subject_id reference)",
                        "target_object": "string (object_id reference)",
                        "next_state": "enum: S_Suspended (required for phase A)",
                        "evidence_phase": "integer (required, must be 1)"
                    },
                    "phase_B_challenge": {
                        "challenge_window_days": "integer (required)",
                        "allowed_actions": ["string"],
                        "evidence_phase": "integer (required, must be 2)"
                    },
                    "phase_C_adjudication": {
                        "if_challenge_rejected_or_expired": {
                            "next_state": "enum: S_Breach (required)",
                            "consequences": ["string"],
                            "evidence_phase": "integer (required, must be 3)"
                        },
                        "if_challenge_accepted": {
                            "if_reputation_above_safe": {
                                "next_state": "enum: S_Active",
                                "evidence_phase": "integer"
                            },
                            "if_reputation_below_safe": {
                                "next_state": "enum: S_Restricted",
                                "restricted_constraints": {
                                    "manual_review_required": "boolean (required)",
                                    "high_sensitive_access_blocked": "boolean (required)",
                                    "privacy_cost_multiplier": "float > 1.0 (required)"
                                },
                                "evidence_phase": "integer"
                            }
                        }
                    }
                }
            }
        ],
        "dispute_units": [
            {
                "dispute_unit_id": "string (required, format: D_*)",
                "ClauseID": "string (required)",
                "issue_type": "string (required)",
                "subject": "string (subject_id reference)",
                "object": "string (object_id reference)",
                "time_window": {
                    "t_start": "ISO8601 string or null",
                    "t_end": "ISO8601 string or null"
                },
                "member_events": ["string (rule_id references)"],
                "merge_rationale": "string (required)",
                "confidence": "float 0-1 (required)",
                "recommend_human_review": "boolean (required)",
                "finality_parameters": {
                    "N_max": "integer >= 1 (required)",
                    "K_max": "integer >= 1 (required)",
                    "theta_safe": "float 0-1 (required)"
                }
            }
        ],
        "A_audit": {
            "evidence_templates": [
                {
                    "template_id": "string (required, format: tpl_*)",
                    "associated_rule": "string (rule_id reference)",
                    "associated_dispute_unit": "string (dispute_unit_id reference)",
                    "template_text": "string (required, natural-language template with slots)",
                    "slots": ["string (list of slot names)"]
                }
            ]
        }
    }

    # =========================================================================
    # LAYER 7: SELF-CHECK PROTOCOL
    # =========================================================================

    SELF_CHECK_PROTOCOL = """
# Pre-Output Self-Check Checklist
Before emitting the final JSON output, verify each of the following.
If any check fails, revise the output before submission.

## Structural Completeness
[CHECK-01] Every subject in S_subjects has a unique subject_id and a defined role.
[CHECK-02] Every object in O_objects has a sensitivity_level and at least one
            permitted_region (or an explicit justification for omission).
[CHECK-03] Every condition in C_conditions has a non-empty IndexClause field.
[CHECK-04] Every rule in R_rules has a non-empty IndexClause field.
[CHECK-05] Every rule contains all three phases: phase_A_freeze, phase_B_challenge,
            phase_C_adjudication. No single-step penalty paths exist.

## Dispute-Unit and Finality Completeness
[CHECK-06] Every rule_id referenced in R_rules appears in at least one
            dispute_unit's member_events list.
[CHECK-07] Every dispute_unit has finality_parameters with N_max >= 1,
            K_max >= 1, and 0 < theta_safe < 1.
[CHECK-08] Every dispute_unit with confidence < 0.7 has
            recommend_human_review set to true.
[CHECK-09] Every if_reputation_below_safe branch includes a non-empty
            restricted_constraints block with manual_review_required,
            high_sensitive_access_blocked, and privacy_cost_multiplier > 1.0.

## Procedural Justice Verification
[CHECK-10] No rule directly transitions from S_Active to S_Breach without
            passing through S_Suspended.
[CHECK-11] Every phase_B_challenge has challenge_window_days >= 1.
[CHECK-12] Every recovery path distinguishes between full recovery (S_Active)
            and restricted recovery (S_Restricted) based on reputation threshold.

## Audit and Evidence Verification
[CHECK-13] Every rule that triggers a state transition has at least one
            corresponding evidence template in A_audit.
[CHECK-14] Every evidence template contains at minimum the following slots:
            timestamp, clause_number, current_state, dispute_unit_id.
[CHECK-15] Every evidence template is associated with both a rule_id and
            a dispute_unit_id.

## Ambiguity and Human Review
[CHECK-16] Any condition or rule derived from ambiguous contractual language
            has requires_human_review set to true.
[CHECK-17] Any dispute-unit merge with confidence < 0.7 or involving
            high-sensitive data access, deposit handling, or final liability
            has recommend_human_review set to true.
"""

    # =========================================================================
    # LAYER 8: PROMPT ASSEMBLY
    # =========================================================================

    @classmethod
    def assemble_prompt(cls, contract_text: str) -> list:
        """
        Assemble the complete prompt sequence for LLM invocation.

        This method constructs a two-message chat sequence:
          - A system message containing meta-instruction, task instruction,
            CoT decomposition, mandatory constraints, and self-check protocol.
          - A user message containing the few-shot exemplar followed by
            the target contract text.

        The assembled sequence is compatible with OpenAI-style chat completion
        APIs and can be directly passed to model invocation endpoints.

        Parameters
        ----------
        contract_text : str
            Raw natural-language contract text to be compiled into SLCML IR.

        Returns
        -------
        list of dict
            Message sequence in [{"role": ..., "content": ...}] format.

        Example
        -------
        >>> framework = SLCMLPromptFramework()
        >>> messages = framework.assemble_prompt("Article 7.3: ...")
        >>> response = openai.ChatCompletion.create(
        ...     model="gpt-4",
        ...     messages=messages,
        ...     temperature=0.0
        ... )
        """
        system_content = "\n\n".join([
            cls.META_INSTRUCTION.strip(),
            cls.TASK_INSTRUCTION.strip(),
            cls.COT_DECOMPOSITION.strip(),
            cls.MANDATORY_CONSTRAINTS.strip(),
            cls.SELF_CHECK_PROTOCOL.strip()
        ])

        user_content = "\n\n".join([
            "# Few-Shot Reference Example",
            cls.FEW_SHOT_EXEMPLAR.strip(),
            "# Contract Text to Compile",
            "Analyze the following contract text and output a complete "
            "SLCML IR in JSON format. Do not include any text outside "
            "the JSON object.",
            contract_text.strip()
        ])

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

    @classmethod
    def get_schema_description(cls) -> dict:
        """
        Return the output schema definition for external validation modules.

        This schema is consumed by downstream components including:
          - JSON schema validators for structural completeness checking
          - SMT translation modules for formal verification
          - Template compilers for Solidity/Vyper code generation
          - Audit log generators for court-readable evidence production

        Returns
        -------
        dict
            SLCML_OUTPUT_SCHEMA structure with field-level type annotations
            and constraint descriptions.
        """
        return cls.OUTPUT_SCHEMA

    @classmethod
    def validate_output_structure(cls, output: dict) -> dict:
        """
        Perform lightweight structural validation on LLM output.

        This method checks for the presence of required top-level keys,
        non-empty arrays, and critical field constraints. It does NOT
        replace full schema validation or SMT verification, but serves
        as a fast pre-filter to reject obviously malformed outputs
        before they enter the formal verification pipeline.

        Parameters
        ----------
        output : dict
            Parsed JSON output from LLM invocation.

        Returns
        -------
        dict
            Validation result with structure:
            {
                "valid": bool,
                "errors": list of str,
                "warnings": list of str
            }
        """
        errors = []
        warnings = []

        # Top-level key presence
        required_keys = [
            "slcml_version", "contract_id", "extraction_metadata",
            "S_subjects", "O_objects", "C_conditions", "R_rules",
            "dispute_units", "A_audit"
        ]
        for key in required_keys:
            if key not in output:
                errors.append(f"Missing required top-level key: {key}")

        if errors:
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Version check
        if output.get("slcml_version") != "2.0":
            errors.append(
                f"Invalid slcml_version: expected '2.0', "
                f"got '{output.get('slcml_version')}'"
            )

        # Non-empty array checks
        for array_key in ["S_subjects", "O_objects", "C_conditions", "R_rules"]:
            if not isinstance(output.get(array_key), list) or len(output[array_key]) == 0:
                errors.append(f"{array_key} must be a non-empty array")

        # IndexClause binding check
        for rule in output.get("R_rules", []):
            if not rule.get("IndexClause"):
                errors.append(
                    f"Rule {rule.get('rule_id', 'UNKNOWN')} missing IndexClause binding"
                )

            # Three-phase structure check
            cf = rule.get("control_flow", {})
            for phase in ["phase_A_freeze", "phase_B_challenge", "phase_C_adjudication"]:
                if phase not in cf:
                    errors.append(
                        f"Rule {rule.get('rule_id', 'UNKNOWN')} missing "
                        f"required phase: {phase}"
                    )

            # S_Restricted constraint completeness check
            adj = cf.get("phase_C_adjudication", {})
            accepted = adj.get("if_challenge_accepted", {})
            below_safe = accepted.get("if_reputation_below_safe", {})
            if below_safe:
                rc = below_safe.get("restricted_constraints", {})
                for field in [
                    "manual_review_required",
                    "high_sensitive_access_blocked",
                    "privacy_cost_multiplier"
                ]:
                    if field not in rc:
                        errors.append(
                            f"Rule {rule.get('rule_id', 'UNKNOWN')}: "
                            f"S_Restricted branch missing {field}"
                        )
                if rc.get("privacy_cost_multiplier") is not None:
                    if rc["privacy_cost_multiplier"] <= 1.0:
                        errors.append(
                            f"Rule {rule.get('rule_id', 'UNKNOWN')}: "
                            f"privacy_cost_multiplier must be > 1.0"
                        )

        # Dispute-unit checks
        for du in output.get("dispute_units", []):
            if not du.get("finality_parameters"):
                errors.append(
                    f"Dispute unit {du.get('dispute_unit_id', 'UNKNOWN')} "
                    f"missing finality_parameters"
                )
            else:
                fp = du["finality_parameters"]
                if fp.get("N_max", 0) < 1:
                    errors.append(
                        f"Dispute unit {du.get('dispute_unit_id', 'UNKNOWN')}: "
                        f"N_max must be >= 1"
                    )
                if fp.get("K_max", 0) < 1:
                    errors.append(
                        f"Dispute unit {du.get('dispute_unit_id', 'UNKNOWN')}: "
                        f"K_max must be >= 1"
                    )
                ts = fp.get("theta_safe")
                if ts is None or not (0 < ts < 1):
                    errors.append(
                        f"Dispute unit {du.get('dispute_unit_id', 'UNKNOWN')}: "
                        f"theta_safe must be in (0, 1)"
                    )

            # Confidence-based human review recommendation
            conf = du.get("confidence", 1.0)
            if conf < 0.7 and not du.get("recommend_human_review", False):
                warnings.append(
                    f"Dispute unit {du.get('dispute_unit_id', 'UNKNOWN')} has "
                    f"confidence {conf} < 0.7 but recommend_human_review is False"
                )

        # Evidence template coverage check
        templates = output.get("A_audit", {}).get("evidence_templates", [])
        template_rule_ids = {t.get("associated_rule") for t in templates}
        for rule in output.get("R_rules", []):
            rid = rule.get("rule_id")
            if rid and rid not in template_rule_ids:
                warnings.append(
                    f"Rule {rid} has no corresponding evidence template in A_audit"
                )

        # Evidence template minimum slot check
        required_slots = {"timestamp", "clause_number", "current_state", "dispute_unit_id"}
        for tpl in templates:
            tpl_slots = set(tpl.get("slots", []))
            missing = required_slots - tpl_slots
            if missing:
                errors.append(
                    f"Template {tpl.get('template_id', 'UNKNOWN')} missing "
                    f"required slots: {missing}"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }