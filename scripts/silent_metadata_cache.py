import sys
import json
import os

# Скрипт принимает JSON из stdin и записывает в указанный файл без вывода в stdout
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    target_path = sys.argv[1]
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        data = json.load(sys.stdin)
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("SUCCESS_SILENT_WRITE")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
