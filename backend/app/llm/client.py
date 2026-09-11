"""LLM 客户端."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.llm.config import resolve_llm_config


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage


class LLMClient:
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def close(self) -> None:
        """关闭底层连接池，避免 GC 清理时报错."""
        pass


class MockLLMClient(LLMClient):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        user = messages[-1]["content"] if messages else ""
        if "命格" in user or "八字" in user or "chart" in user.lower():
            content = json.dumps({
                "vernacular": "综合来看，五行不缺。建议优先考虑含火属性的名字，其次考虑含木属性的名字。",
                "xiyongshen": {"primary": ["火"], "secondary": ["木"], "avoid": []},
                "reasoning_chain": ["丙火生于冬季", "宜火调候", "木生火为次选"],
                "professional": "",
            }, ensure_ascii=False)
        elif "组名" in user or "citation" in user.lower() or "pair_hints" in user:
            content = json.dumps({"candidates": []}, ensure_ascii=False)
        else:
            content = json.dumps({"pass": True, "reasons": []}, ensure_ascii=False)
        return LLMResponse(content=content, model=model or "mock", usage=TokenUsage())


class OpenAICompatibleClient(LLMClient):
    def __init__(self) -> None:
        cfg = resolve_llm_config()
        self._client = AsyncOpenAI(
            api_key=cfg["api_key"] or "sk-placeholder",
            base_url=cfg["api_base"],
            timeout=cfg["timeout"],
            max_retries=cfg["max_retries"],
        )
        self._default_model = cfg["model"]
        self._temperature = cfg["temperature"]

    async def close(self) -> None:
        """关闭 AsyncOpenAI 底层 httpx 连接池，避免 GC 时 aclose() 报错."""
        try:
            await self._client.close()
        except Exception:
            pass

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
        resp = await self._client.chat.completions.create(**kwargs)
        usage = resp.usage
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=resp.model,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ),
        )


def get_llm_client() -> LLMClient:
    cfg = resolve_llm_config()
    if cfg["mock"] or not cfg["api_key"]:
        return MockLLMClient()
    return OpenAICompatibleClient()
