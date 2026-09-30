"""工作台展示状态的纯逻辑测试。"""

from types import SimpleNamespace

from vehicle_valuation.ui_workspace import (
    active_stage_index,
    collect_attention_items,
    derive_workflow_stages,
)


def test_workflow_progress_uses_existing_business_state() -> None:
    session = {
        "initial_checks_passed": True,
        "confirmed_market_cases": [object(), object(), object()],
        "adjustments_approved": True,
        "final_valuation_value": 80_000,
    }

    stages = derive_workflow_stages(session)

    assert [stage.done for stage in stages] == [True, True, True, True, False]
    assert active_stage_index(stages) == 4


def test_attention_center_only_collects_manual_exceptions() -> None:
    session = {
        "license_calibration": SimpleNamespace(
            requires_review=True,
            review_reasons=["VIN无法唯一校准"],
            corrections=[],
        ),
        "license_precheck_conflicts": [
            SimpleNamespace(message="Excel与行驶证车牌冲突")
        ],
        "market_agent_state": SimpleNamespace(
            status="awaiting_human_input", trace=[]
        ),
    }

    assert collect_attention_items(session) == [
        "VIN无法唯一校准",
        "Excel与行驶证车牌冲突",
        "市场案例不足，需要补充案例或恢复搜索",
    ]
