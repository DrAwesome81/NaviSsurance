import argparse
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = PROJECT_ROOT / "data" / "artifacts" / "model_validation"
MODEL_CACHE_DIR = PROJECT_ROOT / "models" / "local_validation"
LLAMA_CLI_PATH = PROJECT_ROOT / "models" / "llama_cpp_b8190" / "runtime" / "llama-cli.exe"

CURRENT_MODEL_PATH = Path(
    "C:/Users/adamo/.cache/huggingface/hub/models--bartowski--Meta-Llama-3-8B-Instruct-GGUF/"
    "snapshots/2c3f8d7f3db06e3f9e8c4c6b6e6c7f3f8d9e4c6/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf"
)

CANDIDATES = [
    {
        "id": "llama3_8b_current_q4km",
        "label": "Current Meta-Llama-3-8B-Instruct Q4_K_M",
        "local_path": str(CURRENT_MODEL_PATH),
        "chat_format": "llama-3",
    },
    {
        "id": "qwen3_14b_q5km",
        "label": "Qwen3-14B Q5_K_M",
        "repo_id": "Qwen/Qwen3-14B-GGUF",
        "filename": "Qwen3-14B-Q5_K_M.gguf",
        "chat_format": None,
    },
    {
        "id": "gemma3_27b_q4",
        "label": "Gemma 3 27B IT Q4_K_M",
        "repo_id": "ggml-org/gemma-3-27b-it-GGUF",
        "filename": "gemma-3-27b-it-Q4_K_M.gguf",
        "chat_format": None,
    },
    {
        "id": "mistral_small_24b_q4km",
        "label": "Mistral Small 3.2 24B Q4_K_M",
        "repo_id": "unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF",
        "filename": "Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf",
        "chat_format": None,
    },
]


def notes_merge_prompt() -> str:
    return """Context: Working on usability study

You maintain a single working notes document for this context.

CURRENT DOCUMENT:
<<<DOCUMENT
## Participant Feedback
- Users understood the onboarding flow after a brief explanation.
- Two participants hesitated at the document upload step because the label was vague.

## Open Questions
- Whether the consent screen needs a clearer progress indicator.
DOCUMENT>>>

NEW OBSERVATION:
Participant 7 said the upload step looked optional because the button styling matched the secondary actions. She also expected the consent screen to explain why location data is requested.

INSTRUCTIONS:
- Merge the new observation into the current document.
- Rewrite for clarity, but preserve the meaning.
- Organize the document into useful section headings and concise bullet points.
- Consolidate duplicate or overlapping bullets instead of repeating them.
- Keep the whole document coherent as if it were one evolving work product.
- If the document is empty, create a sensible structure.

RESPONSE FORMAT:
Return ONLY valid JSON in this exact shape:
{"document": "Updated document text here"}
"""


def notes_reorg_prompt() -> str:
    return """Context: Working on usability study

You are refining a working notes document for this context.

DOCUMENT:
<<<DOCUMENT
## Participant Feedback
- Some users thought the upload step was optional because the button looked secondary.
- People generally understood onboarding after a short explanation.
- Several users wanted clearer wording around why location data is collected.
- Two users paused on the consent screen because the progress state was unclear.
- The upload label was described as vague.

## Follow-up
- Maybe update labels.
- Check if the progress indicator needs to be more explicit.
DOCUMENT>>>

INSTRUCTIONS:
- Reorganize the document into cleaner sections and tighter bullet points.
- Preserve the substance of the document.
- Merge duplicates and improve clarity.
- Keep it concise, but do not drop important details.

RESPONSE FORMAT:
Return ONLY valid JSON:
{"document": "Refined document text here"}
"""


def briefing_prompt() -> str:
    return (
        "Turn this briefing into a concise, helpful rundown in Navi's tone "
        "(direct, professional, calm; no snark). Use <br><br> between sections and keep it "
        "skimmable. Suggest concrete next actions for urgent items.\n\n"
        "Briefing:\n\n"
        "Inbox: 3 client emails need follow-up today.\n"
        "Calendar: 2 PM usability review, 4 PM investor prep.\n"
        "Risks: draft protocol still missing acceptance criteria section.\n"
        "Opportunities: Acme asked whether you can support design controls next month."
    )


