"""Multi-LLM Concurrent Inference Runner for SLCML Evaluation Pipeline.

Orchestrates parallel inference across multiple LLM backends under both
baseline (zero-shot) and SLCML-constrained (structured CoT) prompting
regimes. Supports A/B controlled experiments as described in Section 4.3.

Architecture:
    - Baseline group: native LLM direct generation without quintuple IR constraints
    - SLCML group: structured CoT prompting with three-phase procedural justice
      enforcement and audit anchor embedding

Models evaluated (Section 4.3):
    GPT-5, Claude-4.5-Sonnet, Gemini-3.1-Pro

Contract corpus: 15 real-world medical data collaboration contracts
stratified into Tier 1 (Simple), Tier 2 (Medium), Tier 3 (High-Complex).
"""

import os
import re
import json
import asyncio
import logging
import time as time_module
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Tuple
from enum import Enum

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

CONTRACTS_DIR = PROJECT_ROOT / "contracts_corpus"
GROUND_TRUTH_PATH = PROJECT_ROOT / "soc_ground_truth.xlsx"
OUTPUT_DIR = PROJECT_ROOT / "data" / "llm_outputs"
RAW_OUTPUT_DIR = OUTPUT_DIR / "raw_extractions"

SOCR_DIMENSIONS = ("S", "O", "C", "R")
COMPLEXITY_TIERS = {"Tier1": range(1, 6), "Tier2": range(6, 11), "Tier3": range(11, 16)}
PERTURBATION_TYPES = [
    "clause_reorder",
    "synonym_rewrite",
    "redundant_insertion",
    "cross_reference_deform",
    "long_sentence_split",
]


class PromptMode(Enum):
    BASELINE = "baseline"
    SLCML = "slcml"


@dataclass
class ModelConfig:
    display_name: str
    model_id: str
    prompt_mode: PromptMode
    api_endpoint: str = ""
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout_seconds: int = 120


@dataclass
class ExtractionResult:
    contract_id: str
    model_name: str
    prompt_mode: str
    extraction: Dict[str, List[str]] = field(default_factory=lambda: {d: [] for d in SOCR_DIMENSIONS})
    raw_response: str = ""
    latency_ms: float = 0.0
    token_usage: Dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None


MODELS: List[ModelConfig] = [
    ModelConfig(
        display_name="GPT-5",
        model_id="gpt-5-codex",
        prompt_mode=PromptMode.BASELINE,
    ),
    ModelConfig(
        display_name="Claude-4.5-Sonnet",
        model_id="claude-sonnet-4-5-20250929",
        prompt_mode=PromptMode.BASELINE,
    ),
    ModelConfig(
        display_name="Gemini-3.1-Pro",
        model_id="gemini-3-pro-preview",
        prompt_mode=PromptMode.BASELINE,
    ),
    ModelConfig(
        display_name="SLCML-GPT-5",
        model_id="gpt-5-codex",
        prompt_mode=PromptMode.SLCML,
    ),
    ModelConfig(
        display_name="SLCML-Claude-4.5",
        model_id="claude-sonnet-4-5-20250929",
        prompt_mode=PromptMode.SLCML,
    ),
    ModelConfig(
        display_name="SLCML-Gemini-3.1",
        model_id="gemini-3-pro-preview",
        prompt_mode=PromptMode.SLCML,
    ),
]


BASELINE_SYSTEM_PROMPT = """You are a legal contract analysis expert. Extract structured legal logic from the given contract text.

Output MUST be a JSON object with the following structure:
{
  "S": ["subject description 1", "subject description 2"],
  "O": ["object/asset description 1", ...],
  "C": ["condition description 1", ...],
  "R": ["rule/obligation description 1", ...]
}

Definitions:
- S (Subject): Legal parties, their roles, and responsibilities
- O (Object): Data assets, IP rights, deliverables, regulated objects
- C (Condition): Temporal, geographic, performance, and procedural constraints
- R (Rule): Executable obligations, penalties, breach consequences
"""

