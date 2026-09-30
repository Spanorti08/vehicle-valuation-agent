"""运行离线工作流评测并写入可追踪的 JSON 结果。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from vehicle_valuation.workflow_evaluation import run_workflow_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="评测字段校准、异常分流、LangGraph搜索与RAG检索"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT
            / "data/evaluation/workflow_evaluation_results.json"
        ),
    )
    args = parser.parse_args()

    result = run_workflow_evaluation(PROJECT_ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n结果已写入：{args.output}")


if __name__ == "__main__":
    main()
