import streamlit as st
from datetime import date
from vehicle_valuation.checks import run_initial_checks
from vehicle_valuation.model import (
    DrivingLicenseData,
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
    recognize_license_text,
)
from pathlib import Path

from vehicle_valuation.model_mapping_retrieval import (
    extract_legal_model,
    load_model_mapping_knowledge_base,
    retrieve_model_mapping_evidence,
)

from vehicle_valuation.market_scraper import (
    calculate_listing_similarity,
    fetch_guazi_listings_from_cities,
    shortlist_market_listings,
    fetch_market_page,
    parse_market_listing_detail,
    capture_market_listing_screenshots,
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

GUAZI_CITY_PATHS = [
    "bj",
    "sh",
    "gz",
    "sz",
]


@st.cache_data(
    ttl=86_400,
    show_spinner=False,
)
def load_cached_market_detail(
    case_url: str,
) -> MarketListingDetail:
    """抓取并缓存一个市场案例的详情信息。"""

    html = fetch_market_page(
        case_url,
        scroll_rounds=0,
    )

    return parse_market_listing_detail(
        html,
        case_url,
    )


@st.cache_data(
    ttl=86_400,
    show_spinner=False,
)
def load_cached_market_screenshots(
    case_url: str,
) -> tuple[bytes, bytes]:
    """抓取并缓存一个市场案例的两张截图。"""

    return capture_market_listing_screenshots(
        case_url
    )


st.set_page_config(
    page_title="车辆评估助手",
    page_icon="🚗",
)

st.title("车辆评估助手")

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

        if st.button("识别行驶证"):
            try:
                with st.spinner("正在识别行驶证……"):
                    ocr_lines = recognize_license_text(
                        driving_license_image.getvalue()
                    )

                st.session_state["license_ocr_lines"] = (
                    ocr_lines
                )

                extracted_fields = extract_license_fields(
                    ocr_lines
                )

                widget_keys = {
                    "plate_number": "license_plate_number",
                    "vehicle_type": "license_vehicle_type",
                    "owner_name": "license_owner_name",
                    "address": "license_address",
                    "use_character": "license_use_character",
                    "vehicle_model": "license_vehicle_model",
                    "vin": "license_vin",
                    "engine_number": "license_engine_number",
                }

                for field_name, widget_key in (
                    widget_keys.items()
                ):
                    field_value = extracted_fields[
                        field_name
                    ]

                    if field_value is not None:
                        st.session_state[widget_key] = (
                            field_value
                        )

                registration_date = extracted_fields[
                    "registration_date"
                ]

                if registration_date is not None:
                    st.session_state[
                        "license_registration_date"
                    ] = date.fromisoformat(
                        registration_date
                    )

                issue_date = extracted_fields[
                    "issue_date"
                ]

                if issue_date is not None:
                    st.session_state[
                        "license_issue_date"
                    ] = date.fromisoformat(issue_date)

            except Exception as error:
                st.error(f"行驶证识别失败：{error}")

        ocr_lines = st.session_state.get(
            "license_ocr_lines",
            [],
        )

        st.subheader("行驶证识别结果")

        st.caption(
            "OCR已自动填写，请人工核对并修改识别错误。"
        )

        license_plate_number = st.text_input(
            "车辆牌号",
            key="license_plate_number",
        )

        license_owner_name = st.text_input(
            "所有人",
            key="license_owner_name",
        )

        license_address = st.text_input(
            "住址",
            key="license_address",
        )

        license_use_character = st.text_input(
            "使用性质",
            key="license_use_character",
        )

        license_vehicle_type = st.text_input(
            "车辆类型",
            key="license_vehicle_type",
        )

        license_vehicle_model = st.text_input(
            "品牌型号",
            key="license_vehicle_model",
        )

        license_vin = st.text_input(
            "车辆识别代号（VIN）",
            key="license_vin",
        )

        license_engine_number = st.text_input(
            "发动机号码",
            key="license_engine_number",
        )

        license_registration_date = st.date_input(
            "注册日期",
            value=None,
            key="license_registration_date",
        )

        license_issue_date = st.date_input(
            "发证日期",
            value=None,
            key="license_issue_date",
        )

        if st.button("确认行驶证信息"):
            try:
                confirmed_license = DrivingLicenseData(
                    plate_number=license_plate_number,
                    vehicle_type=license_vehicle_type,
                    owner_name=license_owner_name,
                    address=license_address,
                    use_character=license_use_character,
                    vehicle_model=license_vehicle_model,
                    vin=license_vin,
                    engine_number=license_engine_number,
                    registration_date=(
                        license_registration_date
                    ),
                    issue_date=license_issue_date,
                )

                st.session_state[
                    "confirmed_license"
                ] = confirmed_license

                st.success("行驶证信息已确认")

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

                    issues = run_initial_checks(
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
                            st.write(f"- {issue}")
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

                    market_keyword = st.text_input(
                        "市场交易车型",
                        value=(
                            recommendation.market_keyword
                        ),
                        key="market_keyword",
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

                    elif st.button("搜索市场案例"):
                        try:
                            with st.spinner(
                                "正在搜索多个城市的市场车源……"
                            ):
                                listings, failed_cities = (
                                    fetch_guazi_listings_from_cities(
                                        city_paths=GUAZI_CITY_PATHS,
                                        series_path=(
                                            market_route.series_path
                                        ),
                                    )
                                )

                                candidates = shortlist_market_listings(
                                    listings=listings,
                                    market_keyword=market_keyword,
                                    target_year=(
                                        st.session_state[
                                            "confirmed_license"
                                        ].registration_date.year
                                    ),
                                    target_mileage_km=(
                                        st.session_state[
                                            "valuation_request"
                                        ].inspection.actual_mileage_km
                                    ),
                                    limit=10,
                                    minimum_similarity=0.70,
                                )

                            st.session_state[
                                "market_candidates"
                            ] = candidates
                            st.session_state[
                                "visible_market_candidate_count"
                            ] = 3

                            if failed_cities:
                                st.warning(
                                    "以下城市搜索失败："
                                    + "、".join(failed_cities)
                                )

                        except Exception as error:
                            st.error(f"市场案例搜索失败：{error}")

                else:
                    st.warning(
                        "知识库没有找到对应车型，"
                        "请手动输入市场交易车型。"
                    )

                if "market_candidates" in st.session_state:
                    candidates = st.session_state[
                        "market_candidates"
                    ]

                    visible_count = st.session_state.get(
                        "visible_market_candidate_count",
                        3,
                    )

                    visible_candidates = candidates[:visible_count]

                    st.success(
                        f"找到 {len(candidates)} 个相近候选案例，"
                        f"当前显示 Top {len(visible_candidates)}"
                    )

                    if len(candidates) < 3:
                        st.warning(
                            f"目前只有 {len(candidates)} 个案例达到"
                            " 70% 相似度门槛，需要扩大搜索范围。"
                        )

                    for index, item in enumerate(
                        visible_candidates,
                        start=1,
                    ):
                        with st.expander(
                            f"候选案例 {index}：{item.vehicle_model}",
                            expanded=True,
                        ):
                            st.checkbox(
                                "采用此案例",
                                value=index <= 3,
                                key=(
                                    "market_case_selected_"
                                    f"{item.source_url}"
                                ),
                            )

                            similarity = calculate_listing_similarity(
                                item,
                                st.session_state[
                                    "confirmed_license"
                                ].registration_date.year,
                                st.session_state[
                                    "valuation_request"
                                ].inspection.actual_mileage_km,
                            )

                            st.write(
                                f"综合相似度：{similarity:.1%}"
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

                    if visible_count < len(candidates):
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

                    if st.button("确认采用的市场案例"):
                        if len(selected_market_cases) < 3:
                            st.error(
                                "至少需要选择 3 个市场案例，"
                                f"目前只选择了 {len(selected_market_cases)} 个。"
                            )
                        else:
                            st.session_state[
                                "confirmed_market_cases"
                            ] = selected_market_cases

                            with st.spinner("正在读取所选案例的详情……"):
                                market_case_details = []
                                failed_detail_urls = []

                                for item in selected_market_cases:
                                    try:
                                        case_url = str(item.source_url)

                                        detail = load_cached_market_detail(
                                            case_url
                                        )

                                        market_case_details.append(detail)

                                    except Exception as error:
                                        failed_detail_urls.append(
                                            f"{item.source_url}：{error}"
                                        )

                            st.session_state[
                                "market_case_details"
                            ] = market_case_details

                            st.success(
                                f"已确认 {len(selected_market_cases)} 个市场案例"
                            )

                            if failed_detail_urls:
                                st.warning(
                                    f"有 {len(failed_detail_urls)} 个案例详情读取失败"
                                )

                                for failure in failed_detail_urls:
                                    st.write(f"- {failure}")

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

                        if st.button("AI自动生成调整参数"):
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

                            with st.spinner("AI正在比较待估车辆与市场案例……"):
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
                                f"AI已生成 {len(suggestions)} 个案例的参数建议"
                            )

                        if "ai_comparison_suggestions" in st.session_state:
                            suggestions = st.session_state[
                                "ai_comparison_suggestions"
                            ]

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

                                adjustment_rows.append(row)

                            st.subheader("比较因素条件指数表")
                            st.caption("AI建议列可以直接修改")

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

                            st.subheader("公式计算指数")
                            st.caption(
                                "案例只提供上牌年份，因此年均里程为近似计算"
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

                            st.subheader("比较因素修正系数表")

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

                            if st.button("生成Excel结果"):
                                try:
                                    case_screenshots = {}
                                    screenshot_failures = []

                                    with st.spinner(
                                        "正在生成市场案例截图……"
                                    ):
                                        for listing in confirmed_cases:
                                            case_url = str(
                                                listing.source_url
                                            )

                                            try:
                                                case_screenshots[
                                                    case_url
                                                ] = (
                                                    load_cached_market_screenshots(
                                                        case_url
                                                    )
                                                )
                                            except Exception as error:
                                                screenshot_failures.append(
                                                    f"{case_url}：{error}"
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
                                    )

                                    st.session_state[
                                        "generated_excel_bytes"
                                    ] = excel_result

                                    st.success("Excel生成成功")

                                    if screenshot_failures:
                                        st.warning(
                                            f"有 {len(screenshot_failures)} "
                                            "个案例截图失败，Excel其他内容仍已生成"
                                        )

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

                            with st.expander("查看 AI建议理由"):
                                for index, suggestion in enumerate(
                                    suggestions,
                                    start=1,
                                ):
                                    st.markdown(f"**实例{index}**")

                                    for factor_label, factor_name in (
                                        factor_definitions
                                    ):
                                        factor = getattr(
                                            suggestion,
                                            factor_name,
                                        )

                                        evidence = (
                                            "证据充足"
                                            if factor.evidence_sufficient
                                            else "证据不足"
                                        )

                                        st.write(
                                            f"{factor_label}："
                                            f"{factor.reason} "
                                            f"（{evidence}，"
                                            f"置信度 {factor.confidence:.0%}"
                                        )

    else:
        st.info("请上传所选车辆对应的行驶证照片")