SLCML_SYSTEM_PROMPT = """You are the SLCML Legal Logic Parsing Engine. Transform legal contracts into a structured Intermediate Representation (IR) conforming to the quintuple model <S, O, C, R, A>.

Adhere to the Three-Stage Structured Chain-of-Thought:

### TASK 1: Entity & Object Extraction
- Identify dynamic Subjects (parties, roles, credentials, reputation parameters).
- Identify Objects (data assets, AI models, deposits).
- Assign attributes: Sensitivity Levels (1-5) and Initial Privacy Budget (B_total).

### TASK 2: Spatiotemporal Conditions & Oracle Mapping
- Extract constraints: Temporal windows, Geographic restrictions, Performance thresholds.
- Map to Oracle Environment Variables (omega_geo, omega_perf, omega_auth).
- Extract procedural deadline parameters (challenge windows, observation periods).

### TASK 3: Causal Logic & Procedural Justice
- Construct If-Then-Else control flows for breach/responsibility.
- BIND the natural language clause index to each breach trigger as 'IndexClause'.
- EMBED three-phase Procedural Justice: Freeze -> Challenge Window -> Final Adjudication.
- State transitions MUST follow: S_Active -> S_Suspended -> {S_Breach | S_Restricted | S_Active}.
- Direct Active->Breach transitions are PROHIBITED.
- GENERATE AuditLog NL Fact Templates with variable slots for each state-transition rule.

### TASK 4: Dispute-Unit Aggregation & Finality Parameters
- Group sub-events sharing (ClauseID, IssueType, subject, object, time_window) into dispute units D_k.
- Generate procedural finality parameters: N_max (challenge limit), K_max (suspension fuse), theta_safe (reputation threshold).
- Generate S_Restricted recovery constraints.

Output format MUST be JSON:
{
  "S": [{"party": "...", "role": "...", "credential_type": "...", "B_total": "..."}],
  "O": [{"asset": "...", "sensitivity_level": N, "permitted_regions": [...]}],
  "C": [{"constraint": "...", "oracle_var": "...", "evaluation_timing": "...", "formal_predicate": "..."}],
  "R": [{"logic": "...", "IndexClause": "...", "procedural_justice": {"freeze": "...", "challenge_window": "...", "adjudication": "..."}, "NL_Fact_Template": "...", "breach_type": "...", "severity": "..."}]
}
"""


def build_user_prompt(contract_text: str, chunk_index: int = 0, total_chunks: int = 1) -> str:
    chunk_info = f" (segment {chunk_index + 1}/{total_chunks})" if total_chunks > 1 else ""
    return (
        f"Analyze the following legal contract{chunk_info} and perform SOCR extraction.\n\n"
        f"--- CONTRACT TEXT START ---\n{contract_text}\n--- CONTRACT TEXT END ---\n\n"
        f"Return ONLY the JSON object."
    )


def get_system_prompt(mode: PromptMode) -> str:
    if mode == PromptMode.SLCML:
        return SLCML_SYSTEM_PROMPT
    return BASELINE_SYSTEM_PROMPT


def load_contract_text(file_path: Path, max_chars: int = 100_000) -> str:
    """Load contract text from supported file formats (.txt, .docx, .pdf)."""
    if not file_path.exists():
        log.warning(f"Contract file not found: {file_path}")
        return ""

    ext = file_path.suffix.lower()

    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()[:max_chars]

    if ext == ".docx":
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(file_path))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text[:max_chars]
        except ImportError:
            log.error("python-docx not installed; pip install python-docx")
            return ""

    if ext == ".pdf":
        try:
            import pdfplumber
            texts = []
            with pdfplumber.open(str(file_path)) as pdf:
                for page in pdf.pages[:50]:
                    t = page.extract_text()
                    if t:
                        texts.append(t)
            return "\n".join(texts)[:max_chars]
        except ImportError:
            log.error("pdfplumber not installed; pip install pdfplumber")
            return ""

    log.warning(f"Unsupported file format: {ext}")
    return ""


def chunk_text(text: str, chunk_size: int = 6000) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i : i + chunk_size])
    return chunks


