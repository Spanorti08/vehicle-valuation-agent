import cv2
import numpy as np
from pydantic import BaseModel, Field
from rapidocr import RapidOCR


OCR_ENGINE = RapidOCR()


class OCRTextLine(BaseModel):
    """一行 OCR 原文及模型置信度。"""

    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


def recognize_license_lines(
    image_bytes: bytes,
) -> list[OCRTextLine]:
    """识别行驶证并保留逐行置信度。"""

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8,
    )
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("无法读取行驶证图片")

    result = OCR_ENGINE(image)
    if result.txts is None:
        return []

    scores = (
        list(result.scores)
        if result.scores is not None
        else []
    )
    return [
        OCRTextLine(
            text=str(text),
            confidence=(
                float(scores[index])
                if index < len(scores)
                else 0.0
            ),
        )
        for index, text in enumerate(result.txts)
        if str(text).strip()
    ]


def recognize_license_text(
    image_bytes: bytes,
) -> list[str]:
    """兼容旧调用，仅返回行驶证 OCR 文本。"""

    return [
        line.text
        for line in recognize_license_lines(image_bytes)
    ]
