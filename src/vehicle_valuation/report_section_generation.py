from typing import Any

from vehicle_valuation.llm_provider import OllamaProvider
from vehicle_valuation.model import GroundedReportSection
from vehicle_valuation.rag_generation import (
    generate_grounded_section,
)


REPORT_SECTION_TASKS = {
    "declaration": {
        "topic": "声明和报告要求",
        "task": "撰写车辆评估报告的声明章节。",
    },
    "value_type": {
        "topic": "价值类型",
        "task": (
            "撰写市场价值类型的一般说明。"
            "不得声称已经检查法律、合同或项目资料；"
            "资料未提供时必须明确写待核实。"
        ),
    },
    "valuation_method": {
        "topic": "评估方法",
        "task": (
            "撰写车辆市场法评估方法章节，"
            "说明可比车辆选择和差异修正原则。"
            "只采用与车辆直接相关的内容，"
            "不得写入拆除、运输、安装、调试等"
            "不适用于车辆的机器设备内容。"
        ),
    },
    "valuation_process": {
        "topic": "评估程序",
        "task": (
            "说明车辆评估通常应实施的评估程序。"
            "不得声称本项目已经完成某项程序，"
            "实际完成情况后续由Python业务数据填写。"
        ),
    },
    "special_matters": {
        "topic": "特别事项和使用限制",
        "task": (
            "说明资产评估报告应披露哪些特别事项。"
            "不得假定本项目实际存在法律纠纷、"
            "专家报告、期后事项或权属瑕疵。"
            "没有项目事实支持时必须写待核实。"
        ),
    },
    "usage_restrictions": {
        "topic": "特别事项和使用限制",
        "task": "撰写车辆评估报告的使用限制章节。",
    },
}


def select_topic_evidence(
    evidence: list[dict[str, Any]],
    topic: str,
) -> list[dict[str, Any]]:
    """从整份报告证据中选出指定主题的证据。"""

    return [
        item
        for item in evidence
        if topic in item["report_topics"]
    ]


def generate_report_sections(
    evidence: list[dict[str, Any]],
    provider: OllamaProvider | None = None,
) -> dict[str, GroundedReportSection]:
    """依次生成报告中的RAG章节。"""

    if provider is None:
        provider = OllamaProvider()

    generated_sections = {}

    for field_name, configuration in (
        REPORT_SECTION_TASKS.items()
    ):
        topic_evidence = select_topic_evidence(
            evidence,
            configuration["topic"],
        )

        generated_sections[field_name] = (
            generate_grounded_section(
                task=configuration["task"],
                results=topic_evidence,
                provider=provider,
            )
        )

    return generated_sections