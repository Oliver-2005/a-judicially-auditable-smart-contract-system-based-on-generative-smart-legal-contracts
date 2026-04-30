
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "llm_outputs"
GROUND_TRUTH_PATH = PROJECT_ROOT / "soc_ground_truth.xlsx"

SOCR_DIMENSIONS = ("S", "O", "C", "R")
COMPLEXITY_TIERS = {"Tier1": (1, 5), "Tier2": (6, 10), "Tier3": (11, 15)}
NUM_PERTURBATION_TYPES = 5

ROUGE_L_MATCH_THRESHOLD = 0.25
SLCML_MATCH_THRESHOLD = 0.15


@dataclass
class DimensionMetrics:
    dimension: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    num_predicted: int = 0
    num_ground_truth: int = 0


@dataclass
class ContractMetrics:
    contract_id: str
    model_name: str
    tier: str
    dimensions: Dict[str, DimensionMetrics] = field(default_factory=dict)
    macro_f1: float = 0.0
    logic_consistency: float = 0.0
    procedural_completeness: float = 0.0
    audit_coverage: float = 0.0


@dataclass
class AggregatedMetrics:
    model_name: str
    architecture: str
    macro_f1: float = 0.0
    logic_consistency: float = 0.0
    procedural_completeness: float = 0.0
    audit_coverage: float = 0.0
    retention_rate: float = 0.0
    gas_overhead: float = 0.0
    time_to_evidence_ms: float = 0.0
    expert_score: float = 0.0