def parse_llm_json_response(raw_text: str) -> Dict[str, List[str]]:
    """Parse LLM response into normalized SOCR dictionary."""
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No valid JSON found in response: {raw_text[:100]}...")

    json_str = raw_text[start : end + 1]
    parsed = json.loads(json_str)

    result = {d: [] for d in SOCR_DIMENSIONS}
    for dim in SOCR_DIMENSIONS:
        if dim in parsed and isinstance(parsed[dim], list):
            for item in parsed[dim]:
                if isinstance(item, dict):
                    merged = ", ".join(f"{k}: {v}" for k, v in item.items())
                    result[dim].append(merged)
                elif isinstance(item, str):
                    result[dim].append(item.strip())
                else:
                    result[dim].append(str(item))
    return result


async def call_llm_api(
    model_config: ModelConfig,
    contract_text: str,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> Tuple[Dict[str, List[str]], str, float, Dict[str, int]]:
    """Call LLM API and return (extraction, raw_response, latency_ms, token_usage).

    NOTE: This function requires valid API credentials to execute.
    In repository-submission mode, it serves as an interface specification.
    Actual inference requires configuring model_config.api_key and api_endpoint.
    """
    import aiohttp

    system_prompt = get_system_prompt(model_config.prompt_mode)
    user_prompt = build_user_prompt(contract_text, chunk_index, total_chunks)

    headers = {
        "Authorization": f"Bearer {model_config.api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_config.model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": model_config.temperature,
        "max_tokens": model_config.max_tokens,
    }

    t_start = time_module.perf_counter()

    async with aiohttp.ClientSession() as session:
        async with session.post(
            model_config.api_endpoint,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=model_config.timeout_seconds),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    t_end = time_module.perf_counter()
    latency_ms = (t_end - t_start) * 1000

    raw_text = data["choices"][0]["message"]["content"].strip()
    token_usage = data.get("usage", {})

    extraction = parse_llm_json_response(raw_text)
    return extraction, raw_text, latency_ms, token_usage


async def run_single_extraction(
    model_config: ModelConfig,
    contract_id: str,
    contract_text: str,
    semaphore: asyncio.Semaphore,
    use_cache: bool = True,
) -> ExtractionResult:
    """Execute extraction for one (model, contract) pair with caching and retry."""
    safe_name = re.sub(r"[^\w]", "_", contract_id[:40])
    cache_path = RAW_OUTPUT_DIR / f"{model_config.display_name}_{safe_name}.json"

    if use_cache and cache_path.exists():
        log.info(f"  Cache hit: {model_config.display_name} -> {contract_id[:40]}")
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        return ExtractionResult(
            contract_id=contract_id,
            model_name=model_config.display_name,
            prompt_mode=model_config.prompt_mode.value,
            extraction=cached.get("extraction", {d: [] for d in SOCR_DIMENSIONS}),
            latency_ms=cached.get("latency_ms", 0.0),
        )

    async with semaphore:
        log.info(f"  Calling {model_config.display_name} -> {contract_id[:40]}...")

        chunks = chunk_text(contract_text)
        merged_extraction = {d: [] for d in SOCR_DIMENSIONS}
        total_latency = 0.0
        total_usage = {}

        max_retries = 3
        for idx, chunk in enumerate(chunks):
            for attempt in range(max_retries):
                try:
                    ext, raw, lat, usage = await call_llm_api(
                        model_config, chunk, idx, len(chunks)
                    )
                    for dim in SOCR_DIMENSIONS:
                        merged_extraction[dim].extend(ext.get(dim, []))
                    total_latency += lat
                    total_usage = usage
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** (attempt + 1)
                        log.warning(
                            f"  Retry {attempt + 1}/{max_retries} for "
                            f"{model_config.display_name} chunk {idx + 1}: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        log.error(
                            f"  Failed {model_config.display_name} chunk {idx + 1}: {e}"
                        )
                        return ExtractionResult(
                            contract_id=contract_id,
                            model_name=model_config.display_name,
                            prompt_mode=model_config.prompt_mode.value,
                            error=str(e),
                        )

        extraction = {d: list(set(items)) for d, items in merged_extraction.items()}

        result = ExtractionResult(
            contract_id=contract_id,
            model_name=model_config.display_name,
            prompt_mode=model_config.prompt_mode.value,
            extraction=extraction,
            latency_ms=total_latency,
            token_usage=total_usage,
        )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, ensure_ascii=False, indent=2)

        log.info(f"  Done: {model_config.display_name} -> {contract_id[:40]} ({total_latency:.0f}ms)")
        return result


