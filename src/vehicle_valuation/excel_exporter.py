from io import BytesIO
import re

from openpyxl import load_workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

from vehicle_valuation.model import (
    MarketListing,
    MarketListingDetail,
    ValuationRequest,
)

from vehicle_valuation.adjustment_rules import (
    AdjustmentRuleSet,
)

from openpyxl.drawing.image import Image


def write_calculation_sheet(
    workbook,
    request: ValuationRequest,
    listings: list[MarketListing],
    details: list[MarketListingDetail],
    ai_rows: list[dict],
    formula_rows: list[dict],
    rules: AdjustmentRuleSet,
) -> str:
    """动态生成条件说明、指数和修正系数表，并返回最终值单元格地址。"""

    if "计算表" not in workbook.sheetnames:
        raise ValueError("Excel中缺少“计算表”sheet")

    sheet_index = workbook.sheetnames.index("计算表")
    workbook.remove(workbook["计算表"])
    sheet = workbook.create_sheet("计算表", sheet_index)

    case_count = len(listings)

    if case_count < 3:
        raise ValueError("至少需要3个市场案例")

    detail_by_url = {
        str(detail.source_url): detail
        for detail in details
    }

    subject_used_years = (
        request.valuation_date
        - request.driving_license.registration_date
    ).days / 365.25

    subject_annual_mileage = round(
        request.inspection.actual_mileage_km
        / subject_used_years
    )

    factor_data = []

    for row in ai_rows:
        factor_data.append(
            {
                "label": row["因素"],
                "subject": row["待估车辆"],
                "values": [
                    row.get(
                        f"实例{index}（AI建议）",
                        100,
                    )
                    for index in range(
                        1,
                        case_count + 1,
                    )
                ],
                "source": "AI",
            }
        )

    for row in formula_rows:
        factor_data.append(
            {
                "label": row["因素"],
                "subject": row["待估车辆"],
                "values": [
                    row.get(
                        f"实例{index}（公式）",
                        100,
                    )
                    for index in range(
                        1,
                        case_count + 1,
                    )
                ],
                "source": "公式",
            }
        )

    block_width = case_count + 2
    condition_start = 1
    index_start = condition_start + block_width + 2
    correction_start = index_start + block_width + 2

    headers = [
        "项目",
        "待估车辆",
        *[
            f"实例{index}"
            for index in range(
                1,
                case_count + 1,
            )
        ],
    ]

    titles = [
        (
            condition_start,
            "比较实例因素条件说明表",
        ),
        (
            index_start,
            "比较因素条件指数表",
        ),
        (
            correction_start,
            "比较因素修正系数表",
        ),
    ]

    for start_column, title in titles:
        end_column = (
            start_column + block_width - 1
        )

        sheet.merge_cells(
            start_row=1,
            start_column=start_column,
            end_row=1,
            end_column=end_column,
        )

        title_cell = sheet.cell(
            row=1,
            column=start_column,
        )
        title_cell.value = title
        title_cell.font = Font(
            bold=True,
            size=14,
        )
        title_cell.alignment = Alignment(
            horizontal="center",
        )

        if start_column != correction_start:
            for offset, header in enumerate(headers):
                sheet.cell(
                    row=2,
                    column=start_column + offset,
                ).value = header

    condition_labels = [
        "车型",
        "交易单价",
        *[
            factor["label"]
            for factor in factor_data
        ],
    ]

    subject_conditions = {
        "车型": request.subject_vehicle.vehicle_name,
        "交易单价": "/",
        "交易情况": "待估",
        "年检状况": "现场核查",
        "过户情况": "未提供",
        "车辆用途": (
            request.driving_license.use_character
        ),
        "外观": request.inspection.exterior_grade,
        "内饰": request.inspection.interior_grade,
        "硬件设施状况": (
            request.inspection.hardware_grade
        ),
        "年均行驶里程": (
            subject_annual_mileage
        ),
        "上牌时间": (
            request.driving_license.registration_date
        ),
    }

    for row_offset, label in enumerate(
        condition_labels,
        start=3,
    ):
        sheet.cell(
            row=row_offset,
            column=condition_start,
        ).value = label

        sheet.cell(
            row=row_offset,
            column=condition_start + 1,
        ).value = subject_conditions.get(
            label,
            "未提供",
        )

        for case_index, listing in enumerate(
            listings,
            start=1,
        ):
            detail = detail_by_url.get(
                str(listing.source_url)
            )

            condition_summary = (
                detail.condition_summary
                if detail
                and detail.condition_summary
                else "未披露"
            )

            comparable_used_years = (
                request.valuation_date.year
                - listing.registration_year
            )

            comparable_annual_mileage = round(
                listing.mileage_km
                / comparable_used_years
            )

            case_conditions = {
                "车型": listing.vehicle_model,
                "交易单价": float(
                    listing.price_cny
                ),
                "交易情况": "公开挂牌",
                "年检状况": (
                    detail.inspection_status
                    if detail
                    and detail.inspection_status
                    else "未披露"
                ),
                "过户情况": (
                    f"{detail.transfer_count}次"
                    if detail
                    and detail.transfer_count
                    is not None
                    else "未披露"
                ),
                "车辆用途": (
                    detail.vehicle_use
                    if detail
                    and detail.vehicle_use
                    else "未披露"
                ),
                "外观": (
                    detail.exterior_condition
                    if detail
                    and detail.exterior_condition
                    else (
                        f"总体车况：{condition_summary}；"
                        "未单独披露外观细节"
                    )
                ),
                "内饰": (
                    detail.interior_condition
                    if detail
                    and detail.interior_condition
                    else (
                        f"总体车况：{condition_summary}；"
                        "未单独披露内饰细节"
                    )
                ),
                "硬件设施状况": (
                    detail.engine_transmission_condition
                    if detail
                    and detail.engine_transmission_condition
                    else (
                        f"总体车况：{condition_summary}；"
                        "未单独披露硬件细节"
                    )
                ),
                "年均行驶里程": (
                    comparable_annual_mileage
                ),
                "上牌时间": (
                    f"{listing.registration_year}年"
                ),
            }

            sheet.cell(
                row=row_offset,
                column=(
                    condition_start
                    + case_index
                    + 1
                ),
            ).value = case_conditions.get(
                label,
                "未披露",
            )

    index_labels = [
        "车型",
        "交易单价",
        *[
            factor["label"]
            for factor in factor_data
        ],
    ]

    for row_offset, label in enumerate(
        index_labels,
        start=3,
    ):
        sheet.cell(
            row=row_offset,
            column=index_start,
        ).value = label

        if label == "车型":
            subject_value = (
                request.subject_vehicle.vehicle_name
            )
        elif label == "交易单价":
            subject_value = "/"
        else:
            factor = next(
                item
                for item in factor_data
                if item["label"] == label
            )
            subject_value = factor["subject"]

        sheet.cell(
            row=row_offset,
            column=index_start + 1,
        ).value = subject_value

        for case_index, listing in enumerate(
            listings,
            start=1,
        ):
            target_cell = sheet.cell(
                row=row_offset,
                column=(
                    index_start
                    + case_index
                    + 1
                ),
            )

            if label == "车型":
                target_cell.value = (
                    listing.vehicle_model
                )
            elif label == "交易单价":
                target_cell.value = float(
                    listing.price_cny
                )
            else:
                factor = next(
                    item
                    for item in factor_data
                    if item["label"] == label
                )
                target_cell.value = factor[
                    "values"
                ][case_index - 1]

                if factor["source"] == "AI":
                    target_cell.fill = PatternFill(
                        "solid",
                        fgColor="FFF2CC",
                    )
                else:
                    target_cell.fill = PatternFill(
                        "solid",
                        fgColor="DDEBF7",
                    )

    correction_headers = [
        "项目",
        *[
            f"实例{index}"
            for index in range(
                1,
                case_count + 1,
            )
        ],
    ]

    for offset, header in enumerate(
        correction_headers
    ):
        sheet.cell(
            row=2,
            column=correction_start + offset,
        ).value = header

    correction_labels = [
        "车型",
        "交易单价",
        *[
            factor["label"]
            for factor in factor_data
        ],
        "修正后单价",
        "算术平均",
        "评估建议值",
    ]

    for row_offset, label in enumerate(
        correction_labels,
        start=3,
    ):
        sheet.cell(
            row=row_offset,
            column=correction_start,
        ).value = label

    factor_start_row = 5
    factor_end_row = (
        factor_start_row
        + len(factor_data)
        - 1
    )
    adjusted_row = factor_end_row + 1
    average_row = adjusted_row + 1
    final_row = average_row + 1

    for case_index, listing in enumerate(
        listings,
        start=1,
    ):
        correction_column = (
            correction_start + case_index
        )
        index_column = (
            index_start + case_index + 1
        )

        sheet.cell(
            row=3,
            column=correction_column,
        ).value = listing.vehicle_model

        sheet.cell(
            row=4,
            column=correction_column,
        ).value = float(listing.price_cny)

        for factor_index in range(
            len(factor_data)
        ):
            row_number = (
                factor_start_row
                + factor_index
            )

            subject_index_cell = sheet.cell(
                row=row_number,
                column=index_start + 1,
            ).coordinate

            case_index_cell = sheet.cell(
                row=row_number,
                column=index_column,
            ).coordinate

            sheet.cell(
                row=row_number,
                column=correction_column,
            ).value = (
                f"={subject_index_cell}/"
                f"{case_index_cell}"
            )

        price_cell = sheet.cell(
            row=4,
            column=correction_column,
        ).coordinate

        first_factor_cell = sheet.cell(
            row=factor_start_row,
            column=correction_column,
        ).coordinate

        last_factor_cell = sheet.cell(
            row=factor_end_row,
            column=correction_column,
        ).coordinate

        sheet.cell(
            row=adjusted_row,
            column=correction_column,
        ).value = (
            f"={price_cell}*PRODUCT("
            f"{first_factor_cell}:"
            f"{last_factor_cell})"
        )

    first_case_column = correction_start + 1
    last_case_column = (
        correction_start + case_count
    )

    first_adjusted_cell = sheet.cell(
        row=adjusted_row,
        column=first_case_column,
    ).coordinate

    last_adjusted_cell = sheet.cell(
        row=adjusted_row,
        column=last_case_column,
    ).coordinate

    average_cell = sheet.cell(
        row=average_row,
        column=first_case_column,
    )
    average_cell.value = (
        f"=AVERAGE("
        f"{first_adjusted_cell}:"
        f"{last_adjusted_cell})"
    )

    final_cell = sheet.cell(
        row=final_row,
        column=first_case_column,
    )
    final_cell.value = (
        f"=INT({average_cell.coordinate}"
        f"/100)*100"
    )

    thin_border = Border(
        left=Side(
            style="thin",
            color="D9E1F2",
        ),
        right=Side(
            style="thin",
            color="D9E1F2",
        ),
        top=Side(
            style="thin",
            color="D9E1F2",
        ),
        bottom=Side(
            style="thin",
            color="D9E1F2",
        ),
    )

    max_column = (
        correction_start + block_width - 1
    )

    for row in sheet.iter_rows(
        min_row=2,
        max_row=final_row,
        min_col=1,
        max_col=max_column,
    ):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(
                vertical="center",
                wrap_text=True,
            )

    for start_column, _ in titles:
        for column in range(
            start_column,
            start_column + block_width,
        ):
            header_cell = sheet.cell(
                row=2,
                column=column,
            )
            header_cell.font = Font(bold=True)
            header_cell.fill = PatternFill(
                "solid",
                fgColor="D9EAF7",
            )

    for column in range(
        1,
        max_column + 1,
    ):
        sheet.column_dimensions[
            get_column_letter(column)
        ].width = 16

    for row in range(3, final_row + 1):
        sheet.row_dimensions[row].height = 35

    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = None

    sheet.cell(
        row=average_row,
        column=correction_start,
    ).font = Font(bold=True)

    sheet.cell(
        row=final_row,
        column=correction_start,
    ).font = Font(bold=True)

    final_cell.font = Font(
        bold=True,
        size=14,
        color="C00000",
    )
    final_cell.fill = PatternFill(
        "solid",
        fgColor="E2F0D9",
    )

    for row in range(
        7,
        workbook["车辆"].max_row + 1,
    ):
        for column in (18, 20):
            cell = workbook["车辆"].cell(
                row=row,
                column=column,
            )

            if (
                isinstance(cell.value, str)
                and cell.value.startswith("=")
                and "计算表" in cell.value
            ):
                cell.value = None

    for row in range(7, workbook["车辆"].max_row + 1):
        asset_id = workbook["车辆"].cell(
            row=row,
            column=2,
        ).value

        if str(asset_id) == str(
            request.subject_vehicle.asset_id
        ):
            workbook["车辆"].cell(
                row=row,
                column=18,
            ).value = (
                f"='计算表'!"
                f"{final_cell.coordinate}"
            )

            workbook["车辆"].cell(
                row=row,
                column=20,
            ).value = (
                f"='计算表'!"
                f"{final_cell.coordinate}"
            )

            break

    rule_start_row = final_row + 3

    sheet.merge_cells(
        start_row=rule_start_row,
        start_column=1,
        end_row=rule_start_row,
        end_column=block_width,
    )

    rule_title = sheet.cell(
        row=rule_start_row,
        column=1,
    )
    rule_title.value = "因素修正说明"
    rule_title.font = Font(
        bold=True,
        size=13,
    )
    rule_title.fill = PatternFill(
        "solid",
        fgColor="D9EAF7",
    )

    grade_text = "、".join(
        rules.condition_grades
    )
    mileage_bounds = "、".join(
        f"{value:,}"
        for value in (
            rules.annual_mileage_rule.upper_bounds_km
        )
    )

    rule_rows = [
        (
            "外观状况",
            f"档次为{grade_text}",
            (
                "每相差一档调整"
                f"{rules.condition_rules.exterior.points_per_grade}分"
            ),
        ),
        (
            "内饰状况",
            f"档次为{grade_text}",
            (
                "每相差一档调整"
                f"{rules.condition_rules.interior.points_per_grade}分"
            ),
        ),
        (
            "硬件设施状况",
            f"档次为{grade_text}",
            (
                "每相差一档调整"
                f"{rules.condition_rules.hardware.points_per_grade}分"
            ),
        ),
        (
            "年均行驶里程",
            f"分档上限：{mileage_bounds}公里",
            (
                "每相差一档调整"
                f"{rules.annual_mileage_rule.points_per_grade}分"
            ),
        ),
        (
            "上牌时间",
            (
                "每"
                f"{rules.registration_rule.years_per_grade}"
                "年为一档"
            ),
            (
                "每相差一档调整"
                f"{rules.registration_rule.points_per_grade}分"
            ),
        ),
    ]

    for row_offset, values in enumerate(
        rule_rows,
        start=rule_start_row + 1,
    ):
        for column_offset, value in enumerate(
            values,
            start=1,
        ):
            cell = sheet.cell(
                row=row_offset,
                column=column_offset,
            )
            cell.value = value
            cell.border = thin_border
            cell.alignment = Alignment(
                vertical="center",
                wrap_text=True,
            )

    legend_row = rule_start_row + len(
        rule_rows
    ) + 2

    sheet.cell(
        row=legend_row,
        column=1,
    ).value = "颜色说明"

    sheet.cell(
        row=legend_row,
        column=2,
    ).value = "AI建议，可人工修改"
    sheet.cell(
        row=legend_row,
        column=2,
    ).fill = PatternFill(
        "solid",
        fgColor="FFF2CC",
    )

    sheet.cell(
        row=legend_row,
        column=3,
    ).value = "Python公式计算"
    sheet.cell(
        row=legend_row,
        column=3,
    ).fill = PatternFill(
        "solid",
        fgColor="DDEBF7",
    )

    return final_cell.coordinate


