"""基于 LangGraph 的车辆市场案例搜索 Agent。

Planner 只能从白名单工具中选择下一步；搜索、质量评分、扩城、放宽条件、
重试与安全停止均由确定性执行器完成。LangGraph 负责状态路由、checkpoint、
暂停与恢复，合格案例足够时交给确定性 Top 3 策略自动采用。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from vehicle_valuation.agent_logging import create_run_id, save_agent_trace
from vehicle_valuation.llm_provider import OllamaProvider
from vehicle_valuation.market_quality import (
    MarketCaseQuality,
    RejectedMarketCase,
    score_market_cases,
)
from vehicle_valuation.market_scraper import (
    calculate_listing_similarity,
    capture_market_listing_snapshots_batch,
    fetch_guazi_listings_from_cities,
)
from vehicle_valuation.model import MarketListing, MarketListingDetail


AgentToolName = Literal[
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
]

AgentStatus = Literal[
    "running",
    "candidates_ready",
    "awaiting_human_input",
    "completed",
    "failed",
]


class MarketAgentDecision(BaseModel):
    tool: AgentToolName
    reason: str = Field(min_length=1)


class MarketAgentTraceEntry(BaseModel):
    step: int = Field(ge=1)
    timestamp: datetime
    tool: AgentToolName
    planner_reason: str
    policy_note: str = ""
    outcome: str
    candidate_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class MarketAgentConfig(BaseModel):
    """用户可确认的搜索条件及运行预算。"""

    city_batches: list[list[str]] = Field(
        default_factory=lambda: [["bj", "sh"], ["gz", "sz"]]
    )
    allowed_sources: list[str] = Field(default_factory=lambda: ["guazi"])
    target_count: int = Field(default=3, ge=3)
    candidate_limit: int = Field(default=10, ge=3)
    minimum_quality_score: int = Field(
        default=60,
        ge=60,
        le=100,
        description="候选案例质量硬下限，任何流程均不得低于60分",
    )
    minimum_similarity_score: int = Field(
        default=60,
        ge=60,
        le=100,
        description="年份与里程综合匹配分硬下限",
    )
    initial_year_tolerance: int = Field(default=1, ge=0, le=5)
    maximum_year_tolerance: int = Field(default=2, ge=0, le=8)
    initial_mileage_tolerance_km: int = Field(default=50_000, ge=0)
    maximum_mileage_tolerance_km: int = Field(default=100_000, ge=0)
    mileage_tolerance_step_km: int = Field(default=25_000, gt=0)
    max_keyword_refinements: int = Field(default=1, ge=0, le=3)
    max_search_rounds: int = Field(default=8, ge=1, le=30)
    max_steps: int = Field(default=24, ge=1, le=80)
    max_retries_per_city: int = Field(default=1, ge=0, le=3)


class MarketAgentState(BaseModel):
    """一次搜索中所有可恢复、可审计的状态。"""

    market_keyword: str = Field(min_length=1)
    series_path: str = Field(min_length=1)
    target_year: int = Field(ge=1900, le=2200)
    target_mileage_km: int = Field(ge=0)
    initial_cities: list[str] = Field(default_factory=list)
    allowed_sources: list[str] = Field(default_factory=lambda: ["guazi"])
    current_source_index: int = Field(default=0, ge=0)
    used_keywords: list[str] = Field(default_factory=list)
    searched_sources: list[str] = Field(default_factory=list)
    searched_cities: list[str] = Field(default_factory=list)
    failed_cities: list[str] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    remaining_retries: dict[str, int] = Field(default_factory=dict)
    web_failure_records: dict[str, str] = Field(default_factory=dict)
    rejected_cases: list[RejectedMarketCase] = Field(default_factory=list)
    quality_assessments: list[MarketCaseQuality] = Field(default_factory=list)
    all_listings: list[MarketListing] = Field(default_factory=list)
    candidates: list[MarketListing] = Field(default_factory=list)
    preview_details: list[MarketListingDetail] = Field(default_factory=list)
    preview_screenshots: dict[str, tuple[bytes, bytes]] = Field(
        default_factory=dict,
        exclude=True,
    )
    year_tolerance: int = Field(default=1, ge=0)
    mileage_tolerance_km: int = Field(default=50_000, ge=0)
    keyword_refinement_count: int = Field(default=0, ge=0)
    search_round: int = Field(default=0, ge=0)
    needs_quality_evaluation: bool = False
    status: AgentStatus = "running"
    step_count: int = Field(default=0, ge=0)
    next_batch_index: int = Field(default=0, ge=0)
    trace: list[MarketAgentTraceEntry] = Field(default_factory=list)
    stop_reason: str = ""
    graph_thread_id: str = ""


class MarketGraphState(TypedDict, total=False):
    """LangGraph 节点之间传递的最小共享状态。"""

    agent_state: dict
    decision: dict
    policy_note: str


class MarketEvaluationBatch(BaseModel):
    listings: list[MarketListing]
    details: list[MarketListingDetail] = Field(default_factory=list)
    screenshots: dict[str, tuple[bytes, bytes]] = Field(
        default_factory=dict,
        exclude=True,
    )
    failures: dict[str, str] = Field(default_factory=dict)
    assessments: list[MarketCaseQuality]


class MarketAgentPlanner(Protocol):
    def plan(
        self,
        state: MarketAgentState,
        allowed_tools: list[AgentToolName],
    ) -> MarketAgentDecision: ...


class MarketSearchBackend(Protocol):
    def search(
        self,
        city_paths: list[str],
        series_path: str,
    ) -> tuple[list[MarketListing], list[str]]: ...


class MarketCaseEvaluator(Protocol):
    def evaluate(
        self,
        listings: list[MarketListing],
        state: MarketAgentState,
        config: MarketAgentConfig,
    ) -> MarketEvaluationBatch: ...


class GuaziMarketSearchBackend:
    def search(
        self,
        city_paths: list[str],
        series_path: str,
    ) -> tuple[list[MarketListing], list[str]]:
        return fetch_guazi_listings_from_cities(city_paths, series_path)


class ListingOnlyMarketCaseEvaluator:
    """离线测试用评价器；生产流程应使用详情页快照评价器。"""

    def evaluate(
        self,
        listings: list[MarketListing],
        state: MarketAgentState,
        config: MarketAgentConfig,
    ) -> MarketEvaluationBatch:
        valid_urls = {str(item.source_url) for item in listings}
        assessments = score_market_cases(
            listings,
            state.market_keyword,
            state.target_year,
            state.target_mileage_km,
            set(state.initial_cities),
            valid_urls,
            state.year_tolerance,
            state.mileage_tolerance_km,
            config.minimum_quality_score,
            config.minimum_similarity_score,
        )
        return MarketEvaluationBatch(
            listings=listings,
            assessments=assessments,
        )


class SnapshotMarketCaseEvaluator:
    """同一次详情页读取中保存价格、字段和截图后再评分。"""

    def evaluate(
        self,
        listings: list[MarketListing],
        state: MarketAgentState,
        config: MarketAgentConfig,
    ) -> MarketEvaluationBatch:
        snapshots, details, screenshots, failures = (
            capture_market_listing_snapshots_batch(listings)
        )
        valid_urls = set(screenshots)
        assessments = score_market_cases(
            snapshots,
            state.market_keyword,
            state.target_year,
            state.target_mileage_km,
            set(state.initial_cities),
            valid_urls,
            state.year_tolerance,
            state.mileage_tolerance_km,
            config.minimum_quality_score,
            config.minimum_similarity_score,
        )
        return MarketEvaluationBatch(
            listings=snapshots,
            details=details,
            screenshots=screenshots,
            failures=failures,
            assessments=assessments,
        )


class RuleBasedMarketAgentPlanner:
    _priority: tuple[AgentToolName, ...] = (
        "evaluate_case_quality",
        "search_market_cases",
        "retry_failed_search",
        "expand_search_city",
        "adjust_year_range",
        "adjust_mileage_range",
        "refine_search_keyword",
        "switch_data_source",
        "finalize_candidate_pool",
        "stop_safely",
    )

    def plan(
        self,
        state: MarketAgentState,
        allowed_tools: list[AgentToolName],
    ) -> MarketAgentDecision:
        for tool in self._priority:
            if tool in allowed_tools:
                return MarketAgentDecision(
                    tool=tool,
                    reason="按案例质量、失败记录和剩余搜索预算选择下一步。",
                )
        raise RuntimeError("Agent 当前没有可执行工具")


class OllamaMarketAgentPlanner:
    def __init__(
        self,
        provider: OllamaProvider | None = None,
        fallback: MarketAgentPlanner | None = None,
    ) -> None:
        self.provider = provider or OllamaProvider()
        self.fallback = fallback or RuleBasedMarketAgentPlanner()

    def plan(
        self,
        state: MarketAgentState,
        allowed_tools: list[AgentToolName],
    ) -> MarketAgentDecision:
        prompt = f"""
