"""Small fixed-host OpenAI Responses API adapter with bounded I/O."""

from __future__ import annotations

import http.client
import json
import ssl
from typing import Any

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 60


class ProviderRequestError(RuntimeError):
    """A sanitized provider failure that never includes the request or key."""


class OpenAIResponsesAdapter:
    """Send one already-approved JSON body to the fixed OpenAI HTTPS endpoint."""

    def __init__(self, *, connection_factory: Any = http.client.HTTPSConnection) -> None:
        self._connection_factory = connection_factory

    def generate(self, payload: bytes, api_key: str) -> str:
        _validate_request(payload, api_key)
        connection = self._connection_factory(
            "api.openai.com",
            timeout=REQUEST_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        try:
            connection.request(
                "POST",
                "/v1/responses",
                body=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ProviderRequestError("Ответ OpenAI превышает ограничение размера 2 МиБ.")
            if response.status < 200 or response.status >= 300:
                raise ProviderRequestError(
                    f"OpenAI вернула ошибку (HTTP {response.status}). Проверьте ключ и доступность модели."
                )
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ProviderRequestError("OpenAI вернула ответ в неизвестном формате.") from error
            answer = _response_text(data)
            if not answer.strip():
                raise ProviderRequestError("В ответе OpenAI нет текста.")
            return answer
        except (OSError, TimeoutError, http.client.HTTPException, ssl.SSLError) as error:
            raise ProviderRequestError("Не удалось связаться с OpenAI. Проверьте интернет-подключение.") from error
        finally:
            connection.close()


def _validate_request(payload: bytes, api_key: str) -> None:
    if not isinstance(api_key, str) or not api_key.strip() or "\r" in api_key or "\n" in api_key:
        raise ProviderRequestError("Ключ OpenAI не настроен.")
    if not isinstance(payload, bytes) or not payload or len(payload) > 20 * 1024 * 1024:
        raise ProviderRequestError("Подготовленный запрос OpenAI имеет недопустимый размер.")
    try:
        request = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderRequestError("Подготовленный запрос OpenAI имеет неверный формат.") from error
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("model"), str)
        or not isinstance(request.get("instructions"), str)
        or not isinstance(request.get("input"), str)
        or request.get("store") is not False
        or type(request.get("max_output_tokens")) is not int
        or not 1 <= request["max_output_tokens"] <= 4_000
    ):
        raise ProviderRequestError("Запрос OpenAI не прошёл проверку допустимых параметров.")


def _response_text(data: object) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("output"), list):
        raise ProviderRequestError("OpenAI вернула ответ в неизвестном формате.")
    blocks: list[str] = []
    for item in data["output"]:
        if not isinstance(item, dict) or not isinstance(item.get("content"), list):
            continue
        for block in item["content"]:
            if (
                isinstance(block, dict)
                and block.get("type") == "output_text"
                and isinstance(block.get("text"), str)
            ):
                blocks.append(block["text"])
    return "\n".join(blocks)