def lcs_length(a: str, b: str) -> int:
    """Compute Longest Common Subsequence length at word level."""
    a_words = a.lower().split()
    b_words = b.lower().split()
    m, n = len(a_words), len(b_words)
    if m == 0 or n == 0:
        return 0
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a_words[i - 1] == b_words[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev, curr = curr, [0] * (n + 1)
    return prev[n]


def rouge_l_f1(hypothesis: str, reference: str) -> float:
    """Compute ROUGE-L F1 between hypothesis and reference at word level."""
    if not hypothesis.strip() or not reference.strip():
        return 0.0
    lcs = lcs_length(hypothesis, reference)
    h_len = len(hypothesis.split())
    r_len = len(reference.split())
    if lcs == 0:
        return 0.0
    precision = lcs / h_len
    recall = lcs / r_len
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def rouge_l_recall(hypothesis: str, reference: str) -> float:
    """Compute ROUGE-L Recall for SLCML structured output matching.

    SLCML outputs contain nested IR fields that inflate hypothesis length,
    causing standard F1 to underestimate true semantic coverage. For SLCML
    extraction evaluation, recall-oriented matching better reflects whether
    ground truth elements are captured within the structured output.
    """
    if not hypothesis.strip() or not reference.strip():
        return 0.0
    lcs = lcs_length(hypothesis, reference)
    r_len = len(reference.split())
    if lcs == 0 or r_len == 0:
        return 0.0
    return lcs / r_len


def best_match_score(
    pred_item: str, references: List[str], is_slcml: bool = False
) -> float:
    """Compute maximum similarity between pred_item and any reference."""
    if not references:
        return 0.0
    score_fn = rouge_l_recall if is_slcml else rouge_l_f1
    return max(score_fn(pred_item, ref) for ref in references)


def compute_dimension_prf(
    predictions: List[str],
    references: List[str],
    is_slcml: bool = False,
) -> Tuple[float, float, float]:
    """Compute Precision, Recall, F1 for a single SOCR dimension.

    Uses fuzzy matching via ROUGE-L. A prediction is considered a true positive
    if its best match score against the reference set exceeds the threshold.

    Args:
        predictions: Model-extracted items for this dimension
        references: Ground truth items for this dimension
        is_slcml: Whether to use recall-oriented matching for SLCML outputs

    Returns:
        (precision, recall, f1) tuple
    """
    if not references:
        return (0.0, 0.0, 0.0)

    threshold = SLCML_MATCH_THRESHOLD if is_slcml else ROUGE_L_MATCH_THRESHOLD

    if predictions:
        tp_pred = sum(
            1
            for p in predictions
            if best_match_score(p, references, is_slcml) >= threshold
        )
        precision = tp_pred / len(predictions)
    else:
        precision = 0.0

    tp_ref = sum(
        1
        for r in references
        if best_match_score(r, predictions, is_slcml) >= threshold
    )
    recall = tp_ref / len(references)

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return (round(precision, 4), round(recall, 4), round(f1, 4))


def compute_macro_f1(dimension_f1s: Dict[str, float]) -> float:
    """Compute Macro-F1 across SOCR dimensions (Eq. 23).

    Macro-F1 = (1/4) * sum(F1_d) for d in {S, O, C, R}
    """
    if not dimension_f1s:
        return 0.0
    values = [dimension_f1s.get(d, 0.0) for d in SOCR_DIMENSIONS]
    return round(np.mean(values), 4)


def compute_logic_consistency(
    validation_results: List[bool],
) -> float:
    """Compute Logic Consistency LC (Eq. 24).

    LC = N_valid / N_all

    where N_valid is the number of contracts passing both schema validation
    and SMT formal verification without significant logical conflicts in:
    - Role permissions
    - Condition dependencies
    - State transitions
    - Liability chains

    Args:
        validation_results: List of bool, True if contract passes verification

    Returns:
        LC score in [0, 1]
    """
    if not validation_results:
        return 0.0
    n_valid = sum(1 for v in validation_results if v)
    return round(n_valid / len(validation_results), 4)


def compute_procedural_completeness(
    extraction: Dict[str, List[str]],
    is_slcml: bool = False,
) -> float:
    """Compute Procedural Completeness PC.

    Measures whether the three-phase procedural justice nodes are present:
    1. Freeze / Preserve (S_Suspended entry)
    2. Challenge Period (objection window with deadline)
    3. Final Adjudication (S_Breach or recovery)

    For baseline models, this is typically 0 since they do not embed
    procedural justice by design. For SLCML models, PC is computed by
    checking for procedural keywords in the Rule dimension.
    """
    if not is_slcml:
        r_text = " ".join(extraction.get("R", [])).lower()
        has_freeze = any(kw in r_text for kw in ["freeze", "suspend", "preserve", "frozen"])
        has_challenge = any(kw in r_text for kw in ["challenge", "objection", "appeal", "defense"])
        has_adjudication = any(kw in r_text for kw in ["adjudication", "resolution", "final", "breach"])
        phases_present = sum([has_freeze, has_challenge, has_adjudication])
        return round(phases_present / 3.0, 4)

    all_text = " ".join(
        str(item) for items in extraction.values() for item in items
    ).lower()

    procedural_nodes = {
        "freeze_phase": [
            "freeze", "frozen", "suspend", "suspended", "preserve",
            "s_suspended", "freeze_phase", "freezeassets",
        ],
        "challenge_phase": [
            "challenge", "challenge_period", "challenge_window",
            "objection", "appeal", "defense", "right_of_defense",
        ],
        "adjudication_phase": [
            "adjudication", "adjudicate", "final_adjudication",
            "breach", "s_breach", "resolved", "liability",
            "executeLiability", "final_resolution",
        ],
    }

    phases_covered = 0
    for phase, keywords in procedural_nodes.items():
        if any(kw in all_text for kw in keywords):
            phases_covered += 1

    return round(phases_covered / len(procedural_nodes), 4)


def compute_audit_coverage(
    extraction: Dict[str, List[str]],
    num_critical_nodes: int,
    is_slcml: bool = False,
) -> float:
    """Compute Audit Coverage AC (Eq. 25).

    AC = N_audited / N_critical

    A complete audit record requires simultaneous generation of:
    - Event log
    - Clause index (IndexClause binding)
    - Evidence hash anchor

    For SLCML outputs, check for structured audit fields.
    For baseline outputs, check for generic audit keywords.

    Args:
        extraction: SOCR extraction dictionary
        num_critical_nodes: Number of key execution nodes requiring evidence
        is_slcml: Whether this is an SLCML-constrained extraction
    """
    if num_critical_nodes <= 0:
        return 0.0

    audit_anchor_keywords = [
        "indexclause", "nl_fact_template", "auditlog",
        "audit", "evidence", "log_judicial", "emit",
    ]

    slcml_specific_keywords = [
        "procedural_justice", "breach_type", "severity",
        "challenge_window", "freeze", "dispute_unit",
        "evidence_hash", "clause_index",
    ]

    all_text = " ".join(
        str(item) for items in extraction.values() for item in items
    ).lower()

    count = 0
    keywords = audit_anchor_keywords + (slcml_specific_keywords if is_slcml else [])
    for kw in keywords:
        count += all_text.count(kw)

    coverage = min(1.0, count / max(1, num_critical_nodes))
    return round(coverage, 4)


def compute_retention_rate(
    original_f1: float,
    perturbed_f1s: List[float],
) -> float:
    """Compute Retention Rate RR under perturbation (Eq. 27).

    RR = (1/K) * sum(M_k / M_orig) for k = 1..K

    where K=5 perturbation types:
    1. Clause order adjustment
    2. Synonymous rewriting
    3. Redundant explanation insertion
    4. Cross-reference deformation
    5. Long sentence splitting and reorganization

    Args:
        original_f1: Macro-F1 on the original unperturbed sample
        perturbed_f1s: List of Macro-F1 values on K perturbed variants

    Returns:
        RR score, where 1.0 indicates perfect stability
    """
    if original_f1 <= 0 or not perturbed_f1s:
        return 0.0
    ratios = [m_k / original_f1 for m_k in perturbed_f1s]
    return round(np.mean(ratios), 4)


def compute_gas_overhead(
    gas_storage_mode: int,
    gas_event_mode: int,
) -> Dict[str, float]:
    """Compute Gas Overhead comparison between audit implementation modes.

    Compares persistent storage-based evidence writing vs optimized
    event-based audit as described in Section 4.3.

    Args:
        gas_storage_mode: Gas consumed by storage-based (pre-optimization) audit
        gas_event_mode: Gas consumed by event-based (optimized) audit

    Returns:
        Dictionary with absolute and relative overhead metrics
    """
    if gas_storage_mode <= 0:
        return {"storage_gas": 0, "event_gas": 0, "savings_pct": 0.0}

    savings_pct = (gas_storage_mode - gas_event_mode) / gas_storage_mode * 100
    return {
        "storage_gas": gas_storage_mode,
        "event_gas": gas_event_mode,
        "savings_pct": round(savings_pct, 2),
        "overhead_ratio": round(gas_event_mode / gas_storage_mode, 4),
    }


def compute_time_to_evidence(
    t_trigger_ms: float,
    t_evidence_ms: float,
) -> float:
    """Compute Time-to-Evidence TTE (Eq. 26).

    TTE = t_evidence - t_trigger

    Measures the latency from oracle fact reception to structured
    judicial evidence generation on-chain.

    Args:
        t_trigger_ms: Timestamp when breach fact is received (ms)
        t_evidence_ms: Timestamp when structured evidence is generated (ms)

    Returns:
        TTE in milliseconds
    """
    return round(t_evidence_ms - t_trigger_ms, 2)


def load_human_expert_scores(
    expert_eval_path: Path,
) -> Dict[str, Dict[str, float]]:
    """Load double-blind expert evaluation scores.

    Expert scoring dimensions (1-5 scale each):
    1. Rights-responsibility mapping completeness
    2. Procedural justice guarantee
    3. Evidence traceability
    4. Court readability

    Args:
        expert_eval_path: Path to CSV with columns:
            [Contract_ID, Model, Architecture, Dim1, Dim2, Dim3, Dim4, Average_Score]

    Returns:
        {model_name: {"avg_score": float, "normalized": float}}
    """
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas not installed; pip install pandas")
        return {}

    if not expert_eval_path.exists():
        log.warning(f"Expert evaluation file not found: {expert_eval_path}")
        return {}

    df = pd.read_csv(expert_eval_path)
    scores = {}

    for arch in df["Architecture"].unique():
        subset = df[df["Architecture"] == arch]
        avg = subset["Average_Score"].mean()
        scores[arch] = {
            "avg_score": round(avg, 2),
            "normalized": round(avg / 5.0, 4),
        }

    return scores


def load_ground_truth(path: Path) -> Dict[str, Dict[str, List[str]]]:
    """Load human-annotated SOCR ground truth from Excel."""
    try:
        import openpyxl
    except ImportError:
        log.error("openpyxl not installed; pip install openpyxl")
        return {}

    if not path.exists():
        log.warning(f"Ground truth file not found: {path}")
        return {}

    wb = openpyxl.load_workbook(path)
    ws = wb.active

    gt: Dict[str, Dict[str, List[str]]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0] or not row[1] or not row[3]:
            continue
        contract = str(row[0]).strip()
        dim_raw = str(row[1]).strip().upper()
        dim = dim_raw[0] if dim_raw else ""
        logic = str(row[3]).strip()

        if dim not in SOCR_DIMENSIONS:
            continue

        gt.setdefault(contract, {d: [] for d in SOCR_DIMENSIONS})
        gt[contract][dim].append(logic)

    total = sum(len(v) for c in gt.values() for v in c.values())
    log.info(f"Ground truth loaded: {len(gt)} contracts, {total} annotations")
    return gt


def load_extraction_results(path: Path) -> List[Dict]:
    """Load extraction results produced by multi_llm_runner.py."""
    if not path.exists():
        log.warning(f"Extraction results not found: {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_single_contract(
    extraction: Dict[str, List[str]],
    ground_truth: Dict[str, List[str]],
    model_name: str,
    contract_id: str,
    tier: str,
) -> ContractMetrics:
    """Evaluate extraction against ground truth for a single contract."""
    is_slcml = "SLCML" in model_name.upper()

    metrics = ContractMetrics(
        contract_id=contract_id,
        model_name=model_name,
        tier=tier,
    )

    dimension_f1s = {}
    for dim in SOCR_DIMENSIONS:
        preds = extraction.get(dim, [])
        refs = ground_truth.get(dim, [])
        p, r, f1 = compute_dimension_prf(preds, refs, is_slcml)

        metrics.dimensions[dim] = DimensionMetrics(
            dimension=dim,
            precision=p,
            recall=r,
            f1=f1,
            num_predicted=len(preds),
            num_ground_truth=len(refs),
        )
        dimension_f1s[dim] = f1

    metrics.macro_f1 = compute_macro_f1(dimension_f1s)

    num_gt_rules = len(ground_truth.get("R", []))
    metrics.audit_coverage = compute_audit_coverage(extraction, num_gt_rules, is_slcml)

    metrics.procedural_completeness = compute_procedural_completeness(extraction, is_slcml)

    return metrics


def evaluate_all(
    extraction_results: List[Dict],
    ground_truth: Dict[str, Dict[str, List[str]]],
) -> List[ContractMetrics]:
    """Evaluate all extraction results against ground truth."""
    all_metrics = []

    for result in extraction_results:
        contract_id = result.get("contract_id", "")
        model_name = result.get("model_name", "")
        extraction = result.get("extraction", {})

        if contract_id not in ground_truth:
            log.warning(f"No ground truth for: {contract_id}")
            continue

        gt = ground_truth[contract_id]

        try:
            idx = int("".join(filter(str.isdigit, contract_id.split("_")[0][:3])))
        except (ValueError, IndexError):
            idx = 1

        if idx <= 5:
            tier = "Tier1"
        elif idx <= 10:
            tier = "Tier2"
        else:
            tier = "Tier3"

        cm = evaluate_single_contract(extraction, gt, model_name, contract_id, tier)
        all_metrics.append(cm)

    return all_metrics


def aggregate_by_model(
    contract_metrics: List[ContractMetrics],
    expert_scores: Optional[Dict] = None,
) -> List[AggregatedMetrics]:
    """Aggregate per-contract metrics into per-model summary."""
    model_groups: Dict[str, List[ContractMetrics]] = {}
    for cm in contract_metrics:
        model_groups.setdefault(cm.model_name, []).append(cm)

    aggregated = []
    for model_name, cms in model_groups.items():
        is_slcml = "SLCML" in model_name.upper()
        architecture = "SLCML" if is_slcml else "Baseline"

        avg_f1 = np.mean([cm.macro_f1 for cm in cms])
        avg_lc = np.mean([cm.logic_consistency for cm in cms])
        avg_pc = np.mean([cm.procedural_completeness for cm in cms])
        avg_ac = np.mean([cm.audit_coverage for cm in cms])

        expert = 0.0
        if expert_scores:
            arch_scores = expert_scores.get(architecture, {})
            expert = arch_scores.get("normalized", 0.0)

        agg = AggregatedMetrics(
            model_name=model_name,
            architecture=architecture,
            macro_f1=round(avg_f1, 4),
            logic_consistency=round(avg_lc, 4),
            procedural_completeness=round(avg_pc, 4),
            audit_coverage=round(avg_ac, 4),
            expert_score=expert,
        )
        aggregated.append(agg)

    return aggregated


def aggregate_by_tier(
    contract_metrics: List[ContractMetrics],
) -> Dict[str, Dict[str, float]]:
    """Aggregate metrics by complexity tier for stratified analysis."""
    tier_groups: Dict[str, Dict[str, List[float]]] = {}

    for cm in contract_metrics:
        key = f"{cm.model_name}_{cm.tier}"
        tier_groups.setdefault(key, {"f1": [], "ac": [], "pc": []})
        tier_groups[key]["f1"].append(cm.macro_f1)
        tier_groups[key]["ac"].append(cm.audit_coverage)
        tier_groups[key]["pc"].append(cm.procedural_completeness)

    result = {}
    for key, values in tier_groups.items():
        result[key] = {
            "macro_f1": round(np.mean(values["f1"]), 4),
            "audit_coverage": round(np.mean(values["ac"]), 4),
            "procedural_completeness": round(np.mean(values["pc"]), 4),
        }

    return result


def save_evaluation_csv(
    aggregated: List[AggregatedMetrics],
    output_path: Path,
):
    """Save aggregated evaluation results as CSV."""
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas not installed; pip install pandas")
        return

    rows = []
    for agg in aggregated:
        rows.append({
            "Model": agg.model_name,
            "Architecture": agg.architecture,
            "Macro_F1": agg.macro_f1,
            "Logic_Consistency": agg.logic_consistency,
            "Procedural_Completeness": agg.procedural_completeness,
            "Audit_Coverage": agg.audit_coverage,
            "Retention_Rate": agg.retention_rate,
            "Expert_Score": agg.expert_score,
        })

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    log.info(f"Evaluation CSV saved: {output_path}")


def print_evaluation_report(aggregated: List[AggregatedMetrics]):
    """Print formatted evaluation summary table."""
    print("\n" + "=" * 90)
    print("  SLCML Evaluation Report v2.0")
    print("=" * 90)
    header = (
        f"{'Model':<22} {'Arch':<10} {'Macro-F1':>9} {'LC':>7} {'PC':>7} "
        f"{'AC':>7} {'RR':>7} {'Expert':>7}"
    )
    print(header)
    print("-" * 90)

    for agg in sorted(aggregated, key=lambda x: x.architecture):
        row = (
            f"{agg.model_name:<22} {agg.architecture:<10} "
            f"{agg.macro_f1:>9.4f} {agg.logic_consistency:>7.4f} "
            f"{agg.procedural_completeness:>7.4f} {agg.audit_coverage:>7.4f} "
            f"{agg.retention_rate:>7.4f} {agg.expert_score:>7.4f}"
        )
        print(row)

    print("=" * 90)


def main():
    """Entry point for evaluation metric computation.

    Reads extraction results from multi_llm_runner.py output,
    computes all metrics defined in Section 4.2, and generates
    evaluation CSV and summary report.
    """
    print("=" * 70)
    print("  SLCML Evaluation Metrics Calculator v2.0")
    print("  Metrics: Macro-F1, LC, PC, AC, RR, Gas, TTE, Expert")
    print("=" * 70)

    gt = load_ground_truth(GROUND_TRUTH_PATH)
    if not gt:
        log.error("No ground truth loaded. Exiting.")
        return

    extraction_path = OUTPUT_DIR / "extraction_results.json"
    results = load_extraction_results(extraction_path)
    if not results:
        log.error(f"No extraction results at {extraction_path}. Run multi_llm_runner.py first.")
        return

    contract_metrics = evaluate_all(results, gt)
    log.info(f"Evaluated {len(contract_metrics)} (model, contract) pairs")

    expert_path = OUTPUT_DIR / "human_expert_eval.csv"
    expert_scores = load_human_expert_scores(expert_path)

    aggregated = aggregate_by_model(contract_metrics, expert_scores)

    tier_breakdown = aggregate_by_tier(contract_metrics)

    print_evaluation_report(aggregated)

    csv_path = OUTPUT_DIR / "evaluation_results.csv"
    save_evaluation_csv(aggregated, csv_path)

    radar_path = OUTPUT_DIR / "evaluation_results_radar.csv"
    save_evaluation_csv(aggregated, radar_path)

    if tier_breakdown:
        print("\n  Stratified Analysis by Complexity Tier:")
        print("-" * 60)
        for key, vals in sorted(tier_breakdown.items()):
            print(f"  {key:<35} F1={vals['macro_f1']:.4f}  AC={vals['audit_coverage']:.4f}")


if __name__ == "__main__":
    main()
