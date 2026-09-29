"""Agent 本地审计日志。

日志只保存流程元数据和工具轨迹，不保存上传文件、OCR 原图或完整业务对象。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_AGENT_LOG_DIR = Path("logs/agent")


def create_run_id() -> str:
    """创建不包含业务信息的随机运行编号。"""

    return uuid4().hex


def sanitize_log_value(value: Any) -> Any:
    """递归清理日志中的本机路径、VIN 和常见车牌格式。"""

    if isinstance(value, dict):
        return {
            str(key): sanitize_log_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_log_value(item) for item in value]
    if not isinstance(value, str):
        return value

    cleaned = re.sub(
        r"/(?:Users|home)/[^\s,，；;]+",
        "<LOCAL_PATH>",
        value,
    )
    cleaned = re.sub(
        r"\b[A-HJ-NPR-Z0-9]{17}\b",
        "<VIN>",
        cleaned,
    )
    cleaned = re.sub(
        r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]"
        r"[A-Z][A-Z0-9·]{5,6}",
        "<PLATE_NUMBER>",
        cleaned,
    )
    return cleaned


def save_agent_trace(
    agent_name: str,
    status: str,
    stop_reason: str,
    trace: list[Any],
    run_id: str | None = None,
    log_dir: Path = DEFAULT_AGENT_LOG_DIR,
) -> Path:
    """把一次子 Agent 的完整工具轨迹保存为 JSON。"""

    actual_run_id = run_id or create_run_id()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{agent_name}-{actual_run_id}.json"
    trace_data = [
        entry.model_dump(mode="json")
        if hasattr(entry, "model_dump")
        else entry
        for entry in trace
    ]
    payload = sanitize_log_value(
        {
            "schema_version": 1,
            "created_at": datetime.now().astimezone().isoformat(),
            "run_id": actual_run_id,
            "agent": agent_name,
            "status": status,
            "stop_reason": stop_reason,
            "event_count": len(trace_data),
            "trace": trace_data,
        }
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
