# Local Model Validation

Last updated: 2026-05-12

## Production note (current app)
The shipped desktop app uses **`Qwen3-14B Q5_K_M`** (GGUF on disk; filename uses underscores) via the standalone **`llama-cli`** subprocess wired in `config.py` and `core/local_llm.py` (see `docs/llm_routing.md`). Everything from **Baseline** through **Recommendation** below is **benchmark history** from the validation sprint, not the current runtime description.

## Goal
Validate stronger local models on the `RTX 5090 32GB` while preserving about `8 GB` of VRAM headroom, then decide the safest near-term routing for `Notes`.

## Baseline (at time of benchmark)
- Embedded worker script: `core/llama_worker.py`
- Embedded runtime under test: `llama-cpp-python 0.3.8+cu128.gemma3`
- Embedded model under test: `Meta-Llama-3-8B-Instruct Q4_K_M`
- Offload setting used in tests: `n_gpu_layers=33`

## Key Runtime Finding
The current embedded Python runtime is the main blocker, not the GPU.

- Direct Python load of the current local model crashed immediately with:
  - `ggml-cuda.cu:73: CUDA error`
- Standalone `llama.cpp b8190` Windows CUDA `13.1` runtime loaded and ran models successfully on the same machine.

## Tested Runtime
- Runtime used for successful model validation: standalone `llama.cpp b8190`
- CLI path: `models/llama_cpp_b8190/runtime/llama-cli.exe`
- Test configuration:
  - `gpu_layers=33`
  - `ctx_size=8192`
  - real prompt fixtures based on `Notes` merge/reorg and briefing formatting

## Results
| Candidate | Peak VRAM | Free VRAM | Reserve Pass | Notes Quality | Relative Latency |
|---|---:|---:|---|---|---|
| Current `Llama 3 8B Q4_K_M` | `7733 MiB` | about `24874 MiB` | `True` | poor | fastest |
| `Qwen3-14B Q5_K_M` | `11374 MiB` | about `21233 MiB` | `True` | strong | best balance |
| `Gemma 3 27B IT Q4_K_M` | `22616 MiB` | `9991 MiB` | `True` | strong | too slow |
| `Mistral Small 3.2 24B Q4_K_M` | `20477 MiB` | `12130 MiB` | `True` | good | solid |

## Quality Notes
### Qwen3-14B Q5_K_M
- Best overall fit for `Notes`.
- Produced clean structured JSON for merge/reorg prompts.
- Preserved intent and consolidated overlapping bullets well.
- Much faster than the larger candidates.

### Gemma 3 27B IT Q4_K_M
- Output quality was good.
- It barely stayed above the `8 GB` reserve target.
- Latency was far worse than the other viable options.
- Not a good multitasking default despite technically fitting.

### Mistral Small 3.2 24B Q4_K_M
- Good quality and meaningfully faster than Gemma.
- Still much heavier than Qwen.
- More headroom than Gemma, but not enough quality advantage to justify replacing Qwen as the default choice for `Notes`.

### Current Llama 3 8B Q4_K_M
- Stable in standalone `llama.cpp`, but weak on the actual structured prompts.
- Output quality was clearly worse than the three candidate models.
- Not worth keeping as the long-term local `Notes` model.

## Measured Latency Summary
- `Qwen3-14B Q5_K_M`
  - notes merge: about `11.7 s`
  - notes reorg: about `11.7 s`
  - briefing format: about `11.9 s`
- `Mistral Small 3.2 24B Q4_K_M`
  - notes merge: about `16.4 s`
  - notes reorg: about `18.6 s`
  - briefing format: about `21.3 s`
- `Gemma 3 27B IT Q4_K_M`
  - notes merge: about `45.4 s`
  - notes reorg: about `78.0 s`
  - briefing format: about `67.5 s`

## Recommendation
### Chosen local model
- `Qwen3-14B Q5_K_M`

### Chosen runtime path
- Move away from the current embedded `llama-cpp-python` worker for GPU inference on this machine.
- Target standalone `llama.cpp` as the local runtime path for Windows/Blackwell.

### Routing decision for now
- Keep `CoS` on `Grok`.
- Route `Notes` to `Grok` temporarily if reliability is more important than keeping `Notes` local right now.
- Do not keep using the current embedded local worker for `Notes` on this machine until the runtime is upgraded away from the crashing Python path.

## Practical Conclusion (historical)
If you want the best near-term user experience:
- short term: use `Grok` for `Notes`
- medium term: migrate local structured tasks to standalone `llama.cpp` with `Qwen3-14B Q5_K_M`
- do not invest further in the current `llama-cpp-python` worker setup on this `5090`

## Artifacts
- `scripts/validate_local_models.py`
- `data/artifacts/model_validation/local_model_validation_20260310_143636.md`
- `data/artifacts/model_validation/local_model_validation_20260310_144336.md`
- `data/artifacts/model_validation/local_model_validation_20260310_150235.md`
- `data/artifacts/model_validation/local_model_validation_20260310_151117.md`