你是本流程唯一的车辆市场案例搜索 Agent。你不能直接访问网络、不能估值，
只能从 allowed_tools 选择一个工具。达到 3 个合格案例后必须结束搜索，
交给确定性 Top 3 策略自动采用。
关键词：{state.market_keyword}；年份：{state.target_year}±{state.year_tolerance}；
里程：{state.target_mileage_km}±{state.mileage_tolerance_km}；
轮次：{state.search_round}；已搜索城市：{state.searched_cities}；
网页失败：{state.web_failure_records}；拒绝原因：
{[item.model_dump(mode='json') for item in state.rejected_cases]}
合格案例：{len(state.candidates)}；allowed_tools：{allowed_tools}
请选择下一步并用一句中文说明原因。
""".strip()
        try:
            decision = self.provider.generate(prompt, MarketAgentDecision)
        except Exception:
            return self.fallback.plan(state, allowed_tools)
        if decision.tool not in allowed_tools:
            return self.fallback.plan(state, allowed_tools)
        return decision


class ControlledMarketAgent:
    """用 LangGraph 编排白名单工具、运行预算、暂停与恢复。"""

    def __init__(
        self,
        planner: MarketAgentPlanner | None = None,
        search_backend: MarketSearchBackend | None = None,
        search_backends: dict[str, MarketSearchBackend] | None = None,
        case_evaluator: MarketCaseEvaluator | None = None,
        config: MarketAgentConfig | None = None,
        log_dir: Path | None = None,
        checkpoint_path: Path | None = None,
    ) -> None:
        self.planner = planner or OllamaMarketAgentPlanner()
        self.config = config or MarketAgentConfig()
        default_backend = search_backend or GuaziMarketSearchBackend()
        self.search_backends = search_backends or {"guazi": default_backend}
        self.case_evaluator = case_evaluator or ListingOnlyMarketCaseEvaluator()
        self.log_dir = log_dir
        self.run_id = create_run_id()
        self.last_log_path: Path | None = None
        self._checkpoint_connection: sqlite3.Connection | None = None
        self._tools: dict[AgentToolName, Callable[[MarketAgentState], str]] = {
            "search_market_cases": self._search_market_cases,
            "evaluate_case_quality": self._evaluate_case_quality,
            "expand_search_city": self._expand_search_city,
            "adjust_year_range": self._adjust_year_range,
            "adjust_mileage_range": self._adjust_mileage_range,
            "refine_search_keyword": self._refine_search_keyword,
            "retry_failed_search": self._retry_failed_search,
            "switch_data_source": self._switch_data_source,
            "finalize_candidate_pool": self._finalize_candidate_pool,
            "stop_safely": self._stop_safely,
        }
        if checkpoint_path is None:
            self.checkpointer = InMemorySaver()
        else:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self._checkpoint_connection = sqlite3.connect(
                checkpoint_path,
                check_same_thread=False,
            )
            sqlite_saver = SqliteSaver(self._checkpoint_connection)
            sqlite_saver.setup()
            self.checkpointer = sqlite_saver
        self.graph = self._build_graph()

    @property
    def tool_names(self) -> tuple[AgentToolName, ...]:
        return tuple(self._tools)

    @property
    def graph_mermaid(self) -> str:
        """返回可直接展示在文档或面试中的真实执行图。"""

        return self.graph.get_graph().draw_mermaid()

    def close(self) -> None:
        if self._checkpoint_connection is not None:
            self._checkpoint_connection.close()
            self._checkpoint_connection = None

    def _build_graph(self):
        builder = StateGraph(MarketGraphState)
        builder.add_node("plan_next_action", self._graph_plan_next_action)
        for tool_name in self._tools:
            builder.add_node(
                tool_name,
                self._make_graph_tool_node(tool_name),
            )
        builder.add_node("human_input", self._graph_human_input)
        builder.add_edge(START, "plan_next_action")
        builder.add_conditional_edges(
            "plan_next_action",
            self._route_planned_action,
            {**{name: name for name in self._tools}, "end": END},
        )
        for tool_name in self._tools:
            builder.add_conditional_edges(
                tool_name,
                self._route_after_tool,
                {
                    "continue": "plan_next_action",
                    "human_input": "human_input",
                    "end": END,
                },
            )
        builder.add_edge("human_input", "plan_next_action")
        return builder.compile(
            checkpointer=self.checkpointer,
            name="vehicle_market_search_agent",
        )

    def _graph_config(self, thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.config.max_steps * 3 + 10,
        }

    @staticmethod
    def _coerce_agent_state(value) -> MarketAgentState:
        if isinstance(value, MarketAgentState):
            return value
        return MarketAgentState.model_validate(value)

    @staticmethod
    def _serialize_agent_state(state: MarketAgentState) -> dict:
        """生成 checkpoint 可序列化状态，同时保留二进制截图。"""

        payload = state.model_dump(mode="json")
        payload["preview_screenshots"] = state.preview_screenshots
        return payload

    @staticmethod
    def _coerce_decision(value) -> MarketAgentDecision:
        if isinstance(value, MarketAgentDecision):
            return value
        return MarketAgentDecision.model_validate(value)

    def _graph_plan_next_action(
        self,
        graph_state: MarketGraphState,
    ) -> MarketGraphState:
        state = self._coerce_agent_state(
            graph_state["agent_state"]
        ).model_copy(deep=True)
        if state.step_count >= self.config.max_steps:
            state.status = "failed"
            state.stop_reason = "达到最大步骤数，已安全停止"
            return {"agent_state": self._serialize_agent_state(state)}

        allowed = self._allowed_tools(state)
        decision = self.planner.plan(state, allowed)
        policy_note = ""
        if decision.tool not in allowed:
            safe = RuleBasedMarketAgentPlanner().plan(state, allowed)
            policy_note = (
                f"策略层拒绝 {decision.tool}，改为 {safe.tool}"
            )
            decision = safe
        return {
            "agent_state": self._serialize_agent_state(state),
            "decision": decision.model_dump(mode="json"),
            "policy_note": policy_note,
        }

    def _route_planned_action(
        self,
        graph_state: MarketGraphState,
    ) -> AgentToolName | Literal["end"]:
        state = self._coerce_agent_state(graph_state["agent_state"])
        if state.status != "running" or "decision" not in graph_state:
            return "end"
        return self._coerce_decision(graph_state["decision"]).tool

    def _make_graph_tool_node(
        self,
        tool_name: AgentToolName,
    ) -> Callable[[MarketGraphState], MarketGraphState]:
        def execute_tool(
            graph_state: MarketGraphState,
        ) -> MarketGraphState:
            state = self._coerce_agent_state(
                graph_state["agent_state"]
            ).model_copy(deep=True)
            decision = self._coerce_decision(graph_state["decision"])
            if decision.tool != tool_name:
                raise RuntimeError(
                    f"LangGraph 路由错误：{decision.tool} -> {tool_name}"
                )
            self._execute(
                state,
                decision,
                graph_state.get("policy_note", ""),
            )
            return {"agent_state": self._serialize_agent_state(state)}

        return execute_tool

    def _route_after_tool(
        self,
        graph_state: MarketGraphState,
    ) -> Literal["continue", "human_input", "end"]:
        status = self._coerce_agent_state(
            graph_state["agent_state"]
        ).status
        if status == "running":
            return "continue"
        if status == "awaiting_human_input":
            return "human_input"
        return "end"

    def _graph_human_input(
        self,
        graph_state: MarketGraphState,
    ) -> MarketGraphState:
        state = self._coerce_agent_state(
            graph_state["agent_state"]
        ).model_copy(deep=True)
        response = interrupt(
            {
                "reason": state.stop_reason,
                "qualified_case_count": len(state.candidates),
                "required_case_count": self.config.target_count,
                "minimum_similarity_score": (
                    self.config.minimum_similarity_score
                ),
            }
        )
        additional_listings = [
            MarketListing.model_validate(item)
            for item in response.get("additional_listings", [])
        ]
        by_url = {
            str(item.source_url): item
            for item in [*state.all_listings, *additional_listings]
        }
        state.all_listings = list(by_url.values())
        state.status = "running"
        state.stop_reason = ""
        state.needs_quality_evaluation = True
        return {"agent_state": self._serialize_agent_state(state)}

    def initialize_state(
        self,
        market_keyword: str,
        series_path: str,
        target_year: int,
        target_mileage_km: int,
    ) -> MarketAgentState:
        initial = self.config.city_batches[0] if self.config.city_batches else []
        return MarketAgentState(
            market_keyword=market_keyword,
            series_path=series_path,
            target_year=target_year,
            target_mileage_km=target_mileage_km,
            initial_cities=initial,
            allowed_sources=self.config.allowed_sources,
            used_keywords=[market_keyword],
            year_tolerance=self.config.initial_year_tolerance,
            mileage_tolerance_km=self.config.initial_mileage_tolerance_km,
        )

    def run_until_pause(self, state: MarketAgentState) -> MarketAgentState:
        if not state.initial_cities and self.config.city_batches:
            state.initial_cities = list(self.config.city_batches[0])
        if not state.used_keywords:
            state.used_keywords = [state.market_keyword]
        if not state.allowed_sources:
            state.allowed_sources = list(self.config.allowed_sources)
        thread_id = state.graph_thread_id or self.run_id
        state.graph_thread_id = thread_id
        result = self.graph.invoke(
            {"agent_state": self._serialize_agent_state(state)},
            config=self._graph_config(thread_id),
        )
        final_state = self._coerce_agent_state(result["agent_state"])
        self._persist_log(final_state)
        return final_state

    def resume_with_human_cases(
        self,
        thread_id: str,
        additional_listings: list[MarketListing],
    ) -> MarketAgentState:
        """从 LangGraph interrupt checkpoint 注入案例并继续执行。"""

        result = self.graph.invoke(
            Command(
                resume={
                    "additional_listings": [
                        item.model_dump(mode="json")
                        for item in additional_listings
                    ]
                }
            ),
            config=self._graph_config(thread_id),
        )
        final_state = self._coerce_agent_state(result["agent_state"])
        self._persist_log(final_state)
        return final_state

    def get_checkpoint_state(self, thread_id: str) -> MarketAgentState:
        """读取指定运行线程最近一次持久化的 Agent 状态。"""

        snapshot = self.graph.get_state(self._graph_config(thread_id))
        if "agent_state" not in snapshot.values:
            raise ValueError(f"未找到 LangGraph checkpoint：{thread_id}")
        return self._coerce_agent_state(snapshot.values["agent_state"])

    def approve_candidates(self, state: MarketAgentState) -> MarketAgentState:
        return self.complete_candidate_selection(state, "human")

    def complete_candidate_selection(
        self,
        state: MarketAgentState,
        approval_mode: Literal["human", "automatic_policy"],
    ) -> MarketAgentState:
        """由人工或确定性高质量策略完成案例采用。"""

        if state.status != "candidates_ready":
            raise ValueError("Agent 当前没有可完成选择的候选案例")
        if len(state.candidates) < self.config.target_count:
            raise ValueError("合格案例不足，不能完成人工确认")
        state.status = "completed"
        state.stop_reason = (
            "确定性高质量策略已自动采用至少三个市场案例"
            if approval_mode == "automatic_policy"
            else "用户已确认至少三个市场案例"
        )
        self._persist_log(state)
        return state

    def return_incomplete_cases(
        self,
        state: MarketAgentState,
        failed_urls: list[str],
    ) -> MarketAgentState:
        """详情复核不足三例时退回搜索，而不是继续估值。"""

        failed_set = set(failed_urls)
        state.candidates = [
            item for item in state.candidates
            if str(item.source_url) not in failed_set
        ]
        state.status = "running"
        state.stop_reason = "人工复核后案例不足，已返回搜索 Agent"
        return state

    def _persist_log(self, state: MarketAgentState) -> None:
        if self.log_dir is None:
            return
        try:
            self.last_log_path = save_agent_trace(
                "market_search_agent",
                state.status,
                state.stop_reason,
                state.trace,
                self.run_id,
                self.log_dir,
            )
        except OSError:
            self.last_log_path = None

    def _allowed_tools(self, state: MarketAgentState) -> list[AgentToolName]:
        if state.needs_quality_evaluation:
            return ["evaluate_case_quality"]
        if len(state.candidates) >= self.config.target_count:
            return ["finalize_candidate_pool"]
        if state.search_round >= self.config.max_search_rounds:
            return ["stop_safely"]
        if state.next_batch_index == 0:
            return ["search_market_cases"]

        allowed: list[AgentToolName] = []
        if any(
            state.retry_counts.get(city, 0) < self.config.max_retries_per_city
            for city in state.failed_cities
        ):
            allowed.append("retry_failed_search")
        if state.next_batch_index < len(self.config.city_batches):
            allowed.append("expand_search_city")
        if state.year_tolerance < self.config.maximum_year_tolerance:
            allowed.append("adjust_year_range")
        if state.mileage_tolerance_km < self.config.maximum_mileage_tolerance_km:
            allowed.append("adjust_mileage_range")
        if state.keyword_refinement_count < self.config.max_keyword_refinements:
            allowed.append("refine_search_keyword")
        if state.current_source_index + 1 < len(state.allowed_sources):
            allowed.append("switch_data_source")
        return allowed or ["stop_safely"]

    def _execute(
        self,
        state: MarketAgentState,
        decision: MarketAgentDecision,
        policy_note: str,
    ) -> None:
        started = perf_counter()
        state.step_count += 1
        try:
            outcome = self._tools[decision.tool](state)
        except Exception as error:
            outcome = f"工具执行失败：{error}"
            state.web_failure_records[f"tool:{decision.tool}"] = str(error)
            if decision.tool == "stop_safely":
                state.status = "failed"
                state.stop_reason = outcome
        state.trace.append(
            MarketAgentTraceEntry(
                step=state.step_count,
                timestamp=datetime.now().astimezone(),
                tool=decision.tool,
                planner_reason=decision.reason,
                policy_note=policy_note,
                outcome=outcome,
                candidate_count=len(state.candidates),
                duration_ms=int((perf_counter() - started) * 1000),
            )
        )

    def _current_source(self, state: MarketAgentState) -> str:
        return state.allowed_sources[state.current_source_index]

    def _current_backend(self, state: MarketAgentState) -> MarketSearchBackend:
        source = self._current_source(state)
        if source not in self.search_backends:
            raise ValueError(f"数据源 {source} 尚未配置搜索后端")
        return self.search_backends[source]

    def _search_market_cases(self, state: MarketAgentState) -> str:
        return self._search_next_batch(state)

    def _expand_search_city(self, state: MarketAgentState) -> str:
        return self._search_next_batch(state)

    def _search_next_batch(self, state: MarketAgentState) -> str:
        if state.next_batch_index >= len(self.config.city_batches):
            raise ValueError("没有剩余城市批次")
        cities = self.config.city_batches[state.next_batch_index]
        state.next_batch_index += 1
        return self._search_cities(state, cities)

    def _retry_failed_search(self, state: MarketAgentState) -> str:
        cities = [
            city for city in state.failed_cities
            if state.retry_counts.get(city, 0) < self.config.max_retries_per_city
        ]
        if not cities:
            raise ValueError("没有可重试城市")
        for city in cities:
            state.retry_counts[city] = state.retry_counts.get(city, 0) + 1
            state.remaining_retries[city] = (
                self.config.max_retries_per_city - state.retry_counts[city]
            )
        return self._search_cities(state, cities)

    def _search_cities(self, state: MarketAgentState, cities: list[str]) -> str:
        source = self._current_source(state)
        listings, failures = self._current_backend(state).search(
            cities,
            state.series_path,
        )
        state.search_round += 1
        state.searched_sources = list(dict.fromkeys([*state.searched_sources, source]))
        state.searched_cities = list(dict.fromkeys([*state.searched_cities, *cities]))
        for city in cities:
            state.remaining_retries.setdefault(city, self.config.max_retries_per_city)
        for city in failures:
            if city not in state.failed_cities:
                state.failed_cities.append(city)
            state.web_failure_records[f"{source}:{city}"] = "列表页读取失败"
        successful = set(cities) - set(failures)
        state.failed_cities = [city for city in state.failed_cities if city not in successful]
        for city in successful:
            state.web_failure_records.pop(f"{source}:{city}", None)
        by_url = {str(item.source_url): item for item in [*state.all_listings, *listings]}
        state.all_listings = list(by_url.values())
        state.needs_quality_evaluation = True
        return f"搜索 {source}/{cities}，新增 {len(listings)} 条，失败城市 {failures}"

    def _evaluation_pool(self, state: MarketAgentState) -> list[MarketListing]:
        return sorted(
            state.all_listings,
            key=lambda item: calculate_listing_similarity(
                item,
                state.target_year,
                state.target_mileage_km,
            ),
            reverse=True,
        )[: self.config.candidate_limit]

    def _evaluate_case_quality(self, state: MarketAgentState) -> str:
        batch = self.case_evaluator.evaluate(
            self._evaluation_pool(state),
            state,
            self.config,
        )
        snapshot_by_url = {str(item.source_url): item for item in batch.listings}
        state.all_listings = [
            snapshot_by_url.get(str(item.source_url), item)
            for item in state.all_listings
        ]
        state.preview_details = batch.details
        state.preview_screenshots = batch.screenshots
        state.web_failure_records.update(batch.failures)
        state.quality_assessments = batch.assessments
        quality_by_url = {str(item.source_url): item for item in batch.assessments}
        rejected: list[RejectedMarketCase] = []
        candidates: list[MarketListing] = []
        for listing in batch.listings:
            quality = quality_by_url.get(str(listing.source_url))
            if quality is not None and quality.qualified:
                candidates.append(listing)
            elif quality is not None:
                rejected.append(
                    RejectedMarketCase(
                        source_url=listing.source_url,
                        vehicle_model=listing.vehicle_model,
                        reasons=quality.rejection_reasons,
                    )
                )
        state.rejected_cases = rejected
        state.candidates = sorted(
            candidates,
            key=lambda item: quality_by_url[str(item.source_url)].total_score,
            reverse=True,
        )
        state.needs_quality_evaluation = False
        return (
            f"评价 {len(batch.listings)} 条案例，合格 {len(state.candidates)} 条，"
            f"拒绝 {len(rejected)} 条，网页失败 {len(batch.failures)} 条"
        )

    def _adjust_year_range(self, state: MarketAgentState) -> str:
        state.year_tolerance = min(
            self.config.maximum_year_tolerance,
            state.year_tolerance + 1,
        )
        state.needs_quality_evaluation = True
        return f"年份范围放宽为±{state.year_tolerance}年"

    def _adjust_mileage_range(self, state: MarketAgentState) -> str:
        state.mileage_tolerance_km = min(
            self.config.maximum_mileage_tolerance_km,
            state.mileage_tolerance_km + self.config.mileage_tolerance_step_km,
        )
        state.needs_quality_evaluation = True
        return f"里程范围放宽为±{state.mileage_tolerance_km}公里"

    def _refine_search_keyword(self, state: MarketAgentState) -> str:
        refined = re.sub(r"\b(19|20)\d{2}\b", "", state.market_keyword)
        refined = re.sub(r"\s+", " ", refined).strip()
        if not refined or refined == state.market_keyword:
            refined = " ".join(state.market_keyword.split()[:-1]) or state.market_keyword
        state.market_keyword = refined
        state.keyword_refinement_count += 1
        state.used_keywords = list(dict.fromkeys([*state.used_keywords, refined]))
        state.needs_quality_evaluation = True
        return f"搜索关键词调整为：{refined}"

    def _switch_data_source(self, state: MarketAgentState) -> str:
        state.current_source_index += 1
        state.next_batch_index = 0
        return f"数据源切换为 {self._current_source(state)}"

    def _finalize_candidate_pool(self, state: MarketAgentState) -> str:
        if len(state.candidates) < self.config.target_count:
            raise ValueError("案例不足，不能结束候选案例搜索")
        state.status = "candidates_ready"
        state.stop_reason = "案例数量与门槛达标，交给确定性 Top 3 策略"
        return state.stop_reason

    def _stop_safely(self, state: MarketAgentState) -> str:
        state.status = "awaiting_human_input"
        state.stop_reason = (
            f"达到受控搜索边界：共 {state.search_round} 轮、"
            f"{len(state.searched_cities)} 个城市、"
            f"仅找到 {len(state.candidates)} 个合格案例；"
            "LangGraph 已暂停，请人工补充来源或调整条件后恢复"
        )
        return state.stop_reason
