import streamlit as st
import hashlib
from datetime import date
from vehicle_valuation.checks import (
    run_license_subject_checks,
    run_structured_checks,
)
from vehicle_valuation.model import (
    DrivingLicenseData,
    MarketListing,
    ValuationRequest,
    VehicleInspection,
)

from vehicle_valuation.license_parser import (
    extract_license_fields,
)
from vehicle_valuation.excel_loader import (
    load_subject_vehicles_from_excel,
)
from vehicle_valuation.license_ocr import (
    recognize_license_lines,
)
from vehicle_valuation.license_calibration import (
    calibrate_license_fields,
)
from pathlib import Path

from vehicle_valuation.model_mapping_retrieval import (
    extract_legal_model,
    load_model_mapping_knowledge_base,
    retrieve_model_mapping_evidence,
)

from vehicle_valuation.market_scraper import (
    calculate_listing_similarity,
)
from vehicle_valuation.market_agent import (
    ControlledMarketAgent,
    MarketAgentConfig,
    SnapshotMarketCaseEvaluator,
)

from vehicle_valuation.market_route_retrieval import (
    load_market_search_routes,
    retrieve_market_search_route,
)

from vehicle_valuation.adjustment_ai import (
    generate_comparison_suggestion,
)
from vehicle_valuation.llm_provider import OllamaProvider
from vehicle_valuation.model import MarketListingDetail

from vehicle_valuation.adjustment_rules import (
    calculate_annual_mileage_bucket_index,
    calculate_registration_year_index,
    load_adjustment_rule_set,
)

from vehicle_valuation.calculation import (
    calculate_price_from_index_values,
    calculate_rounded_average_value,
)

from vehicle_valuation.excel_exporter import (
    build_case_sheets_excel,
)

from vehicle_valuation.rag_service import (
    VehicleValuationRAG,
)
from vehicle_valuation.report_evidence import (
    retrieve_full_report_evidence,
)
from vehicle_valuation.report_section_generation import (
    generate_report_sections,
)
from vehicle_valuation.report_assembly import (
    build_report_draft,
)
from vehicle_valuation.report_docx_exporter import (
    build_report_docx_from_template,
)
from vehicle_valuation.output_validation import (
    validate_output_consistency,
)
from vehicle_valuation.case_selection import (
    evaluate_automatic_case_selection,
)
from vehicle_valuation.adjustment_review import (
    evaluate_adjustment_review,
)


MODEL_MAPPING_PATH = (
    Path(__file__).parent
    / "data"
    / "public"
    / "vehicle_model_mappings.json"
)


MARKET_ROUTE_PATH = (
    Path(__file__).parent
    / "data"
    / "public"
    / "market_search_routes.json"
)

OCR_PIPELINE_VERSION = "3"
MARKET_SELECTION_POLICY_VERSION = "3-langgraph"

st.set_page_config(
    page_title="车辆评估助手",
    page_icon="🚗",
)

st.title("车辆评估助手")


DOWNSTREAM_STATE_KEYS = [
    "market_agent_state",
    "market_candidates",
    "confirmed_market_cases",
    "market_case_details",
    "market_case_screenshots",
    "ai_comparison_suggestions",
    "adjustments_approved",
    "adjusted_market_prices",
    "final_valuation_value",
    "generated_excel_bytes",
    "generated_report_bytes",
    "report_valid_chunk_ids",
    "report_cited_chunk_ids",
    "final_outputs_approved",
    "market_cases_auto_selected",
    "automatic_case_selection",
    "adjustment_review_decision",
    "market_agent_instance",
]

LICENSE_WIDGET_KEYS = {
    "plate_number": "license_plate_number",
    "vehicle_type": "license_vehicle_type",
    "owner_name": "license_owner_name",
    "address": "license_address",
    "use_character": "license_use_character",
    "vehicle_model": "license_vehicle_model",
    "vin": "license_vin",
    "engine_number": "license_engine_number",
}


def clear_downstream_state() -> None:
    """输入或案例变化后清除旧计算和旧下载文件。"""

    for state_key in DOWNSTREAM_STATE_KEYS:
        value = st.session_state.pop(state_key, None)
        if state_key == "market_agent_instance" and value is not None:
            value.close()


def apply_automatic_market_selection(
    market_agent: ControlledMarketAgent,
    agent_state,
) -> bool:
    """达到硬门槛时自动采用 Top 3，并保存同次抓取证据。"""

    automatic_selection = evaluate_automatic_case_selection(
        listings=agent_state.candidates,
        assessments=agent_state.quality_assessments,
        details=agent_state.preview_details,
        screenshots=agent_state.preview_screenshots,
        minimum_similarity_score=60,
    )
    st.session_state["automatic_case_selection"] = automatic_selection
    if not automatic_selection.approved:
        return False

    selected_url_set = set(automatic_selection.selected_urls)
    automatic_cases = [
        item
        for item in agent_state.candidates
        if str(item.source_url) in selected_url_set
    ]
    detail_by_url = {
        str(item.source_url): item
        for item in agent_state.preview_details
    }
    market_agent.complete_candidate_selection(
        agent_state,
        "automatic_policy",
    )
    st.session_state["confirmed_market_cases"] = automatic_cases
    st.session_state["market_case_details"] = [
        detail_by_url[str(item.source_url)]
        for item in automatic_cases
    ]
    st.session_state["market_case_screenshots"] = {
        url: images
        for url, images in agent_state.preview_screenshots.items()
        if url in selected_url_set
    }
    st.session_state["market_cases_auto_selected"] = True
    return True


def populate_license_widget_state(
    fields: dict[str, str | None],
) -> None:
    """把校准后的行驶证字段填入可编辑控件。"""

    for field_name, widget_key in LICENSE_WIDGET_KEYS.items():
        if fields.get(field_name) is not None:
            st.session_state[widget_key] = fields[field_name]
    for field_name, widget_key in (
        ("registration_date", "license_registration_date"),
        ("issue_date", "license_issue_date"),
    ):
        value = fields.get(field_name)
        if value:
            st.session_state[widget_key] = date.fromisoformat(value)