PROMPTS = [
    ("notes_merge", notes_merge_prompt(), 320),
    ("notes_reorg", notes_reorg_prompt(), 320),
    ("briefing_format", briefing_prompt(), 220),
]


def ensure_dirs() -> None:
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def nvidia_smi_memory() -> tuple[int, int]:
    out = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip()
    used_str, total_str = [part.strip() for part in out.split(",")]
    return int(used_str), int(total_str)


class VramMonitor:
    def __init__(self, poll_interval: float = 0.25):
        self.poll_interval = poll_interval
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                used, _ = nvidia_smi_memory()
                self.samples.append(int(used))
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    @property
    def peak(self) -> int | None:
        return max(self.samples) if self.samples else None


def download_candidate(candidate: dict) -> str:
    local_path = candidate.get("local_path")
    if local_path:
        return local_path

    repo_id = candidate["repo_id"]
    filename = candidate["filename"]
    target_dir = MODEL_CACHE_DIR / candidate["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    return hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
    )


def call_model(llm: Llama, candidate: dict, prompt: str, max_tokens: int) -> dict:
    started = time.perf_counter()
    try:
        chat_kwargs = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.7,
        }
        response = llm.create_chat_completion(**chat_kwargs)
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        elapsed = time.perf_counter() - started
        usage = response.get("usage", {}) or {}
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return {
            "mode": "chat",
            "response": content,
            "elapsed_s": round(elapsed, 3),
            "completion_tokens": completion_tokens,
            "tok_per_s": round((completion_tokens / elapsed), 2) if completion_tokens and elapsed else None,
            "error": None,
        }
    except Exception as chat_error:
        raw_prompt = prompt
        if candidate.get("chat_format") == "llama-3":
            raw_prompt = f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        started = time.perf_counter()
        try:
            response = llm.create_completion(
                prompt=raw_prompt,
                max_tokens=max_tokens,
                temperature=0.2,
                top_p=0.7,
                echo=False,
            )
            content = response.get("choices", [{}])[0].get("text", "").strip()
            elapsed = time.perf_counter() - started
            usage = response.get("usage", {}) or {}
            completion_tokens = int(usage.get("completion_tokens") or 0)
            return {
                "mode": "completion",
                "response": content,
                "elapsed_s": round(elapsed, 3),
                "completion_tokens": completion_tokens,
                "tok_per_s": round((completion_tokens / elapsed), 2) if completion_tokens and elapsed else None,
                "error": f"chat_failed: {chat_error}",
            }
        except Exception as completion_error:
            elapsed = time.perf_counter() - started
            return {
                "mode": "failed",
                "response": "",
                "elapsed_s": round(elapsed, 3),
                "completion_tokens": 0,
                "tok_per_s": None,
                "error": f"chat_failed: {chat_error}; completion_failed: {completion_error}",
            }


def parse_cli_output(stdout: str) -> dict:
    generation_tps = None
    prompt_tps = None
    perf_match = re.search(r"\[\s*Prompt:\s*([0-9.]+)\s*t/s\s*\|\s*Generation:\s*([0-9.]+)\s*t/s\s*\]", stdout)
    if perf_match:
        prompt_tps = float(perf_match.group(1))
        generation_tps = float(perf_match.group(2))

    free_after_load_mib = None
    memory_match = re.search(r"CUDA0.*\|\s*(\d+)\s*=\s*(\d+)\s*\+\s*\((\d+)\s*=", stdout)
    if memory_match:
        free_after_load_mib = int(memory_match.group(2))

    response = stdout
    if "\n> " in stdout:
        response = stdout.split("\n> ", 1)[1]
    if "llama_memory_breakdown_print:" in response:
        response = response.split("llama_memory_breakdown_print:", 1)[0]
    response = response.strip()

    return {
        "response": response,
        "prompt_tps": prompt_tps,
        "generation_tps": generation_tps,
        "free_after_load_mib": free_after_load_mib,
    }


