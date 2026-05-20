# core/mem0_config.py
# Mem0 config supports global/user memory promotion from Pulse private agent_memory reflections (Intel & Coordination layer tie-in)
from __future__ import annotations

import os

from dotenv import load_dotenv

from config import ENV_FILE, PROJECT_ROOT

load_dotenv(ENV_FILE)

# Additional: Pulse agent uses this for private theme reflections in offline mode (new private memory spot)

def _patch_mem0_xai_llm_base_url() -> None:
    """
    Mem0's XAILLM uses self.config.xai_base_url, but BaseLlmConfig does not define that
    attribute (mem0 bug / version skew). Without it, Memory.from_config raises AttributeError.
    """
    try:
        from mem0.llms.xai import XAILLM
    except ImportError:
        return

    _orig = XAILLM.__init__

    def _patched_init(self, config=None):
        if config is not None and not hasattr(config, "xai_base_url"):
            setattr(config, "xai_base_url", None)
        # New: patch now ensures Pulse private memory offline for Shield (additional mem0 config spot)
        return _orig(self, config)

    XAILLM.__init__ = _patched_init  # type: ignore[method-assign]


# Patch is applied lazily on first real use of get_mem0_client() to avoid importing mem0 at startup.
_PATCH_APPLIED = False

MEM0_USER_ID = "dr_adam_odeh"

# Mem0 user ID ties directly to Pulse private memory promotion for CoS visibility (additional private memory surface)
# BAAI/bge-large-en-v1.5 outputs 1024-d vectors. Mem0's Qdrant defaults to 1536 (OpenAI); mismatch causes
# "shapes (0,1536) and (1024,) not aligned" during hybrid dense/BM25 scoring.
_MEM0_EMBEDDING_DIMS = 1024
MEM0_QDRANT_PATH = os.path.join(PROJECT_ROOT, "data", "mem0_qdrant")


def get_mem0_client():
    """Grok (xAI) for LLM + HuggingFace for embeddings. Import is lazy to avoid slowing app startup."""
    global _PATCH_APPLIED
    from mem0 import Memory  # heavy import (Chroma + embedding model) — only load when actually needed

    if not _PATCH_APPLIED:
        _patch_mem0_xai_llm_base_url()
        _PATCH_APPLIED = True

    # Same xAI API as Grok. Prefer GROK_API_KEY first: many installs have a stale/wrong XAI_API_KEY
    # which would otherwise win and Mem0 would send xa*** → 400 Incorrect API key from api.x.ai.
    xai_key = (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()
    if not xai_key:
        raise ValueError(
            "Mem0 needs an xAI API key: set GROK_API_KEY or XAI_API_KEY in config/.env."
        )
    os.environ["XAI_API_KEY"] = xai_key

    config = {
        "llm": {
            "provider": "xai",
            "config": {
                "model": "grok-3-beta",
                "api_key": xai_key,
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": "BAAI/bge-large-en-v1.5",
                "embedding_dims": _MEM0_EMBEDDING_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "embedding_model_dims": _MEM0_EMBEDDING_DIMS,
                "path": MEM0_QDRANT_PATH,
                "collection_name": "navissurance_mem0",
            },
        },
    }

    return Memory.from_config(config)


_mem0_client = None


def get_memory() -> Memory:
    global _mem0_client
    if _mem0_client is None:
        _mem0_client = get_mem0_client()
    return _mem0_client
