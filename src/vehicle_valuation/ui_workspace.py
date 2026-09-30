"""Streamlit 工作台的纯展示组件和状态派生逻辑。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

import streamlit as st


@dataclass(frozen=True)
class WorkflowStage:
    key: str
    number: str
    label: str
    anchor: str
    done: bool


def derive_workflow_stages(session: Mapping[str, Any]) -> list[WorkflowStage]:
    """只根据现有业务状态计算展示进度，不改变流程状态。"""

    data_done = bool(session.get("initial_checks_passed", False))
    market_done = bool(session.get("confirmed_market_cases"))
    adjustment_done = bool(session.get("adjustments_approved", False))
    valuation_done = session.get("final_valuation_value") is not None
    output_done = bool(
        session.get("generated_excel_bytes")
        and session.get("generated_report_bytes")
        and session.get("final_outputs_approved", False)
    )
    return [
        WorkflowStage("vehicle", "01", "车辆资料", "stage-vehicle", data_done),
        WorkflowStage("market", "02", "市场案例", "stage-market", market_done),
        WorkflowStage(
            "adjustment", "03", "调整参数", "stage-adjustment", adjustment_done
        ),
        WorkflowStage(
            "valuation", "04", "估值结果", "stage-valuation", valuation_done
        ),
        WorkflowStage("report", "05", "报告输出", "stage-report", output_done),
    ]


def active_stage_index(stages: Sequence[WorkflowStage]) -> int:
    for index, stage in enumerate(stages):
        if not stage.done:
            return index
    return max(0, len(stages) - 1)


def collect_attention_items(session: Mapping[str, Any]) -> list[str]:
    """汇总真正需要人工处理的事项。"""

    items: list[str] = []
    calibration = session.get("license_calibration")
    if calibration is not None and getattr(calibration, "requires_review", False):
        items.extend(getattr(calibration, "review_reasons", []))
    for conflict in session.get("license_precheck_conflicts", []) or []:
        items.append(getattr(conflict, "message", str(conflict)))

    agent_state = session.get("market_agent_state")
    if getattr(agent_state, "status", None) == "awaiting_human_input":
        items.append("市场案例不足，需要补充案例或恢复搜索")

    adjustment_review = session.get("adjustment_review_decision")
    if (
        adjustment_review is not None
        and getattr(adjustment_review, "requires_review", False)
        and not session.get("adjustments_approved", False)
    ):
        items.extend(getattr(adjustment_review, "reasons", []))
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))


def inject_workspace_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --vv-ink: #162033;
            --vv-muted: #667085;
            --vv-line: #e5eaf2;
            --vv-blue: #2457d6;
            --vv-blue-soft: #eef4ff;
            --vv-green: #16845b;
            --vv-green-soft: #eaf8f2;
            --vv-amber: #b86b08;
            --vv-bg: #f5f7fb;
        }
        .stApp { background: var(--vv-bg); color: var(--vv-ink); }
        .block-container {
            max-width: 1440px;
            padding-top: 1.5rem;
            padding-bottom: 5rem;
        }
        [data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--vv-line);
        }
        [data-testid="stSidebar"] .block-container { padding-top: 1.4rem; }
        [data-testid="stFileUploaderDropzone"] {
            background: #ffffff;
            border: 1.5px dashed #b8c4d8;
            border-radius: 16px;
            padding: 1rem;
        }
        [data-testid="stFileUploaderDropzone"]:hover {
            border-color: var(--vv-blue);
            background: var(--vv-blue-soft);
        }
        [data-testid="stExpander"] {
            background: #ffffff;
            border: 1px solid var(--vv-line);
            border-radius: 14px;
            overflow: hidden;
        }
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--vv-line);
            border-radius: 14px;
            padding: .9rem 1rem;
            box-shadow: 0 8px 22px rgba(30, 53, 87, .05);
        }
        .stButton > button, .stDownloadButton > button {
            min-height: 2.75rem;
            border-radius: 10px;
            font-weight: 650;
            border-color: #cfd7e6;
        }
        .stButton > button[kind="primary"],
        .stDownloadButton > button[kind="primary"] {
            background: var(--vv-blue);
            border-color: var(--vv-blue);
        }
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        [data-baseweb="textarea"] > div {
            border-radius: 10px;
            border-color: #d8dfeb;
        }
        .vv-hero {
            position: relative;
            overflow: hidden;
            border-radius: 22px;
            padding: 1.5rem 1.65rem;
            margin-bottom: 1rem;
            color: #ffffff;
            background: linear-gradient(125deg, #17233d 0%, #214796 64%, #2f6bea 100%);
            box-shadow: 0 18px 45px rgba(24, 54, 112, .18);
        }
        .vv-hero::after {
            content: "";
            position: absolute;
            width: 250px;
            height: 250px;
            right: -95px;
            top: -130px;
            border-radius: 50%;
            background: rgba(255,255,255,.10);
        }
        .vv-eyebrow {
            font-size: .76rem;
            font-weight: 750;
            letter-spacing: .12em;
            text-transform: uppercase;
            color: #bbd0ff;
            margin-bottom: .42rem;
        }
        .vv-hero-row {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            gap: 1rem;
        }
        .vv-hero h1 { margin: 0; font-size: 1.72rem; color: white; }
        .vv-hero p { margin: .45rem 0 0; color: #dce6ff; max-width: 760px; }
        .vv-status-badge {
            white-space: nowrap;
            padding: .44rem .75rem;
            border: 1px solid rgba(255,255,255,.28);
            border-radius: 999px;
            background: rgba(255,255,255,.12);
            font-size: .84rem;
            font-weight: 700;
        }
        .vv-progress {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: .55rem;
            margin: 1rem 0 1.5rem;
        }
        .vv-step {
            background: #ffffff;
            border: 1px solid var(--vv-line);
            border-radius: 13px;
            padding: .72rem .78rem;
            color: var(--vv-muted);
            min-width: 0;
        }
        .vv-step.done { border-color: #b9e2d2; background: var(--vv-green-soft); color: #116b4c; }
        .vv-step.active { border-color: #8eafff; background: var(--vv-blue-soft); color: #1749bd; box-shadow: 0 6px 18px rgba(36,87,214,.10); }
        .vv-step-number { font-size: .7rem; font-weight: 800; letter-spacing: .08em; }
        .vv-step-label { display: block; font-size: .9rem; font-weight: 720; margin-top: .18rem; overflow: hidden; text-overflow: ellipsis; }
        .vv-section {
            display: flex;
            align-items: center;
            gap: .8rem;
            margin: 2rem 0 .9rem;
            scroll-margin-top: 1rem;
        }
        .vv-section-number {
            display: grid;
            place-items: center;
            width: 2.35rem;
            height: 2.35rem;
            border-radius: 11px;
            background: var(--vv-blue-soft);
            color: var(--vv-blue);
            font-size: .78rem;
            font-weight: 800;
        }
        .vv-section h2 { margin: 0; font-size: 1.32rem; color: var(--vv-ink); }
        .vv-section p { margin: .14rem 0 0; color: var(--vv-muted); font-size: .88rem; }
        .vv-subsection { margin: 1.35rem 0 .55rem; }
        .vv-subsection h3 { margin: 0; font-size: 1.03rem; color: var(--vv-ink); }
        .vv-subsection p { margin: .18rem 0 0; color: var(--vv-muted); font-size: .84rem; }
        .vv-summary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .65rem;
            margin: .8rem 0 1rem;
        }
        .vv-summary-card, .vv-case-card {
            background: #ffffff;
            border: 1px solid var(--vv-line);
            border-radius: 14px;
            padding: .85rem .95rem;
            box-shadow: 0 7px 20px rgba(28, 46, 77, .045);
        }
        .vv-card-label { color: var(--vv-muted); font-size: .75rem; margin-bottom: .28rem; }
        .vv-card-value { color: var(--vv-ink); font-weight: 760; font-size: .98rem; word-break: break-word; }
        .vv-nav-title { font-weight: 800; font-size: 1rem; color: var(--vv-ink); margin: .25rem 0 .75rem; }
        .vv-nav-link {
            display: flex;
            align-items: center;
            gap: .65rem;
            padding: .64rem .72rem;
            margin: .24rem 0;
            border-radius: 10px;
            text-decoration: none !important;
            color: #475467 !important;
            border: 1px solid transparent;
        }
        .vv-nav-link.active { background: var(--vv-blue-soft); color: #1749bd !important; border-color: #cbd9ff; font-weight: 720; }
        .vv-nav-link.done { color: #176e50 !important; }
        .vv-nav-dot { width: .55rem; height: .55rem; border-radius: 50%; background: #c7cfdb; flex: none; }
        .vv-nav-link.done .vv-nav-dot { background: var(--vv-green); }
        .vv-nav-link.active .vv-nav-dot { background: var(--vv-blue); box-shadow: 0 0 0 4px #dce7ff; }
        .vv-side-box { margin-top: 1rem; padding: .8rem; border-radius: 12px; background: #f8fafc; border: 1px solid var(--vv-line); }
        .vv-side-ok { color: #116b4c; font-weight: 700; font-size: .86rem; }
        .vv-side-warning { color: #985406; font-size: .82rem; line-height: 1.45; }
        @media (max-width: 900px) {
            .vv-progress, .vv-summary-grid { grid-template-columns: 1fr 1fr; }
            .vv-hero-row { align-items: flex-start; flex-direction: column; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _selected_vehicle(session: Mapping[str, Any]) -> Any | None:
    request = session.get("valuation_request")
    if request is not None:
        return getattr(request, "subject_vehicle", None)
    return session.get("ui_selected_vehicle")


def render_workspace_shell(session: Mapping[str, Any]) -> None:
    stages = derive_workflow_stages(session)
    active_index = active_stage_index(stages)
    active = stages[active_index]
    vehicle = _selected_vehicle(session)
    if vehicle is None:
        title = "新建车辆评估"
        description = "上传资料后，系统将自动完成识别、核对、案例搜索与估值。"
    else:
        title = escape(
            f"{getattr(vehicle, 'plate_number', '')} · "
            f"{getattr(vehicle, 'vehicle_name', '车辆评估')}"
        )
        asset_id = escape(str(getattr(vehicle, "asset_id", "")))
        description = f"资产编号 {asset_id} · 自动流程只在异常时请求人工处理"

    st.markdown(
        f"""
        <div class="vv-hero">
          <div class="vv-eyebrow">Vehicle valuation workspace</div>
          <div class="vv-hero-row">
            <div><h1>{title}</h1><p>{description}</p></div>
            <span class="vv-status-badge">当前 · {escape(active.label)}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    progress_items = []
    for index, stage in enumerate(stages):
        css_class = "done" if stage.done else ("active" if index == active_index else "")
        marker = "✓" if stage.done else stage.number
        progress_items.append(
            f'<div class="vv-step {css_class}">'
            f'<span class="vv-step-number">{marker}</span>'
            f'<span class="vv-step-label">{escape(stage.label)}</span></div>'
        )
    st.markdown(
        '<div class="vv-progress">' + "".join(progress_items) + "</div>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown('<div class="vv-nav-title">评估工作台</div>', unsafe_allow_html=True)
        for index, stage in enumerate(stages):
            css_class = "done" if stage.done else ("active" if index == active_index else "")
            st.markdown(
                f'<a class="vv-nav-link {css_class}" href="#{stage.anchor}">'
                f'<span class="vv-nav-dot"></span>'
                f'<span>{stage.number}&nbsp;&nbsp;{escape(stage.label)}</span></a>',
                unsafe_allow_html=True,
            )

        attention_items = collect_attention_items(session)
        if attention_items:
            items = "".join(
                f"<div>• {escape(item)}</div>" for item in attention_items[:4]
            )
            st.markdown(
                '<div class="vv-side-box"><div class="vv-side-warning">'
                f"<strong>需要处理 · {len(attention_items)}</strong>{items}</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="vv-side-box"><div class="vv-side-ok">'
                "✓ 当前没有待处理异常</div></div>",
                unsafe_allow_html=True,
            )

        agent_state = session.get("market_agent_state")
        trace_count = len(getattr(agent_state, "trace", []) or [])
        correction_count = len(
            getattr(session.get("license_calibration"), "corrections", []) or []
        )
        st.caption(
            f"自动校准 {correction_count} 项 · Agent 轨迹 {trace_count} 步"
        )


def render_section_header(
    anchor: str,
    number: str,
    title: str,
    description: str,
) -> None:
    st.markdown(
        f"""
        <div class="vv-section" id="{escape(anchor)}">
          <div class="vv-section-number">{escape(number)}</div>
          <div><h2>{escape(title)}</h2><p>{escape(description)}</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_subsection(title: str, description: str) -> None:
    st.markdown(
        f'<div class="vv-subsection"><h3>{escape(title)}</h3>'
        f'<p>{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def render_vehicle_summary(vehicle: Any, valuation_date: Any) -> None:
    values = (
        ("资产编号", getattr(vehicle, "asset_id", "-")),
        ("车辆牌号", getattr(vehicle, "plate_number", "-")),
        ("当前里程", f"{getattr(vehicle, 'mileage_km', 0):,} km"),
        ("评估基准日", valuation_date or "待选择"),
    )
    cards = "".join(
        '<div class="vv-summary-card">'
        f'<div class="vv-card-label">{escape(str(label))}</div>'
        f'<div class="vv-card-value">{escape(str(value))}</div></div>'
        for label, value in values
    )
    st.markdown(
        f'<div class="vv-summary-grid">{cards}</div>', unsafe_allow_html=True
    )


def render_market_case_cards(
    listings: Sequence[Any],
    quality_by_url: Mapping[str, Any] | None = None,
) -> None:
    quality_by_url = quality_by_url or {}
    columns = st.columns(max(1, len(listings)))
    for index, (column, listing) in enumerate(zip(columns, listings, strict=False), 1):
        quality = quality_by_url.get(str(listing.source_url))
        score = getattr(quality, "similarity_score", None)
        score_text = f"{score} 分" if score is not None else "已通过门槛"
        with column:
            st.markdown(
                '<div class="vv-case-card">'
                f'<div class="vv-card-label">采用案例 {index} · {escape(score_text)}</div>'
                f'<div class="vv-card-value">{escape(str(listing.vehicle_model))}</div>'
                f'<div class="vv-card-label" style="margin-top:.65rem">'
                f'{listing.registration_year} 年 · {listing.mileage_km:,} km · '
                f'{escape(str(listing.city))}</div>'
                f'<div class="vv-card-value">¥ {float(listing.price_cny):,.0f}</div>'
                "</div>",
                unsafe_allow_html=True,
            )


def render_valuation_dashboard(
    final_value: Any,
    listings: Sequence[Any],
    adjusted_prices: Sequence[Any],
) -> None:
    render_section_header(
        "stage-valuation",
        "04",
        "估值结果",
        "对比挂牌价与修正后价格，最终金额由 Python Decimal 公式计算。",
    )
    metric_columns = st.columns(3)
    with metric_columns[0]:
        st.metric("车辆评估建议值", f"¥ {float(final_value):,.0f}")
    with metric_columns[1]:
        average_listing = sum(float(item.price_cny) for item in listings) / len(listings)
        st.metric("案例平均挂牌价", f"¥ {average_listing:,.0f}")
    with metric_columns[2]:
        adjustment_delta = float(final_value) - average_listing
        st.metric("修正影响", f"¥ {adjustment_delta:+,.0f}")

    chart_rows = [
        {
            "案例": f"案例{index}",
            "挂牌价": float(listing.price_cny),
            "修正后价格": float(adjusted_price),
        }
        for index, (listing, adjusted_price) in enumerate(
            zip(listings, adjusted_prices, strict=False), start=1
        )
    ]
    st.bar_chart(
        chart_rows,
        x="案例",
        y=["挂牌价", "修正后价格"],
        color=["#93A4C3", "#2457D6"],
        height=280,
    )