def build_case_sheets_excel(
    excel_bytes: bytes,
    listings: list[MarketListing],
    details: list[MarketListingDetail],
    request: ValuationRequest,
    ai_rows: list[dict],
    formula_rows: list[dict],
    rules: AdjustmentRuleSet,
    screenshots: dict[
    str,
    tuple[bytes, bytes],
],
) -> bytes:
    """生成案例sheet和计算表，并返回新的Excel文件内容。"""

    workbook = load_workbook(
        BytesIO(excel_bytes)
    )

    if "案例1" not in workbook.sheetnames:
        raise ValueError(
            "Excel中缺少“案例1”模板sheet"
        )

    template = workbook["案例1"]

    detail_by_url = {
        str(detail.source_url): detail
        for detail in details
    }

    temporary_sheets = []

    for index, listing in enumerate(
        listings,
        start=1,
    ):
        sheet = workbook.copy_worksheet(
            template
        )
        sheet.title = f"__临时案例{index}"

        detail = detail_by_url.get(
            str(listing.source_url)
        )

        condition_summary = (
            detail.condition_summary
            if detail
            and detail.condition_summary
            else "公开页面未提供详细车况"
        )

        sheet["B1"] = str(
            listing.source_url
        )
        sheet["B13"] = listing.vehicle_model
        sheet["C13"] = "瓜子二手车客服"
        sheet["D13"] = listing.mileage_km
        sheet["E13"] = (
            f"{listing.registration_year}年"
        )
        sheet["F13"] = (
            f"公开页面总体车况："
            f"{condition_summary}；"
            "未单独披露外观细节"
        )
        sheet["G13"] = (
            f"公开页面总体车况："
            f"{condition_summary}；"
            "未单独披露内饰细节"
        )
        sheet["H13"] = (
            f"公开页面总体车况："
            f"{condition_summary}；"
            "未单独披露硬件细节"
        )
        sheet["I13"] = float(
            listing.price_cny
        )
        sheet["J13"] = (
            "公开挂牌价，未经电话询价确认"
        )

        case_screenshots = screenshots.get(
            str(listing.source_url)
        )

        if case_screenshots is not None:
            vehicle_bytes, detail_bytes = (
                case_screenshots
            )

            vehicle_image = Image(
                BytesIO(vehicle_bytes)
            )
            vehicle_image.width = 850
            vehicle_image.height = 435
            sheet.add_image(
                vehicle_image,
                "B2",
            )

            detail_image = Image(
                BytesIO(detail_bytes)
            )
            detail_image.width = 850
            detail_image.height = 735
            sheet.add_image(
                detail_image,
                "B15",
            )

            for row_number in range(2, 12):
                sheet.row_dimensions[
                    row_number
                ].height = 33

            for row_number in range(15, 29):
                sheet.row_dimensions[
                    row_number
                ].height = 40

        temporary_sheets.append(sheet)

    for sheet in list(
        workbook.worksheets
    ):
        if re.fullmatch(
            r"案例\d+",
            sheet.title,
        ):
            workbook.remove(sheet)

    for index, sheet in enumerate(
        temporary_sheets,
        start=1,
    ):
        sheet.title = f"案例{index}"

    write_calculation_sheet(
        workbook=workbook,
        request=request,
        listings=listings,
        details=details,
        ai_rows=ai_rows,
        formula_rows=formula_rows,
        rules=rules,
    )

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"

    output = BytesIO()
    workbook.save(output)

    return output.getvalue()