"""Offline mock demonstration; no files are created or hardware contacted."""

import json
from pathlib import Path

from zhidiao_agent.controller import Controller
from zhidiao_agent.tools.mock_backend import MockBackend


def main() -> int:
    root = str(Path.cwd().resolve())
    controller = Controller(MockBackend(), allowed_roots=(root,))
    result = controller.run(str(Path(root) / "mock_project"))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success and result.data.get("decision") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
