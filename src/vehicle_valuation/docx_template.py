from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt


# 宋体是正式中文报告的常用字体，并在主要 Windows Word 环境中可用；
# macOS Word 或 LibreOffice 会按系统字体回退规则替换显示。
CHINESE_FONT = "SimSun"


def replace_paragraph_placeholders(
    paragraph,
    replacements: dict[str, str],
) -> None:
    """替换一个Word段落中的占位符。"""

    original_text = paragraph.text
    new_text = original_text

    for placeholder, value in replacements.items():
        new_text = new_text.replace(
            placeholder,
            value,
        )

    if new_text == original_text:
        return

    paragraph_blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n|\n", new_text)
        if block.strip()
    ]
    first_block = (
        paragraph_blocks[0]
        if paragraph_blocks
        else new_text
    )

    if paragraph.runs:
        paragraph.runs[0].text = first_block

        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(first_block)

    if len(paragraph_blocks) > 1:
        previous_element = paragraph._p
        reference_properties = (
            deepcopy(paragraph.runs[0]._element.rPr)
            if paragraph.runs
            else None
        )

        for block in paragraph_blocks[1:]:
            next_paragraph = OxmlElement("w:p")

            if paragraph._p.pPr is not None:
                next_paragraph.append(
                    deepcopy(paragraph._p.pPr)
                )

            next_run = OxmlElement("w:r")

            if reference_properties is not None:
                next_run.append(
                    deepcopy(reference_properties)
                )

            next_text = OxmlElement("w:t")
            next_text.set(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve",
            )
            next_text.text = block
            next_run.append(next_text)
            next_paragraph.append(next_run)
            previous_element.addnext(next_paragraph)
            previous_element = next_paragraph

    if len(new_text) >= 120:
        paragraph.paragraph_format.line_spacing = 1.5
        paragraph.paragraph_format.space_after = Pt(6)


def normalize_chinese_fonts_in_container(container) -> None:
    """把模板中的专用中文字体替换为Word常用宋体。"""

    for paragraph in container.paragraphs:
        for run in paragraph.runs:
            run.font.name = CHINESE_FONT
            run._element.get_or_add_rPr().rFonts.set(
                qn("w:eastAsia"),
                CHINESE_FONT,
            )

    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                normalize_chinese_fonts_in_container(cell)


def normalize_document_fonts(document) -> None:
    """统一正文、样式、页眉和页脚中的中文字体。"""

    for style in document.styles:
        if not hasattr(style, "font"):
            continue

        style.font.name = CHINESE_FONT
        properties = style.element.get_or_add_rPr()
        properties.get_or_add_rFonts().set(
            qn("w:eastAsia"),
            CHINESE_FONT,
        )

    normalize_chinese_fonts_in_container(document)

    for section in document.sections:
        normalize_chinese_fonts_in_container(
            section.header
        )
        normalize_chinese_fonts_in_container(
            section.footer
        )


def replace_container_placeholders(
    container,
    replacements: dict[str, str],
) -> None:
    """替换正文、页眉、页脚和表格中的占位符。"""

    for paragraph in container.paragraphs:
        replace_paragraph_placeholders(
            paragraph,
            replacements,
        )

    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                replace_container_placeholders(
                    cell,
                    replacements,
                )


def highlight_pending_text_in_paragraph(paragraph) -> None:
    """将段落中的待填写标记设为黄色高亮。"""

    pending_pattern = re.compile(r"(待补充|待编号)")

    for run in list(paragraph.runs):
        if pending_pattern.search(run.text) is None:
            continue

        text_parts = pending_pattern.split(run.text)
        run.text = text_parts[0]
        reference_properties = deepcopy(run._element.rPr)

        if reference_properties is not None:
            for highlight in reference_properties.findall(
                qn("w:highlight")
            ):
                reference_properties.remove(highlight)

        for index, text_part in enumerate(
            text_parts[1:],
            start=1,
        ):
            next_run = paragraph.add_run(text_part)

            if reference_properties is not None:
                next_run._element.insert(
                    0,
                    deepcopy(reference_properties),
                )

            if index % 2 == 1:
                next_run.font.highlight_color = (
                    WD_COLOR_INDEX.YELLOW
                )


def highlight_pending_text_in_container(container) -> None:
    """高亮正文、页眉、页脚和表格中的所有待补充文字。"""

    for paragraph in container.paragraphs:
        highlight_pending_text_in_paragraph(paragraph)

    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                highlight_pending_text_in_container(cell)


def request_field_update_on_open(document) -> None:
    """要求Word打开文件时更新目录和其他域。"""

    settings = document.settings.element
    update_fields = settings.find(qn("w:updateFields"))

    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)

    update_fields.set(qn("w:val"), "true")


def remove_stale_toc_page_numbers(document) -> None:
    """移除模板目录中缓存的旧页码，避免初稿显示错误页数。"""

    toc_heading_found = False

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if re.fullmatch(r"目\s*录", text):
            toc_heading_found = True
            continue

        if not toc_heading_found:
            continue

        if text in {"声   明", "摘   要", "资 产 评 估 报 告"}:
            break

        # Word 模板中的目录项目以制表符连接标题、点线和旧页码。
        # 这里只保留标题；Word 打开文件后仍会根据 updateFields 更新正式目录。
        if "\t" in paragraph.text:
            title = paragraph.text.split("\t", maxsplit=1)[0].strip()

            if title:
                paragraph.text = title


def remove_empty_numbered_paragraphs(document) -> None:
    """删除模板中清空正文后遗留的空编号段落。"""

    for paragraph in list(document.paragraphs):
        if paragraph.text.strip():
            continue

        properties = paragraph._p.pPr

        if properties is None or properties.numPr is None:
            continue

        paragraph._p.getparent().remove(paragraph._p)


def fill_docx_template(
    template_path: Path,
    replacements: dict[str, str],
) -> bytes:
    """读取Word模板并返回填充完成的DOCX文件。"""

    document = Document(template_path)

    replace_container_placeholders(
        document,
        replacements,
    )

    for section in document.sections:
        replace_container_placeholders(
            section.header,
            replacements,
        )
        replace_container_placeholders(
            section.footer,
            replacements,
        )

    normalize_document_fonts(document)

    highlight_pending_text_in_container(document)

    for section in document.sections:
        highlight_pending_text_in_container(
            section.header,
        )
        highlight_pending_text_in_container(
            section.footer,
        )

    remove_stale_toc_page_numbers(document)
    remove_empty_numbered_paragraphs(document)
    request_field_update_on_open(document)

    output = BytesIO()
    document.save(output)

    return output.getvalue()
