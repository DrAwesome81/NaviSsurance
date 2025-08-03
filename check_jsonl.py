import json

with open("data/fine_tune.jsonl", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        try:
            json.loads(line.strip())
            print(f"Line {i+1}: Valid")
        except json.JSONDecodeError as e:
            print(f"Line {i+1}: Invalid - {e}")