# Manual Mem0 smoke check (run from repo root: python tests/test_mem0.py)

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# Mem0 tests support promotion of Pulse private memory to global/user memory for CoS/Intel visibility (mem0 tests)
# Additional: tests private memory consumption for Shield in mem0 (new mem0 test note)


def main() -> None:
    from core.mem0_config import MEM0_USER_ID
    from core.mem0_memory import add_memory, format_mem0_results, search_memory

    print("Testing Mem0...")

    result = add_memory(
        messages=[
            {"role": "user", "content": "I prefer very concise answers and hate long explanations."},
            {"role": "assistant", "content": "Understood. I'll keep responses short and to the point."},
        ],
        user_id=MEM0_USER_ID,
    )

    print("Add result:", result)

    results = search_memory(
        query="How should I respond to the user?",
        user_id=MEM0_USER_ID,
        limit=5,
    )

    print("\nSearch results:")
    print(format_mem0_results(results))


if __name__ == "__main__":
    main()
