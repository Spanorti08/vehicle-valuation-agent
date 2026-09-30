"""受控市场案例搜索 Agent 的单元与模拟端到端测试。"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from vehicle_valuation.market_agent import (
    ControlledMarketAgent,
    MarketAgentConfig,
    MarketAgentDecision,
    MarketAgentState,
    RuleBasedMarketAgentPlanner,
)
from vehicle_valuation.model import MarketListing


def make_listing(
    case_id: str,
    year: int = 2018,
    mileage_km: int = 80_000,
) -> MarketListing:
    """创建一条达到测试相似度门槛的模拟车源。"""

    return MarketListing(
        source_url=(
            "https://www.guazi.com/car-detail/"
            f"{case_id}.html"
        ),
        vehicle_model="奔驰C级 2018款 C 200 L 运动版",
        registration_year=year,
        mileage_km=mileage_km,
        city="测试城市",
        price_cny=Decimal("80000"),
    )


def make_state() -> MarketAgentState:
    """创建一次标准的 Agent 搜索状态。"""

    return MarketAgentState(
        market_keyword="C 200 L",
        series_path="benz/benz-c",
        target_year=2018,
        target_mileage_km=80_000,
    )


class FakeSearchBackend:
    """按城市批次返回预设结果，避免测试访问真实网站。"""

    def __init__(self, responses: dict[tuple[str, ...], tuple]):
        """保存每个城市组合对应的模拟响应。"""

        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def search(self, city_paths, series_path):
        """返回预设车源和失败城市。"""

        key = tuple(city_paths)
        self.calls.append(key)
        return self.responses.get(key, ([], []))


class UnsafePlanner:
    """故意在第二步提出过早结束，用来验证策略拦截。"""

    def plan(self, state, allowed_tools):
        """返回未经策略允许的安全停止动作。"""

        if state.step_count == 0:
            return MarketAgentDecision(
                tool="search_market_cases",
                reason="先搜索",
            )

        return MarketAgentDecision(
            tool="stop_safely",
            reason="尝试过早结束",
        )


def test_agent_expands_scope_and_finalizes_candidate_pool() -> None:
    """首批案例不足时应自动扩展，达标后结束搜索。"""

    backend = FakeSearchBackend(
        {
            ("bj",): ([make_listing("one")], []),
            ("sh",): (
                [make_listing("two"), make_listing("three")],
                [],
            ),
        }
    )
    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=backend,
        config=MarketAgentConfig(
            city_batches=[["bj"], ["sh"]],
        ),
    )

    state = agent.run_until_pause(make_state())

    assert state.status == "candidates_ready"
    assert len(state.candidates) == 3
    assert backend.calls == [("bj",), ("sh",)]
    assert [entry.tool for entry in state.trace] == [
        "search_market_cases",
        "evaluate_case_quality",
        "expand_search_city",
        "evaluate_case_quality",
        "finalize_candidate_pool",
    ]


def test_agent_retries_failed_city_within_budget() -> None:
    """城市失败后只在配置预算内自动重试。"""

    class RetryBackend:
        """第一次失败，第二次返回三个案例。"""

        def __init__(self):
            self.call_count = 0

        def search(self, city_paths, series_path):
            self.call_count += 1
            if self.call_count == 1:
                return [], ["bj"]
            return [
                make_listing("one"),
                make_listing("two"),
                make_listing("three"),
            ], []

    backend = RetryBackend()
    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=backend,
        config=MarketAgentConfig(
            city_batches=[["bj"]],
            max_retries_per_city=1,
        ),
    )

    state = agent.run_until_pause(make_state())

    assert state.status == "candidates_ready"
    assert backend.call_count == 2
    assert state.retry_counts == {"bj": 1}
    assert "retry_failed_search" in [
        entry.tool for entry in state.trace
    ]


def test_agent_pauses_when_cases_remain_insufficient() -> None:
    """搜索资源耗尽且案例不足时应暂停而非无限循环。"""

    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=FakeSearchBackend(
            {("bj",): ([make_listing("only")], [])}
        ),
        config=MarketAgentConfig(city_batches=[["bj"]]),
    )

    state = agent.run_until_pause(make_state())

    assert state.status == "awaiting_human_input"
    assert len(state.candidates) == 1
    assert "仅找到 1 个" in state.stop_reason
    assert state.trace[-1].tool == "stop_safely"


def test_langgraph_checkpoint_can_resume_after_human_input(tmp_path) -> None:
    """SQLite checkpoint 应支持跨 Agent 实例恢复暂停的搜索。"""

    checkpoint_path = tmp_path / "market_graph.sqlite"
    config = MarketAgentConfig(city_batches=[["bj"]])
    first_agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=FakeSearchBackend(
            {("bj",): ([make_listing("one")], [])}
        ),
        config=config,
        checkpoint_path=checkpoint_path,
    )

    paused = first_agent.run_until_pause(make_state())
    thread_id = paused.graph_thread_id

    assert paused.status == "awaiting_human_input"
    assert first_agent.get_checkpoint_state(thread_id).status == (
        "awaiting_human_input"
    )
    assert "human_input" in first_agent.graph_mermaid
    first_agent.close()

    resumed_agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=FakeSearchBackend({}),
        config=config,
        checkpoint_path=checkpoint_path,
    )
    resumed = resumed_agent.resume_with_human_cases(
        thread_id,
        [make_listing("two"), make_listing("three")],
    )

    assert resumed.status == "candidates_ready"
    assert len(resumed.candidates) == 3
    assert resumed.trace[-1].tool == "finalize_candidate_pool"
    resumed_agent.close()


def test_langgraph_checkpoint_state_keeps_binary_evidence() -> None:
    """图状态序列化不能丢失后续报告所需的网页截图。"""

    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=FakeSearchBackend({}),
    )
    state = make_state()
    state.preview_screenshots = {
        "https://example.com/case": (b"top-image", b"detail-image")
    }

    payload = agent._serialize_agent_state(state)
    restored = MarketAgentState.model_validate(payload)

    assert restored.preview_screenshots == state.preview_screenshots


def test_policy_replaces_disallowed_planner_action() -> None:
    """Planner 过早停止时策略层应改成当前允许的工具。"""

    backend = FakeSearchBackend(
        {
            ("bj",): ([make_listing("one")], []),
            ("sh",): (
                [make_listing("two"), make_listing("three")],
                [],
            ),
        }
    )
    agent = ControlledMarketAgent(
        planner=UnsafePlanner(),
        search_backend=backend,
        config=MarketAgentConfig(
            city_batches=[["bj"], ["sh"]],
        ),
    )

    state = agent.run_until_pause(make_state())

    assert state.status == "candidates_ready"
    assert state.trace[1].tool == "evaluate_case_quality"
    assert "策略层拒绝 stop_safely" in state.trace[1].policy_note


def test_selection_policy_completes_ready_candidate_pool() -> None:
    """Agent 找到案例后由外部确定性 Top 3 策略完成选择。"""

    backend = FakeSearchBackend(
        {
            ("bj",): (
                [
                    make_listing("one"),
                    make_listing("two"),
                    make_listing("three"),
                ],
                [],
            )
        }
    )
    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=backend,
        config=MarketAgentConfig(city_batches=[["bj"]]),
    )

    state = agent.run_until_pause(make_state())
    assert state.status == "candidates_ready"

    approved = agent.approve_candidates(state)
    assert approved.status == "completed"


def test_agent_stops_at_maximum_step_budget() -> None:
    """达到最大步骤预算时应停止，不继续调用工具。"""

    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=FakeSearchBackend({("bj",): ([], [])}),
        config=MarketAgentConfig(
            city_batches=[["bj"], ["sh"]],
            max_steps=1,
        ),
    )

    state = agent.run_until_pause(make_state())

    assert state.status == "failed"
    assert state.step_count == 1
    assert "最大步骤数" in state.stop_reason


def test_agent_exposes_exact_flowchart_tool_whitelist() -> None:
    """工具名应与用户流程图逐项一致。"""

    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=FakeSearchBackend({}),
    )

    assert agent.tool_names == (
        "search_market_cases",
        "evaluate_case_quality",
        "expand_search_city",
        "adjust_year_range",
        "adjust_mileage_range",
        "refine_search_keyword",
        "retry_failed_search",
        "switch_data_source",
        "finalize_candidate_pool",
        "stop_safely",
    )


def test_candidate_quality_floor_cannot_be_configured_below_sixty() -> None:
    """即使调用方传错参数，也不能让60分以下案例进入候选池。"""

    with pytest.raises(ValidationError):
        MarketAgentConfig(minimum_quality_score=59)

    with pytest.raises(ValidationError):
        MarketAgentConfig(minimum_similarity_score=59)


def test_incomplete_human_review_returns_to_search_agent() -> None:
    """人工复核不足三例时必须退回搜索状态。"""

    backend = FakeSearchBackend(
        {
            ("bj",): (
                [make_listing("one"), make_listing("two"), make_listing("three")],
                [],
            )
        }
    )
    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=backend,
        config=MarketAgentConfig(city_batches=[["bj"]]),
    )
    state = agent.run_until_pause(make_state())

    returned = agent.return_incomplete_cases(
        state,
        [str(state.candidates[0].source_url)],
    )

    assert returned.status == "running"
    assert len(returned.candidates) == 2
    assert "返回搜索 Agent" in returned.stop_reason


def test_agent_deduplicates_listings_across_tools() -> None:
    """不同城市返回同一链接时只保留一个案例。"""

    duplicate = make_listing("same")
    backend = FakeSearchBackend(
        {
            ("bj",): ([duplicate], []),
            ("sh",): ([duplicate], []),
        }
    )
    agent = ControlledMarketAgent(
        planner=RuleBasedMarketAgentPlanner(),
        search_backend=backend,
        config=MarketAgentConfig(
            city_batches=[["bj"], ["sh"]],
        ),
    )

    state = agent.run_until_pause(make_state())

    assert len(state.all_listings) == 1
    assert len(state.candidates) == 1
    assert state.status == "awaiting_human_input"