def build_driving_license_from_widgets() -> DrivingLicenseData:
    """从当前编辑控件构造经过 Pydantic 校验的行驶证对象。"""

    return DrivingLicenseData(
        plate_number=st.session_state.get("license_plate_number", ""),
        vehicle_type=st.session_state.get("license_vehicle_type", ""),
        owner_name=st.session_state.get("license_owner_name", ""),
        address=st.session_state.get("license_address", ""),
        use_character=st.session_state.get("license_use_character", ""),
        vehicle_model=st.session_state.get("license_vehicle_model", ""),
        vin=st.session_state.get("license_vin", ""),
        engine_number=st.session_state.get("license_engine_number", ""),
        registration_date=st.session_state.get("license_registration_date"),
        issue_date=st.session_state.get("license_issue_date"),
    )

uploaded_file = st.file_uploader(
    "上传车辆评估明细表",
    type=["xlsx"],
)

if uploaded_file is not None:
    try:
        vehicles = load_subject_vehicles_from_excel(
            uploaded_file
        )
    except Exception as error:
        st.error(f"Excel读取失败：{error}")
        st.stop()

    st.success(f"成功读取 {len(vehicles)} 辆车")

    selected_vehicle = st.selectbox(
        "选择待评估车辆",
        options=vehicles,
        format_func=lambda vehicle: (
            f"{vehicle.asset_id} - "
            f"{vehicle.plate_number} - "
            f"{vehicle.vehicle_name}"
        ),
    )

    valuation_date = st.date_input(
        "评估基准日",
        value=None,
        format="YYYY/MM/DD",
    )

    if valuation_date is None:
        st.info("请选择评估基准日")
        st.stop()

    st.subheader("行驶证")

    driving_license_image = st.file_uploader(
        "上传行驶证照片",
        type=["jpg", "jpeg", "png"],
        key="driving_license",
    )

    if driving_license_image is not None:
        st.image(
            driving_license_image,
            caption="行驶证预览",
            width=500,
        )
        image_bytes = driving_license_image.getvalue()
        processing_key = (
            hashlib.sha256(image_bytes).hexdigest()
            + ":"
            + selected_vehicle.asset_id
            + ":"
            + OCR_PIPELINE_VERSION
        )
        if st.session_state.get("license_processing_key") != processing_key:
            for state_key in (
                "confirmed_license",
                "valuation_request",
                "initial_checks_passed",
                "license_calibration",
                "license_precheck_conflicts",
                "license_auto_accepted",
                "show_license_editor",
            ):
                st.session_state.pop(state_key, None)
            clear_downstream_state()
            try:
                with st.spinner("已检测到行驶证，正在自动识别和校准……"):
                    ocr_records = recognize_license_lines(image_bytes)
                    raw_lines = [item.text for item in ocr_records]
                    extracted_fields = extract_license_fields(raw_lines)
                    calibration = calibrate_license_fields(
                        extracted_fields=extracted_fields,
                        ocr_lines=ocr_records,
                        subject_vehicle=selected_vehicle,
                        mappings=load_model_mapping_knowledge_base(
                            MODEL_MAPPING_PATH
                        ),
                    )
                    populate_license_widget_state(calibration.fields)
                    st.session_state["license_ocr_records"] = ocr_records
                    st.session_state["license_ocr_lines"] = raw_lines
                    st.session_state["license_calibration"] = calibration
                    st.session_state["license_processing_key"] = processing_key

                    if not calibration.requires_review:
                        candidate_license = build_driving_license_from_widgets()
                        precheck_conflicts = run_license_subject_checks(
                            selected_vehicle,
                            candidate_license,
                        )
                        st.session_state[
                            "license_precheck_conflicts"
                        ] = precheck_conflicts
                        if not precheck_conflicts:
                            st.session_state[
                                "confirmed_license"
                            ] = candidate_license
                            st.session_state[
                                "license_auto_accepted"
                            ] = True
            except Exception as error:
                st.session_state["license_processing_key"] = processing_key
                st.session_state["license_auto_accepted"] = False
                st.error(f"行驶证自动识别失败：{error}")

        calibration = st.session_state.get("license_calibration")
        precheck_conflicts = st.session_state.get(
            "license_precheck_conflicts",
            [],
        )
        if calibration is not None and calibration.corrections:
            correction_summary = "；".join(
                f"{item.raw_value}→{item.calibrated_value}"
                for item in calibration.corrections
            )
            st.info(f"已自动校准：{correction_summary}")
        if st.session_state.get("license_auto_accepted", False):
            st.success("行驶证已与 Excel 自动核对通过。")
        elif calibration is not None and calibration.requires_review:
            st.warning(
                "需要人工处理："
                + "；".join(calibration.review_reasons)
            )
        if precheck_conflicts:
            st.warning(
                "Excel 与行驶证存在冲突，需要人工处理："
            )
            for conflict in precheck_conflicts:
                st.write(
                    f"- {conflict.field_name}：{conflict.message}；"
                    f"来源值={conflict.source_values}"
                )

        needs_license_intervention = (
            calibration is None
            or calibration.requires_review
            or bool(precheck_conflicts)
        )
        show_license_editor = needs_license_intervention
        if not needs_license_intervention:
            show_license_editor = st.toggle(
                "手动修改行驶证识别结果",
                key="show_license_editor",
            )

        if show_license_editor:
            st.caption(
                "仅在自动核对异常或你主动修改时显示以下字段。"
            )
            st.caption(
                "系统仍会保留 OCR 原文、置信度和校准记录。"
            )
            st.text_input("车辆牌号", key="license_plate_number")
            st.text_input("所有人", key="license_owner_name")
            st.text_input("住址", key="license_address")
            st.text_input("使用性质", key="license_use_character")
            st.text_input("车辆类型", key="license_vehicle_type")
            st.text_input("品牌型号", key="license_vehicle_model")
            st.text_input("车辆识别代号（VIN）", key="license_vin")
            st.text_input("发动机号码", key="license_engine_number")
            st.date_input(
                "注册日期",
                value=None,
                key="license_registration_date",
            )
            st.date_input(
                "发证日期",
                value=None,
                key="license_issue_date",
            )
            if st.button("保存人工修改并继续"):
                try:
                    corrected_license = build_driving_license_from_widgets()
                    remaining_conflicts = run_license_subject_checks(
                        selected_vehicle,
                        corrected_license,
                    )
                    st.session_state[
                        "license_precheck_conflicts"
                    ] = remaining_conflicts
                    if remaining_conflicts:
                        st.error(
                            "修改后仍存在 Excel/行驶证冲突，"
                            "请继续核对。"
                        )
                    else:
                        st.session_state[
                            "confirmed_license"
                        ] = corrected_license
                        st.session_state["license_auto_accepted"] = False
                        st.success("人工修改已保存，资料核对通过")
                        st.rerun()
                except Exception as error:
                    st.error(f"请检查行驶证信息：{error}")

        if "confirmed_license" in st.session_state:
            st.subheader("现场核查")

            inspection_date = st.date_input(
                "核查日期",
                key="inspection_date",
            )

            actual_mileage_km = st.number_input(
                "现场里程（公里）",
                min_value=0,
                value=selected_vehicle.mileage_km,
                step=100,
            )

            condition_options = [
                "差",
                "较差",
                "一般",
                "较好",
                "好",
            ]

            exterior_grade = st.selectbox(
                "外观状况",
                options=condition_options,
                index=2,
            )

            interior_grade = st.selectbox(
                "内饰状况",
                options=condition_options,
                index=2,
            )

            hardware_grade = st.selectbox(
                "硬件状况",
                options=condition_options,
                index=2,
            )

            can_start = st.checkbox(
                "车辆可以正常启动",
                value=True,
            )

            can_drive = st.checkbox(
                "车辆可以正常行驶",
                value=True,
            )

            inspection_notes = st.text_area(
                "现场核查备注",
            )

            if st.button("确认现场核查并核对资料"):
                try:
                    clear_downstream_state()

                    confirmed_inspection = VehicleInspection(
                        inspection_date=inspection_date,
                        actual_mileage_km=actual_mileage_km,
                        exterior_grade=exterior_grade,
                        interior_grade=interior_grade,
                        hardware_grade=hardware_grade,
                        can_start=can_start,
                        can_drive=can_drive,
                        notes=inspection_notes,
                    )

                    valuation_request = ValuationRequest(
                        valuation_date=valuation_date,
                        subject_vehicle=selected_vehicle,
                        driving_license=st.session_state[
                            "confirmed_license"
                        ],
                        inspection=confirmed_inspection,
                    )

                    issues = run_structured_checks(
                        valuation_request
                    )

                    st.session_state[
                        "valuation_request"
                    ] = valuation_request

                    if issues:
                        st.session_state[
                            "initial_checks_passed"
                        ] = False

                        st.warning("发现以下资料问题：")

                        for issue in issues:
                            st.write(
                                f"- {issue.field_name}：{issue.message}；"
                                f"来源值={issue.source_values}"
                                + (
                                    "（可能为 OCR 识别错误）"
                                    if issue.possible_ocr_error
                                    else ""
                                )
                            )
                        st.info(
                            "流程已暂停。请返回上方修改资料并重新确认，"
                            "冲突消失后才会进入市场搜索。"
                        )
                    else:
                        st.session_state[
                            "initial_checks_passed"
                        ] = True

                        st.success(
                            "Excel、行驶证和现场核查信息核对通过"
                        )

                except Exception as error:
                    st.error(f"资料确认失败：{error}")

            if st.session_state.get(
                "initial_checks_passed",
                False,
            ):
                st.subheader("市场车型推荐")

                legal_model = extract_legal_model(
                    st.session_state[
                        "confirmed_license"
                    ].vehicle_model
                )

                mappings = (
                    load_model_mapping_knowledge_base(
                        MODEL_MAPPING_PATH
                    )
                )

                evidence = retrieve_model_mapping_evidence(
                    mappings,
                    legal_model,
                )

                if evidence:
                    recommendation = evidence[0]

                    st.write(
                        f"识别法定型号：{legal_model}"
                    )

                    st.write(
                        "推荐市场车系："
                        f"{recommendation.market_series}"
                    )

                    market_keyword = recommendation.market_keyword
                    st.write(
                        f"默认市场交易车型：{market_keyword}"
                    )

                    st.caption(
                        recommendation.evidence_summary
                    )

                    st.markdown(
                        "[查看公开来源]"
                        f"({recommendation.source_url})"
                    )

                    routes = load_market_search_routes(
                        MARKET_ROUTE_PATH
                    )

                    market_route = retrieve_market_search_route(
                        routes=routes,
                        provider="guazi",
                        market_series=recommendation.market_series,
                    )

                    if market_route is None:
                        st.warning(
                            "暂未配置该车系的瓜子搜索路径，"
                            "请手工补充市场案例。"
                        )

                    else:
                        target_market_year = st.session_state[
                            "confirmed_license"
                        ].registration_date.year
                        target_market_mileage = st.session_state[
                            "valuation_request"
                        ].inspection.actual_mileage_km
                        selected_cities = ["bj", "sh"]
                        selected_sources = ["guazi"]
                        max_search_rounds = 8
                        minimum_quality_score = 60
                        st.caption(
                            "默认条件：目标年份取行驶证注册年份，目标里程取现场里程；"
                            "先搜索北京、上海，再自动扩展广州、深圳；"
                            "最多8轮；质量分及年份/里程匹配分均不得低于60分，"
                            "完整合格案例达到3个后自动采用相似度最高的Top 3。"
                        )
                        search_signature_source = (
                            st.session_state[
                                "valuation_request"
                            ].model_dump_json()
                            + market_keyword
                            + market_route.series_path
                            + MARKET_SELECTION_POLICY_VERSION
                        )
                        automatic_search_key = hashlib.sha256(
                            search_signature_source.encode("utf-8")
                        ).hexdigest()
                        retry_market_search = st.button(
                            "重新运行市场搜索",
                            help="正常流程会自动搜索；仅在网络失败后使用此按钮。",
                        )
                        should_run_market_search = (
                            retry_market_search
                            or st.session_state.get("market_search_key")
                            != automatic_search_key
                        )

                    if (
                        market_route is not None
                        and should_run_market_search
                    ):
                        try:
                            clear_downstream_state()
                            st.session_state[
                                "market_search_key"
                            ] = automatic_search_key

                            with st.spinner(
                                "资料已通过，Agent 正在按默认条件自动搜索案例……"
                            ):
                                market_agent = ControlledMarketAgent(
                                    config=MarketAgentConfig(
                                        city_batches=[
                                            ["bj", "sh"],
                                            ["gz", "sz"],
                                        ],
                                        allowed_sources=selected_sources,
                                        target_count=3,
                                        max_search_rounds=int(max_search_rounds),
                                        minimum_quality_score=int(minimum_quality_score),
                                        minimum_similarity_score=60,
                                    ),
                                    case_evaluator=SnapshotMarketCaseEvaluator(),
                                    log_dir=Path("logs/agent"),
                                    checkpoint_path=Path(
                                        "logs/agent/market_graph_checkpoints.sqlite"
                                    ),
                                )
                                st.session_state[
                                    "market_agent_instance"
                                ] = market_agent
                                agent_state = market_agent.initialize_state(
                                    market_keyword=market_keyword,
                                    series_path=(
                                        market_route.series_path
                                    ),
                                    target_year=(
                                        int(target_market_year)
                                    ),
                                    target_mileage_km=(
                                        int(target_market_mileage)
                                    ),
                                )
                                agent_state = (
                                    market_agent.run_until_pause(
                                        agent_state
                                    )
                                )

                                if (
                                    agent_state.status
                                    == "candidates_ready"
                                ):
                                    apply_automatic_market_selection(
                                        market_agent,
                                        agent_state,
                                    )

                            st.session_state[
                                "market_agent_state"
                            ] = agent_state
                            st.session_state[
                                "market_candidates"
                            ] = agent_state.candidates
                            st.session_state[
                                "visible_market_candidate_count"
                            ] = 3
                            if market_agent.last_log_path is not None:
                                st.session_state[
                                    "market_agent_log_path"
                                ] = str(market_agent.last_log_path)

                            if agent_state.failed_cities:
                                st.warning(
                                    "以下城市搜索失败："
                                    + "、".join(
                                        agent_state.failed_cities
                                    )
                                )

                            if agent_state.status in {
                                "failed",
                                "awaiting_human_input",
                            }:
                                st.warning(agent_state.stop_reason)

                        except Exception as error:
                            st.error(f"Agent 运行失败：{error}")

                else:
                    st.warning(
                        "知识库没有找到对应车型，"
                        "请手动输入市场交易车型。"
                    )

                if "market_candidates" in st.session_state:
                    candidates = st.session_state[
                        "market_candidates"
                    ]

                    market_cases_auto_selected = st.session_state.get(
                        "market_cases_auto_selected",
                        False,
                    )

                    visible_count = st.session_state.get(
                        "visible_market_candidate_count",
                        3,
                    )

                    visible_candidates = (
                        []
                        if market_cases_auto_selected
                        else candidates[:visible_count]
                    )

                    if market_cases_auto_selected:
                        st.success(
                            f"找到 {len(candidates)} 个合格案例，"
                            "已自动采用相似度最高的 Top 3。"
                        )
                    else:
                        st.warning(
                            "达到最低相似度且证据完整的案例不足3个，"
                            "请人工补充或选择。"
                        )

                    agent_state = st.session_state.get(
                        "market_agent_state"
                    )
                    quality_by_url = {
                        str(item.source_url): item
                        for item in (
                            agent_state.quality_assessments
                            if agent_state is not None
                            else []
                        )
                    }
                    if agent_state is not None:
                        if (
                            agent_state.status
                            == "candidates_ready"
                        ):
                            automatic_selection = st.session_state.get(
                                "automatic_case_selection"
                            )
                            st.warning(
                                "案例未满足自动采用条件，需要人工选择。"
                            )
                            if automatic_selection is not None:
                                for reason in automatic_selection.reasons:
                                    st.write(f"- {reason}")

                        with st.expander("查看 Agent 执行轨迹"):
                            trace_rows = [
                                {
                                    "步骤": entry.step,
                                    "工具": entry.tool,
                                    "Planner理由": (
                                        entry.planner_reason
                                    ),
                                    "策略说明": entry.policy_note,
                                    "执行结果": entry.outcome,
                                    "候选数量": (
                                        entry.candidate_count
                                    ),
                                    "耗时(ms)": entry.duration_ms,
                                }
                                for entry in agent_state.trace
                            ]
                            st.dataframe(
                                trace_rows,
                                use_container_width=True,
                                hide_index=True,
                            )

                        if agent_state.status == "awaiting_human_input":
                            with st.expander(
                                "补充市场案例并恢复 Agent",
                                expanded=True,
                            ):
                                st.caption(
                                    "仅在自动搜索不足3例时使用。提交后，"
                                    "LangGraph 会从当前 checkpoint 继续评分，"
                                    "不会重新执行已经完成的城市搜索。"
                                )
                                manual_case_rows = st.data_editor(
                                    [
                                        {
                                            "车源URL": "",
                                            "车型": market_keyword,
                                            "上牌年份": int(target_market_year),
                                            "里程公里": int(target_market_mileage),
                                            "城市": "人工补充",
                                            "价格元": 0,
                                        }
                                    ],
                                    num_rows="dynamic",
                                    hide_index=True,
                                    use_container_width=True,
                                    key="manual_market_case_editor",
                                )
                                if st.button("提交补充案例并恢复搜索"):
                                    try:
                                        additional_listings = [
                                            MarketListing(
                                                source_url=row["车源URL"],
                                                vehicle_model=row["车型"],
                                                registration_year=int(
                                                    row["上牌年份"]
                                                ),
                                                mileage_km=int(row["里程公里"]),
                                                city=row["城市"],
                                                price_cny=row["价格元"],
                                            )
                                            for row in manual_case_rows
                                            if str(row.get("车源URL", "")).strip()
                                        ]
                                        if not additional_listings:
                                            raise ValueError(
                                                "请至少填写一条补充案例"
                                            )
                                        active_market_agent = (
                                            st.session_state.get(
                                                "market_agent_instance"
                                            )
                                        )
                                        if active_market_agent is None:
                                            raise ValueError(
                                                "当前 Agent 会话已失效，"
                                                "请重新运行市场搜索"
                                            )
                                        resume_market_agent = getattr(
                                            active_market_agent,
                                            "resume_with_human_cases",
                                        )
                                        resumed_state = (
                                            resume_market_agent(
                                                agent_state.graph_thread_id,
                                                additional_listings,
                                            )
                                        )
                                        st.session_state[
                                            "market_agent_state"
                                        ] = resumed_state
                                        st.session_state[
                                            "market_candidates"
                                        ] = resumed_state.candidates
                                        st.session_state[
                                            "visible_market_candidate_count"
                                        ] = 3
                                        if (
                                            resumed_state.status
                                            == "candidates_ready"
                                        ):
                                            apply_automatic_market_selection(
                                                active_market_agent,
                                                resumed_state,
                                            )
                                        st.rerun()
                                    except Exception as error:
                                        st.error(f"补充案例处理失败：{error}")

                    if len(candidates) < 3 and not market_cases_auto_selected:
                        st.warning(
                            f"目前只有 {len(candidates)} 个案例达到"
                            f" {minimum_quality_score} 分质量门槛，"
                            "需要扩大或调整搜索条件。"
                        )

                    for index, item in enumerate(
                        visible_candidates,
                        start=1,
                    ):
                        with st.expander(
                            f"候选案例 {index}：{item.vehicle_model}",
                            expanded=not st.session_state.get(
                                "market_cases_auto_selected",
                                False,
                            ),
                        ):
                            st.checkbox(
                                "采用此案例",
                                value=(
                                    str(item.source_url)
                                    in {
                                        str(case.source_url)
                                        for case in st.session_state.get(
                                            "confirmed_market_cases",
                                            visible_candidates[:3],
                                        )
                                    }
                                ),
                                key=(
                                    "market_case_selected_"
                                    f"{item.source_url}"
                                ),
                            )

                            similarity = calculate_listing_similarity(
                                item,
                                int(target_market_year),
                                int(target_market_mileage),
                            )

                            st.write(
                                f"综合相似度：{similarity:.1%}"
                            )
                            quality = quality_by_url.get(
                                str(item.source_url)
                            )
                            if quality is not None:
                                st.write(
                                    f"Python质量评分：{quality.total_score}/100"
                                )
                                if quality.risk_warnings:
                                    st.warning(
                                        "；".join(quality.risk_warnings)
                                    )
                            st.write(
                                f"上牌年份：{item.registration_year}"
                            )
                            st.write(
                                f"里程：{item.mileage_km:,} 公里"
                            )
                            st.write(
                                f"价格：{item.price_cny:,.0f} 元"
                            )
                            st.write(f"城市：{item.city}")

                            st.markdown(
                                f"[查看车源]({item.source_url})"
                            )

                    if (
                        not market_cases_auto_selected
                        and visible_count < len(candidates)
                    ):
                        if st.button("添加一个候选案例"):
                            st.session_state[
                                "visible_market_candidate_count"
                            ] = visible_count + 1

                            st.rerun()
                    
                    selected_market_cases = [
                        item
                        for item in visible_candidates
                        if st.session_state.get(
                            "market_case_selected_"
                            f"{item.source_url}",
                            False,
                        )
                    ]

                    if (
                        not market_cases_auto_selected
                        and st.button("确认采用的市场案例")
                    ):
                        for state_key in (
                            "ai_comparison_suggestions",
                            "adjusted_market_prices",
                            "final_valuation_value",
                            "generated_excel_bytes",
                            "generated_report_bytes",
                        ):
                            st.session_state.pop(
                                state_key,
                                None,
                            )

                        if len(selected_market_cases) < 3:
                            st.error(
                                "至少需要选择 3 个市场案例，"
                                f"目前只选择了 {len(selected_market_cases)} 个。"
                            )
                        else:
                            selected_urls = [
                                str(item.source_url)
                                for item in selected_market_cases
                            ]
                            selected_url_set = set(selected_urls)
                            detail_by_url = {
                                str(item.source_url): item
                                for item in agent_state.preview_details
                            }
                            snapshot_cases = selected_market_cases
                            market_case_details = [
                                detail_by_url[str(item.source_url)]
                                for item in selected_market_cases
                                if str(item.source_url) in detail_by_url
                            ]
                            case_screenshots = {
                                url: images
                                for url, images in agent_state.preview_screenshots.items()
                                if url in selected_url_set
                            }
                            snapshot_failures = {
                                url: "缺少同次读取的详情或截图"
                                for url in selected_urls
                                if (
                                    url not in detail_by_url
                                    or url not in case_screenshots
                                )
                            }

                            if snapshot_failures or len(snapshot_cases) < 3:
                                st.error(
                                    "成功保存的完整案例不足3个，"
                                    "已返回市场案例搜索 Agent。"
                                )
                                active_market_agent = st.session_state.get(
                                    "market_agent_instance"
                                ) or ControlledMarketAgent()
                                active_market_agent.return_incomplete_cases(
                                    agent_state,
                                    list(snapshot_failures),
                                )
                            else:
                                if (
                                    agent_state.status
                                    == "candidates_ready"
                                ):
                                    active_market_agent = st.session_state.get(
                                        "market_agent_instance"
                                    ) or ControlledMarketAgent()
                                    active_market_agent.approve_candidates(agent_state)
                                st.session_state[
                                    "market_agent_state"
                                ] = agent_state
                                st.session_state[
                                    "market_cases_auto_selected"
                                ] = False
                                st.session_state[
                                    "confirmed_market_cases"
                                ] = snapshot_cases
                                st.session_state[
                                    "market_case_details"
                                ] = market_case_details
                                st.session_state[
                                    "market_case_screenshots"
                                ] = case_screenshots

                                st.success(
                                    f"已确认 {len(snapshot_cases)} 个市场案例，"
                                    "价格、详情和截图来自同一次网页读取"
                                )

                            if snapshot_failures:
                                with st.expander(
                                    "查看未能保存的案例"
                                ):
                                    for case_url, reason in (
                                        snapshot_failures.items()
                                    ):
                                        st.write(
                                            f"{case_url}：{reason}"
                                        )

                    if "market_case_details" in st.session_state:
                        st.subheader("市场案例详情")

                        detail_rows = []

                        for index, detail in enumerate(
                            st.session_state["market_case_details"],
                            start=1,
                        ):
                            detail_rows.append(
                                {
                                    "案例": f"实例{index}",
                                    "成色": detail.condition_score,
                                    "车况等级": detail.condition_grade,
                                    "车况说明": detail.condition_summary,
                                    "理赔次数": detail.claim_count,
                                    "过户次数": detail.transfer_count,
                                    "检测状态": detail.inspection_status,
                                    "车辆用途": detail.vehicle_use,
                                    "车身颜色": detail.body_color,
                                }
                            )

                        st.dataframe(
                            detail_rows,
                            use_container_width=True,
                            hide_index=True,
                        )

                        if (
                            "ai_comparison_suggestions"
                            not in st.session_state
                        ):
                            detail_by_url = {
                                str(detail.source_url): detail
                                for detail in st.session_state[
                                    "market_case_details"
                                ]
                            }

                            suggestions = []
                            provider = OllamaProvider()
                            rules = load_adjustment_rule_set(
                                Path(
                                    "data/public/adjustment_rules.json"
                                )
                            )

                            with st.spinner(
                                "案例已确定，AI正在自动生成有证据的调整建议……"
                            ):
                                for index, listing in enumerate(
                                    st.session_state[
                                        "confirmed_market_cases"
                                    ],
                                    start=1,
                                ):
                                    case_url = str(listing.source_url)

                                    detail = detail_by_url.get(
                                        case_url,
                                        MarketListingDetail(
                                            source_url=case_url
                                        ),
                                    )

                                    suggestion = (
                                        generate_comparison_suggestion(
                                            provider=provider,
                                            case_id=f"CASE-{index}",
                                            request=st.session_state[
                                                "valuation_request"
                                            ],
                                            listing=listing,
                                            detail=detail,
                                            rules=rules,
                                        )
                                    )

                                    suggestions.append(suggestion)

                            st.session_state[
                                "ai_comparison_suggestions"
                            ] = suggestions

                            st.success(
                                f"已自动生成 {len(suggestions)} 个案例的参数建议"
                            )

                        if "ai_comparison_suggestions" in st.session_state:
                            suggestions = st.session_state[
                                "ai_comparison_suggestions"
                            ]
                            adjustment_review = evaluate_adjustment_review(
                                suggestions
                            )
                            st.session_state[
                                "adjustment_review_decision"
                            ] = adjustment_review

                            factor_definitions = [
                                ("交易情况", "transaction"),
                                ("年检状况", "inspection"),
                                ("过户情况", "transfer"),
                                ("车辆用途", "vehicle_use"),
                                ("外观", "exterior"),
                                ("内饰", "interior"),
                                ("硬件设施状况", "hardware"),
                            ]

                            case_columns = [
                                f"实例{index}（AI建议）"
                                for index in range(
                                    1,
                                    len(suggestions) + 1,
                                )
                            ]

                            adjustment_rows = []
                            evidence_rows = []

                            for factor_label, factor_name in factor_definitions:
                                row = {
                                    "因素": factor_label,
                                    "待估车辆": 100,
                                }

                                for index, suggestion in enumerate(
                                    suggestions,
                                    start=1,
                                ):
                                    factor = getattr(
                                        suggestion,
                                        factor_name,
                                    )

                                    row[
                                        f"实例{index}（AI建议）"
                                    ] = factor.suggested_index
                                    evidence_rows.append(
                                        {
                                            "案例": f"实例{index}",
                                            "因素": factor_label,
                                            "证据充分": factor.evidence_sufficient,
                                            "档位差": factor.grade_difference,
                                            "置信度": factor.confidence,
                                            "正式指数": factor.suggested_index,
                                            "理由与证据": factor.reason,
                                        }
                                    )

                                adjustment_rows.append(row)

                            with st.expander(
                                "比较因素条件指数表",
                                expanded=False,
                            ):
                                st.caption(
                                    "Qwen只建议方向、档位差和理由；"
                                    "正式指数由Python规则计算，"
                                    "证据不足强制为100。下表供人工复核。"
                                )
                                st.dataframe(
                                    evidence_rows,
                                    use_container_width=True,
                                    hide_index=True,
                                )
                                st.caption(
                                    "确认依据后，可在下方修改最终采用指数"
                                )

                                edited_adjustments = st.data_editor(
                                    adjustment_rows,
                                    use_container_width=True,
                                    hide_index=True,
                                    disabled=[
                                        "因素",
                                        "待估车辆",
                                    ],
                                    column_config={
                                        column: st.column_config.NumberColumn(
                                            column,
                                            min_value=70,
                                            max_value=130,
                                            step=1,
                                        )
                                        for column in case_columns
                                    },
                                    key="ai_adjustment_editor",
                                )

                            st.session_state[
                                "edited_ai_adjustments"
                            ] = edited_adjustments

                            rules = load_adjustment_rule_set(
                                Path(
                                    "data/public/adjustment_rules.json"
                                )
                            )

                            request = st.session_state[
                                "valuation_request"
                            ]
                            confirmed_cases = st.session_state[
                                "confirmed_market_cases"
                            ]

                            subject_used_years = (
                                (
                                    request.valuation_date
                                    - request.driving_license.registration_date
                                ).days
                                / 365.25
                            )

                            subject_annual_mileage = (
                                request.inspection.actual_mileage_km
                                / subject_used_years
                            )

                            mileage_row = {
                                "因素": "年均行驶里程",
                                "待估车辆": 100,
                            }
                            registration_row = {
                                "因素": "上牌时间",
                                "待估车辆": 100,
                            }

                            for index, listing in enumerate(
                                confirmed_cases,
                                start=1,
                            ):
                                column_name = f"实例{index}（公式）"

                                comparable_used_years = (
                                    request.valuation_date.year
                                    - listing.registration_year
                                )

                                if comparable_used_years <= 0:
                                    raise ValueError(
                                        "案例上牌年份必须早于评估基准日"
                                    )

                                comparable_annual_mileage = (
                                    listing.mileage_km
                                    / comparable_used_years
                                )

                                mileage_row[column_name] = (
                                    calculate_annual_mileage_bucket_index(
                                        subject_annual_mileage,
                                        comparable_annual_mileage,
                                        rules.annual_mileage_rule,
                                    )
                                )

                                registration_row[column_name] = (
                                    calculate_registration_year_index(
                                        request.driving_license.registration_date.year,
                                        listing.registration_year,
                                        rules.registration_rule,
                                    )
                                )

                            formula_rows = [
                                mileage_row,
                                registration_row,
                            ]

                            with st.expander(
                                "公式计算指数",
                                expanded=False,
                            ):
                                st.caption(
                                    "案例只提供上牌年份，"
                                    "因此年均里程为近似计算"
                                )

                                st.dataframe(
                                    formula_rows,
                                    use_container_width=True,
                                    hide_index=True,
                                )

                            st.session_state[
                                "formula_adjustments"
                            ] = formula_rows

                            ai_rows = edited_adjustments

                            factor_labels = [
                                row["因素"]
                                for row in ai_rows
                            ] + [
                                row["因素"]
                                for row in formula_rows
                            ]

                            correction_rows = [
                                {"项目": "交易单价"}
                            ] + [
                                {"项目": factor_label}
                                for factor_label in factor_labels
                            ]

                            adjusted_price_row = {
                                "项目": "修正后单价"
                            }
                            adjusted_prices = []

                            for case_index, listing in enumerate(
                                confirmed_cases,
                                start=1,
                            ):
                                ai_column = (
                                    f"实例{case_index}（AI建议）"
                                )
                                formula_column = (
                                    f"实例{case_index}（公式）"
                                )
                                result_column = f"实例{case_index}"

                                ai_index_values = [
                                    int(row[ai_column])
                                    for row in ai_rows
                                ]
                                formula_index_values = [
                                    int(row[formula_column])
                                    for row in formula_rows
                                ]

                                all_index_values = (
                                    ai_index_values
                                    + formula_index_values
                                )

                                correction_rows[0][result_column] = float(
                                    listing.price_cny
                                )

                                for row_index, index_value in enumerate(
                                    all_index_values,
                                    start=1,
                                ):
                                    correction_rows[row_index][
                                        result_column
                                    ] = round(
                                        100 / index_value,
                                        4,
                                    )

                                adjusted_price = (
                                    calculate_price_from_index_values(
                                        listing.price_cny,
                                        all_index_values,
                                    )
                                )

                                adjusted_prices.append(adjusted_price)

                                adjusted_price_row[result_column] = round(
                                    float(adjusted_price),
                                    2,
                                )

                            correction_rows.append(
                                adjusted_price_row
                            )

                            final_value = (
                                calculate_rounded_average_value(
                                    adjusted_prices
                                )
                            )

                            with st.expander(
                                "比较因素修正系数表",
                                expanded=True,
                            ):
                                st.dataframe(
                                    correction_rows,
                                    use_container_width=True,
                                    hide_index=True,
                                )

                            st.metric(
                                "车辆评估建议值",
                                f"{final_value:,.0f} 元",
                            )

                            st.session_state[
                                "adjusted_market_prices"
                            ] = adjusted_prices
                            st.session_state[
                                "final_valuation_value"
                            ] = final_value

                            if adjustment_review.requires_review:
                                st.warning(
                                    "调整建议存在异常，需要人工复核后继续："
                                )
                                for reason in adjustment_review.reasons:
                                    st.write(f"- {reason}")
                                st.checkbox(
                                    "我已处理上述异常并确认调整参数",
                                    key="adjustments_approved",
                                )
                            else:
                                st.session_state["adjustments_approved"] = True
                                st.success(
                                    "调整建议通过证据、置信度和档位差校验，"
                                    "已自动进入确定性计算。"
                                )

                            if st.button(
                                "生成Excel结果",
                                disabled=not st.session_state.get(
                                    "adjustments_approved",
                                    False,
                                ),
                            ):
                                try:
                                    case_screenshots = (
                                        st.session_state[
                                            "market_case_screenshots"
                                        ]
                                    )
                                    excel_result = build_case_sheets_excel(
                                        excel_bytes=uploaded_file.getvalue(),
                                        listings=confirmed_cases,
                                        details=st.session_state.get(
                                            "market_case_details",
                                            [],
                                        ),
                                        request=st.session_state[
                                            "valuation_request"
                                        ],
                                        ai_rows=ai_rows,
                                        formula_rows=formula_rows,
                                        rules=rules,
                                        screenshots=case_screenshots,
                                        expected_final_value=final_value,
                                    )

                                    st.session_state[
                                        "generated_excel_bytes"
                                    ] = excel_result

                                    st.success("Excel生成成功")

                                except Exception as error:
                                    st.error(f"Excel生成失败：{error}")

                            if "generated_excel_bytes" in st.session_state:
                                st.download_button(
                                    label="下载评估Excel",
                                    data=st.session_state[
                                        "generated_excel_bytes"
                                    ],
                                    file_name="车辆评估结果.xlsx",
                                    mime=(
                                        "application/vnd.openxmlformats-"
                                        "officedocument.spreadsheetml.sheet"
                                    ),
                                )

                            if st.button(
                                "生成Word报告初稿",
                                disabled=not st.session_state.get(
                                    "adjustments_approved",
                                    False,
                                ),
                            ):
                                try:
                                    with st.spinner(
                                        "正在检索评估准则并生成报告……"
                                    ):
                                        request = st.session_state[
                                            "valuation_request"
                                        ]
                                        confirmed_cases = st.session_state[
                                            "confirmed_market_cases"
                                        ]

                                        rag = VehicleValuationRAG(
                                            Path(
                                                "data/rag/processed/"
                                                "chunks.jsonl"
                                            ),
                                            Path(
                                                "data/rag/processed/"
                                                "faiss.index"
                                            ),
                                            retrieval_strategy="weighted_hybrid",
                                        )

                                        evidence = (
                                            retrieve_full_report_evidence(
                                                rag
                                            )
                                        )

                                        report_sections = (
                                            generate_report_sections(
                                                evidence=evidence,
                                            )
                                        )

                                        report_draft = build_report_draft(
                                            request=request,
                                            listings=confirmed_cases,
                                            final_value=final_value,
                                            evidence=evidence,
                                            sections=report_sections,
                                        )

                                        vehicle = (
                                            request.subject_vehicle
                                        )
                                        license_data = (
                                            request.driving_license
                                        )

                                        increase_value = (
                                            final_value
                                            - vehicle.book_value_net_cny
                                        )

                                        if (
                                            vehicle.book_value_net_cny
                                            > 0
                                        ):
                                            increase_rate = (
                                                increase_value
                                                / vehicle.book_value_net_cny
                                                * 100
                                            )
                                            increase_rate_text = (
                                                f"{increase_rate:.2f}%"
                                            )
                                        else:
                                            increase_rate_text = (
                                                "不适用"
                                            )

                                        fact_replacements = {
                                            "{{CLIENT_NAME}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_SHORT_NAME}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_CREDIT_CODE}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_TYPE}}": "待补充",
                                            "{{CLIENT_ADDRESS}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_RESPONSIBLE_PERSON}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_ESTABLISHMENT_DATE}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_OPERATION_PERIOD}}": (
                                                "待补充"
                                            ),
                                            "{{CLIENT_BUSINESS_SCOPE}}": (
                                                "待补充"
                                            ),
                                            "{{VALUATION_AGENCY}}": (
                                                "评估机构待补充"
                                            ),
                                            "{{REPORT_NUMBER}}": (
                                                "自动生成初稿（待编号）"
                                            ),
                                            "{{REPORT_DATE}}": (
                                                f"{date.today():%Y年%m月%d日}"
                                            ),
                                            "{{ECONOMIC_ACTION_BASIS}}": (
                                                "经济行为依据待补充"
                                            ),
                                            "{{VEHICLE_NAME}}": (
                                                vehicle.vehicle_name
                                            ),
                                            "{{PLATE_NUMBER}}": (
                                                vehicle.plate_number
                                            ),
                                            "{{VALUATION_DATE}}": (
                                                request.valuation_date.strftime(
                                                    "%Y年%m月%d日"
                                                )
                                            ),
                                            "{{BOOK_VALUE_ORIGINAL}}": (
                                                f"{vehicle.book_value_original_cny / 10000:.2f}"
                                                "万元"
                                            ),
                                            "{{BOOK_VALUE_NET}}": (
                                                f"{vehicle.book_value_net_cny / 10000:.2f}"
                                                "万元"
                                            ),
                                            "{{VALUATION_RESULT}}": (
                                                f"{final_value / 10000:.2f}"
                                                "万元"
                                            ),
                                            "{{VALUATION_INCREASE}}": (
                                                f"{increase_value / 10000:.2f}"
                                                "万元"
                                            ),
                                            "{{VALUATION_INCREASE_RATE}}": (
                                                increase_rate_text
                                            ),
                                        }

                                        report_bytes = (
                                            build_report_docx_from_template(
                                                report_draft,
                                                fact_replacements,
                                            )
                                        )

                                        st.session_state[
                                            "generated_report_bytes"
                                        ] = report_bytes
                                        st.session_state[
                                            "report_valid_chunk_ids"
                                        ] = {
                                            item["chunk_id"] for item in evidence
                                        }
                                        st.session_state[
                                            "report_cited_chunk_ids"
                                        ] = set(report_draft.cited_chunk_ids)

                                    st.success("Word报告初稿生成成功")

                                except Exception as error:
                                    st.error(
                                        f"Word报告生成失败：{error}"
                                    )

                            if (
                                "generated_report_bytes"
                                in st.session_state
                            ):
                                st.download_button(
                                    label="下载Word报告初稿",
                                    data=st.session_state[
                                        "generated_report_bytes"
                                    ],
                                    file_name="车辆评估报告初稿.docx",
                                    mime=(
                                        "application/vnd.openxmlformats-"
                                        "officedocument.wordprocessingml."
                                        "document"
                                    ),
                                )

                            if (
                                "generated_excel_bytes" in st.session_state
                                and "generated_report_bytes"
                                in st.session_state
                            ):
                                consistency = validate_output_consistency(
                                    excel_bytes=st.session_state[
                                        "generated_excel_bytes"
                                    ],
                                    report_bytes=st.session_state[
                                        "generated_report_bytes"
                                    ],
                                    request=st.session_state[
                                        "valuation_request"
                                    ],
                                    listings=st.session_state[
                                        "confirmed_market_cases"
                                    ],
                                    final_value=st.session_state[
                                        "final_valuation_value"
                                    ],
                                    screenshots=st.session_state[
                                        "market_case_screenshots"
                                    ],
                                    cited_chunk_ids=st.session_state.get(
                                        "report_cited_chunk_ids", set()
                                    ),
                                    valid_chunk_ids=st.session_state.get(
                                        "report_valid_chunk_ids", set()
                                    ),
                                )
                                if consistency.passed:
                                    st.success(
                                        "Python、Excel、Word、案例证据和 RAG 引用一致性检查通过"
                                    )
                                else:
                                    st.error(
                                        "输出一致性检查未通过，流程已暂停："
                                    )
                                    for issue in consistency.issues:
                                        st.write(f"- {issue.check}：{issue.message}")
                                st.checkbox(
                                    "我已下载并复核 Excel 与 Word 初稿",
                                    key="final_outputs_approved",
                                    disabled=not consistency.passed,
                                    help=(
                                        "这一步只表示初稿流程完成，"
                                        "不代表正式评估结论获批。"
                                    ),
                                )

    else:
        st.info("请上传所选车辆对应的行驶证照片")
