from typing import TypeVar

import requests
from pydantic import BaseModel


ResponseModel = TypeVar(
    "ResponseModel",
    bound=BaseModel,
)


class OllamaProvider:
    """通过本地 Ollama 调用结构化大模型。"""

    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
    ) -> None:
        """保存模型名称和 Ollama 服务地址。"""

        self.model = model
        self.base_url = base_url

    def generate(
        self,
        prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        """调用模型并用 Pydantic 校验结构化结果。"""

        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "format": response_model.model_json_schema(),
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0,
                },
            },
            timeout=180,
        )

        response.raise_for_status()

        content = response.json()[
            "message"
        ]["content"]

        return response_model.model_validate_json(
            content
        )