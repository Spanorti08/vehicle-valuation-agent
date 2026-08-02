import json
import re
from pathlib import Path

from vehicle_valuation.model import VehicleModelMapping


LEGAL_MODEL_PATTERN = re.compile(
    r"[A-Z]{1,4}\d[A-Z0-9.-]*"
)


def normalize_legal_model(value: str) -> str:
    """删除法定型号中的空格和标点并统一为大写。"""

    return re.sub(
        r"[^A-Z0-9]",
        "",
        value.upper(),
    )


def extract_legal_model(vehicle_model: str) -> str:
    """从完整品牌型号中提取类似BJ7204的法定型号。"""

    match = LEGAL_MODEL_PATTERN.search(
        vehicle_model.upper()
    )

    if match is None:
        raise ValueError(
            f"无法提取车辆法定型号：{vehicle_model}"
        )

    return normalize_legal_model(match.group())


def load_model_mapping_knowledge_base(
    knowledge_path: Path,
) -> list[VehicleModelMapping]:
    """加载并验证公开车型映射知识库。"""

    data = json.loads(
        knowledge_path.read_text(encoding="utf-8")
    )

    return [
        VehicleModelMapping.model_validate(item)
        for item in data
    ]


def retrieve_model_mapping_evidence(
    mappings: list[VehicleModelMapping],
    legal_model: str,
) -> list[VehicleModelMapping]:
    """检索与指定法定型号完全匹配的公开证据。"""

    normalized_query = normalize_legal_model(
        legal_model
    )

    return [
        mapping
        for mapping in mappings
        if normalize_legal_model(
            mapping.legal_model
        ) == normalized_query
    ]