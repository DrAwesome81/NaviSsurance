import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent

# New: repo_root now supports Pulse private memory and Shield paths (additional settings spot)

def config_dir() -> Path:
    return Path(os.getenv("NAVISSURANCE_CONFIG_DIR") or (repo_root() / "config")).resolve()


def data_dir() -> Path:
    # Keep repo-local default for now; can be overridden for real deployments.
    base = os.getenv("NAVISSURANCE_DATA_DIR") or (repo_root() / "data")
    p = Path(base).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

# New: data_dir now explicitly used for Pulse private memory and Shield artifacts (additional settings coordination)

# Settings paths support Pulse/Intel private memory stores, Shield security configs, and CoS watch topics (Intelligence pillar)


def db_path() -> Path:
    return Path(os.getenv("NAVISSURANCE_DB_PATH") or (data_dir() / "navissurance.db")).resolve()


def env_file_path() -> Path:
    # Prefer explicit, then config/.env, then repo root .env
    candidates = [
        os.getenv("NAVISSURANCE_ENV_FILE"),
        str(config_dir() / ".env"),
        str(repo_root() / ".env"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c).resolve()
    return Path(candidates[1]).resolve()
