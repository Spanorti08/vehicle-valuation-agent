from typing import Any

from vehicle_valuation.rag_service import (
    VehicleValuationRAG,
)


REPORT_EVIDENCE_QUERIES = [
    {
        "topic": "声明和报告要求",
        "query": "资产评估报告应当包含什么内容和声明",
        "document_types": {
            "基本准则",
            "报告准则",
        },
    },
    {
        "topic": "价值类型",
        "query": "车辆市场价值的定义和选择依据",
        "document_types": {
            "基本准则",
            "指导意见",
        },
    },
    {
        "topic": "评估方法",
        "query": "车辆机器设备采用市场法选择可比案例并修正差异",
        "document_types": {
            "评估方法",
            "资产类别准则",
        },
    },
    {
        "topic": "评估程序",
        "query": "资产评估现场调查资料核查和报告编制程序",
        "document_types": {
            "基本准则",
            "程序准则",
        },
    },
    {
        "topic": "特别事项和使用限制",
        "query": "资产评估报告特别事项说明和使用限制",
        "document_types": {
            "报告准则",
            "指导意见",
        },
    },
]


def retrieve_full_report_evidence(
    rag: VehicleValuationRAG,
) -> list[dict[str, Any]]:
    """为完整评估报告检索并去重多类准则证据。"""
    evidence_by_id = {}

    for configuration in REPORT_EVIDENCE_QUERIES:
        results = rag.retrieve(
            query=configuration["query"],
            allowed_document_types=configuration[
                "document_types"
            ],
            top_k=3,
        )

        for result in results:
            chunk_id = result["chunk_id"]

            if chunk_id not in evidence_by_id:
                evidence_by_id[chunk_id] = {
                    **result,
                    "report_topics": [],
                }

            evidence_by_id[chunk_id][
                "report_topics"
            ].append(configuration["topic"])

    return list(evidence_by_id.values())