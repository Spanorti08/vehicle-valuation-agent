import cv2
import numpy as np
from rapidocr import RapidOCR


OCR_ENGINE = RapidOCR()


def recognize_license_text(
    image_bytes: bytes,
) -> list[str]:
    """识别行驶证图片中的全部文字行。"""

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8,
    )

    image = cv2.imdecode(
        image_array,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError("无法读取行驶证图片")

    result = OCR_ENGINE(image)

    if result.txts is None:
        return []

    return list(result.txts)