async def run_all_extractions(
    contracts: Dict[str, str],
    models: List[ModelConfig],
    max_concurrency: int = 3,
) -> List[ExtractionResult]:
    """Run extraction across all (model, contract) combinations concurrently."""
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = []

    for contract_id, contract_text in contracts.items():
        for model_config in models:
            tasks.append(
                run_single_extraction(model_config, contract_id, contract_text, semaphore)
            )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    extraction_results = []
    for r in results:
        if isinstance(r, ExtractionResult):
            extraction_results.append(r)
        elif isinstance(r, Exception):
            log.error(f"Task exception: {r}")

    return extraction_results


def load_ground_truth(path: Path) -> Dict[str, Dict[str, List[str]]]:
    """Load human-annotated SOCR ground truth from Excel.

    Expected column layout: Contract File | Dimension | Element Type | Extracted Logic | ...
    Returns: {contract_name: {"S": [...], "O": [...], "C": [...], "R": [...]}}
    """
    try:
        import openpyxl
    except ImportError:
        log.error("openpyxl not installed; pip install openpyxl")
        return {}

    if not path.exists():
        log.warning(f"Ground truth file not found: {path}")
        return {}

    log.info(f"Loading ground truth: {path}")
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

    total_annotations = sum(len(v) for c in gt.values() for v in c.values())
    log.info(f"  Loaded: {len(gt)} contracts, {total_annotations} annotations")
    return gt


def get_tier_for_contract(index: int) -> str:
    if index <= 5:
        return "Tier1"
    elif index <= 10:
        return "Tier2"
    else:
        return "Tier3"


def save_results(results: List[ExtractionResult], output_path: Path):
    """Serialize extraction results to JSON for downstream metric computation."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = [asdict(r) for r in results]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    log.info(f"Results saved: {output_path} ({len(results)} entries)")


def main():
    """Entry point for multi-LLM evaluation pipeline.

    Execution requires:
    1. Valid API credentials configured in each ModelConfig
    2. Contract corpus in CONTRACTS_DIR
    3. Ground truth annotations in GROUND_TRUTH_PATH

    The runner produces raw extraction JSON files consumed by metrics_calc.py.
    """
    print("=" * 70)
    print("  SLCML Multi-LLM Evaluation Runner v2.0")
    print(f"  Models: {', '.join(m.display_name for m in MODELS)}")
    print(f"  Corpus: {CONTRACTS_DIR}")
    print(f"  Output: {OUTPUT_DIR}")
    print("=" * 70)

    gt = load_ground_truth(GROUND_TRUTH_PATH)
    if not gt:
        log.error("No ground truth loaded. Exiting.")
        return

    contracts = {}
    for contract_name in gt.keys():
        for ext in (".docx", ".pdf", ".txt"):
            candidate = CONTRACTS_DIR / (contract_name + ext) if not contract_name.endswith(ext) else CONTRACTS_DIR / contract_name
            if candidate.exists():
                text = load_contract_text(candidate)
                if text:
                    contracts[contract_name] = text
                break

    if not contracts:
        log.error("No contract texts loaded. Exiting.")
        return

    log.info(f"Loaded {len(contracts)} contract texts for evaluation")

    results = asyncio.run(run_all_extractions(contracts, MODELS))

    output_path = OUTPUT_DIR / "extraction_results.json"
    save_results(results, output_path)

    log.info("Pipeline complete. Run metrics_calc.py for evaluation.")


if __name__ == "__main__":
    main()