def call_model_cli(llama_cli_path: Path, model_path: str, candidate: dict, prompt: str, max_tokens: int, gpu_layers: str) -> dict:
    command = [
        str(llama_cli_path),
        "--model",
        model_path,
        "--device",
        "CUDA0",
        "--gpu-layers",
        str(gpu_layers),
        "--ctx-size",
        "8192",
        "--simple-io",
        "--single-turn",
        "--reasoning-budget",
        "0",
        "--n-predict",
        str(max_tokens),
        "--prompt",
        prompt,
    ]
    if candidate.get("chat_format"):
        command.extend(["--chat-template", candidate["chat_format"]])
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    elapsed = time.perf_counter() - started
    parsed = parse_cli_output(completed.stdout or "")
    return {
        "mode": "llama_cli",
        "response": parsed["response"],
        "elapsed_s": round(elapsed, 3),
        "completion_tokens": None,
        "tok_per_s": parsed["generation_tps"],
        "prompt_tok_per_s": parsed["prompt_tps"],
        "free_after_load_mib": parsed["free_after_load_mib"],
        "error": None if completed.returncode == 0 else (completed.stderr or completed.stdout),
        "return_code": completed.returncode,
    }


def benchmark_candidate(candidate: dict, reserve_vram_gb: int, runtime: str, gpu_layers: str) -> dict:
    result: dict = {
        "candidate_id": candidate["id"],
        "label": candidate["label"],
        "runtime": runtime,
        "model_path": None,
        "downloaded": False,
        "load_error": None,
        "load_time_s": None,
        "memory_before_mib": None,
        "memory_after_load_mib": None,
        "memory_peak_mib": None,
        "memory_total_mib": None,
        "memory_free_after_load_mib": None,
        "reserve_target_mib": reserve_vram_gb * 1024,
        "reserve_pass": None,
        "prompts": [],
    }

    model_path = download_candidate(candidate)
    result["model_path"] = model_path
    result["downloaded"] = bool(candidate.get("repo_id"))

    before_used, total_mib = nvidia_smi_memory()
    result["memory_before_mib"] = before_used
    result["memory_total_mib"] = total_mib

    monitor = VramMonitor()
    monitor.start()
    llm = None
    load_started = time.perf_counter()
    try:
        if runtime == "python":
            llm_kwargs = {
                "model_path": model_path,
                "n_gpu_layers": -1 if str(gpu_layers).lower() == "all" else int(gpu_layers),
                "n_ctx": 8192,
                "n_threads": max(os.cpu_count() or 4, 4),
                "verbose": False,
            }
            if candidate.get("chat_format"):
                llm_kwargs["chat_format"] = candidate["chat_format"]
            llm = Llama(**llm_kwargs)
            result["load_time_s"] = round(time.perf_counter() - load_started, 3)
            after_used, _ = nvidia_smi_memory()
            result["memory_after_load_mib"] = after_used
            result["memory_free_after_load_mib"] = total_mib - after_used
            result["reserve_pass"] = bool((total_mib - after_used) >= reserve_vram_gb * 1024)

            for prompt_name, prompt_text, max_tokens in PROMPTS:
                prompt_result = call_model(llm, candidate, prompt_text, max_tokens)
                prompt_result["prompt_name"] = prompt_name
                result["prompts"].append(prompt_result)
        elif runtime == "llama_cli":
            if not LLAMA_CLI_PATH.exists():
                raise FileNotFoundError(f"llama-cli not found at {LLAMA_CLI_PATH}")
            result["load_time_s"] = None
            for prompt_name, prompt_text, max_tokens in PROMPTS:
                prompt_result = call_model_cli(LLAMA_CLI_PATH, model_path, candidate, prompt_text, max_tokens, gpu_layers)
                prompt_result["prompt_name"] = prompt_name
                if prompt_result.get("free_after_load_mib") is not None and result["memory_free_after_load_mib"] is None:
                    result["memory_free_after_load_mib"] = prompt_result["free_after_load_mib"]
                    result["memory_after_load_mib"] = total_mib - prompt_result["free_after_load_mib"]
                    result["reserve_pass"] = bool(prompt_result["free_after_load_mib"] >= reserve_vram_gb * 1024)
                result["prompts"].append(prompt_result)
        else:
            raise ValueError(f"Unsupported runtime: {runtime}")
    except Exception as exc:
        result["load_error"] = str(exc)
    finally:
        monitor.stop()
        result["memory_peak_mib"] = monitor.peak
        if result["reserve_pass"] is None and result["memory_peak_mib"] is not None:
            result["memory_after_load_mib"] = result["memory_peak_mib"]
            result["memory_free_after_load_mib"] = total_mib - result["memory_peak_mib"]
            result["reserve_pass"] = bool(result["memory_free_after_load_mib"] >= reserve_vram_gb * 1024)
        if llm is not None:
            try:
                del llm
            except Exception:
                pass
        time.sleep(2)

    return result


