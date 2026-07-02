# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI-compatible LLM helper with structured outputs."""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from isaaclab_arena.agentic_environment_generation.agent_utils import build_strict_schema, extract_response_text, ping

# TODO(qianl): This is currently Nvidia internal. Switch to public endpoint.
DEFAULT_BASE_URL = "https://inference-api.nvidia.com"
DEFAULT_MODEL = "nvidia/deepseek-ai/deepseek-v4-flash"


class BaseLLMAgent:
    """Shared OpenAI-compatible client for structured inference."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        *,
        client: OpenAI | None = None,
        validate_connection: bool = True,
    ) -> None:
        """Configure the client.

        Args:
            api_key: API token. Falls back to ``NV_API_KEY``.
            model: Model identifier at the inference endpoint.
            base_url: OpenAI-compatible inference endpoint.
            client: Optional pre-constructed OpenAI client to reuse.
            validate_connection: When ``True``, ping the endpoint on construction.
        """
        self.api_key = api_key or os.getenv("NV_API_KEY")
        assert self.api_key, "API key required: set NV_API_KEY or pass api_key."
        self.model = model or DEFAULT_MODEL
        base_url = base_url or DEFAULT_BASE_URL
        self.client = client or OpenAI(api_key=self.api_key, base_url=base_url)
        if validate_connection:
            ping(self.client, self.model)

    def infer_structured(
        self,
        model_cls: type[BaseModel],
        messages: list[dict[str, Any]],
        *,
        schema_name: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> tuple[BaseModel, str]:
        """Run one structured-output completion and validate against ``model_cls``.

        Returns:
            A ``(parsed_model, raw_json_text)`` tuple.
        """
        schema = build_strict_schema(model_cls)
        schema_name = schema_name or model_cls.__name__
        last_exc: Exception | None = None
        for attempt in range(1 + max_retries):
            if attempt > 0:
                print(f"[{schema_name}] retry {attempt}/{max_retries} after: {last_exc}", flush=True)
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "strict": True,
                            "schema": schema,
                        },
                    },
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = self._extract_message_text(resp)
                data = json.loads(text, strict=False)
                return model_cls.model_validate(data), text
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(
            f"Model {self.model!r} failed {schema_name} after {1 + max_retries} attempts. Last error: {last_exc}"
        ) from last_exc

    @staticmethod
    def _extract_message_text(resp: Any) -> str:
        choices = getattr(resp, "choices", None) or []
        if not choices:
            raise ValueError(
                "Model returned HTTP 200 with no choices "
                "(content filter / guardrail / rate-limit response with empty body)."
            )
        text, route = extract_response_text(choices[0].message)
        assert route != "empty", (
            "Model returned an empty structured-outputs envelope. "
            "Verify the endpoint/model supports response_format=json_schema."
        )
        return text
