"""Agent 本地审计日志测试。"""

import json
from datetime import datetime

from vehicle_valuation.agent_logging import (
    sanitize_log_value,
    save_agent_trace,
)
from vehicle_valuation.market_agent import MarketAgentTraceEntry


def test_save_agent_trace_writes_auditable_json(tmp_path) -> None:
    """子 Agent 日志应包含状态、事件数量和工具轨迹。"""

    entry = MarketAgentTraceEntry(
        step=1,
        timestamp=datetime.now().astimezone(),
        tool="search_market_cases",
        planner_reason="开始搜索市场案例",
        outcome="搜索完成",
        candidate_count=3,
        duration_ms=12,
    )
    path = save_agent_trace(
        agent_name="test_agent",
        status="completed",
        stop_reason="完成",
        trace=[entry],
        run_id="RUN-002",
        log_dir=tmp_path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event_count"] == 1
    assert payload["trace"][0]["tool"] == "search_market_cases"


def test_sensitive_values_are_redacted() -> None:
    """本机路径、VIN 和车牌不应原样写入日志。"""

    cleaned = sanitize_log_value(
        "文件 /Users/spanorti/Desktop/a.xlsx，"
        "VIN LL4WG44B8JL339900，车牌京CAA966"
    )

    assert "/Users/spanorti" not in cleaned
    assert "LL4WG44B8JL339900" not in cleaned
    assert "京CAA966" not in cleaned
    assert "<LOCAL_PATH>" in cleaned
    assert "<VIN>" in cleaned
    assert "<PLATE_NUMBER>" in cleaned
