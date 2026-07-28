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
                        st.warning("发现以下资料问题：")

                        for issue in issues:
                            st.write(f"- {issue}")
                    else:
                        st.success(
                            "Excel、行驶证和现场核查信息核对通过"
                        )

                except Exception as error:
                    st.error(f"资料确认失败：{error}")

    else:
        st.info("请上传所选车辆对应的行驶证照片")

    st.subheader("车辆信息")

    st.json(
        selected_vehicle.model_dump(mode="json")
    )