def write_outputs(results: list[dict]) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = ARTIFACTS_DIR / f"local_model_validation_{stamp}.json"
    md_path = ARTIFACTS_DIR / f"local_model_validation_{stamp}.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = [
        "# Local Model Validation",
        "",
        f"Generated: `{datetime.now().isoformat(timespec='seconds')}`",
        "",
        "| Candidate | Load | Load s | After Load MiB | Free After Load MiB | Peak MiB | Reserve Pass |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        lines.append(
            "| {label} | {load} | {load_time} | {after_load} | {free_after} | {peak} | {reserve_pass} |".format(
                label=result["label"],
                load="ok" if not result["load_error"] else "fail",
                load_time=result["load_time_s"] or "-",
                after_load=result["memory_after_load_mib"] or "-",
                free_after=result["memory_free_after_load_mib"] or "-",
                peak=result["memory_peak_mib"] or "-",
                reserve_pass=result["reserve_pass"] if result["reserve_pass"] is not None else "-",
            )
        )
        for prompt_result in result["prompts"]:
            lines.extend(
                [
                    "",
                    f"## {result['label']} / {prompt_result['prompt_name']}",
                    "",
                    f"- Mode: `{prompt_result['mode']}`",
                    f"- Elapsed: `{prompt_result['elapsed_s']} s`",
                    f"- Completion tokens: `{prompt_result['completion_tokens']}`",
                    f"- Tokens/sec: `{prompt_result['tok_per_s']}`",
                    f"- Prompt tokens/sec: `{prompt_result.get('prompt_tok_per_s')}`",
                    f"- Error: `{prompt_result['error']}`",
                    "",
                    "```text",
                    (prompt_result["response"] or "").strip()[:4000],
                    "```",
                ]
            )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local GGUF models on the current GPU.")
    parser.add_argument(
        "--candidate",
        action="append",
        choices=[candidate["id"] for candidate in CANDIDATES],
        help="Candidate id to run. Repeat to run multiple. Defaults to all.",
    )
    parser.add_argument(
        "--reserve-vram-gb",
        type=int,
        default=8,
        help="How much VRAM to keep free after model load.",
    )
    parser.add_argument(
        "--runtime",
        choices=["python", "llama_cli"],
        default="python",
        help="Inference runtime to benchmark.",
    )
    parser.add_argument(
        "--gpu-layers",
        default="33",
        help="GPU layer setting for the benchmark runtime. Use 'all' for full offload where supported.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()
    selected = set(args.candidate or [candidate["id"] for candidate in CANDIDATES])
    chosen = [candidate for candidate in CANDIDATES if candidate["id"] in selected]
    results = [
        benchmark_candidate(
            candidate,
            reserve_vram_gb=args.reserve_vram_gb,
            runtime=args.runtime,
            gpu_layers=args.gpu_layers,
        )
        for candidate in chosen
    ]
    json_path, md_path = write_outputs(results)
    print(f"Wrote JSON results to {json_path}")
    print(f"Wrote Markdown summary to {md_path}")


if __name__ == "__main__":
    main()
