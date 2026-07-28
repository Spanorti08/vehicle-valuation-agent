import re


def clean_text(text: str) -> str:
    """删除文字中的空格并统一英文字母为大写。"""

    return text.replace(" ", "").upper()


def extract_license_fields(
    ocr_lines: list[str],
) -> dict[str, str | None]:
    """从OCR文字中提取完整的行驶证字段。"""

    fields = {
        "plate_number": None,
        "vehicle_type": None,
        "owner_name": None,
        "address": None,
        "use_character": None,
        "vehicle_model": None,
        "vin": None,
        "engine_number": None,
        "registration_date": None,
        "issue_date": None,
    }

    owner_index = None
    use_character_index = None
    vin_label_index = None
    found_dates = []

    for index, original_line in enumerate(ocr_lines):
        line = clean_text(original_line)

        plate_match = re.fullmatch(
            r"[\u4e00-\u9fff][A-Z][A-Z0-9]{5}",
            line,
        )
        if plate_match:
            fields["plate_number"] = plate_match.group()

        vin_match = re.fullmatch(
            r"[A-HJ-NPR-Z0-9]{17}",
            line,
        )
        if vin_match:
            fields["vin"] = vin_match.group()

        if "公司" in original_line:
            fields["owner_name"] = original_line.strip()
            owner_index = index

        if any(
            vehicle_type in original_line
            for vehicle_type in (
                "轿车",
                "客车",
                "货车",
                "专项作业车",
            )
        ):
            fields["vehicle_type"] = original_line.strip()

        if any(
            use_character in original_line
            for use_character in (
                "非营运",
                "营运",
                "出租客运",
                "货运",
            )
        ):
            fields["use_character"] = original_line.strip()
            use_character_index = index

        if "车辆识别代号" in original_line:
            vin_label_index = index

        if (
            "发动机号码" in original_line
            and index + 1 < len(ocr_lines)
        ):
            fields["engine_number"] = clean_text(
                ocr_lines[index + 1]
            )

        date_match = re.search(
            r"\d{4}[-./]\d{2}[-./]\d{2}",
            original_line,
        )
        if date_match:
            normalized_date = (
                date_match.group()
                .replace(".", "-")
                .replace("/", "-")
            )
            found_dates.append(normalized_date)

    if len(found_dates) >= 1:
        fields["registration_date"] = found_dates[0]

    if len(found_dates) >= 2:
        fields["issue_date"] = found_dates[1]

    if owner_index is not None:
        for line in ocr_lines[owner_index + 1:]:
            if (
                ("市" in line or "省" in line)
                and ("区" in line or "县" in line)
            ):
                fields["address"] = (
                    line.removeprefix("址").strip()
                )
                break

    if (
        use_character_index is not None
        and vin_label_index is not None
    ):
        model_parts = []

        for line in ocr_lines[
            use_character_index + 1:vin_label_index
        ]:
            if any(
                ignored_text in line
                for ignored_text in (
                    "公安",
                    "交通",
                    "管理",
                    "北京市公",
                )
            ):
                continue

            model_parts.append(line.strip())

        if model_parts:
            fields["vehicle_model"] = "".join(
                model_parts[:2]
            )

    return fields