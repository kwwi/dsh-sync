"""Parse JSON from LLM responses (may include markdown fences)."""

from __future__ import annotations

import json
import re


def parse_llm_json(content: str, *, fallback: dict | None = None) -> dict:
    text = (content or "").strip()
    if not text:
        if fallback is not None:
            return fallback
        raise ValueError("empty LLM response")

    # 1) 尝试直接解析（含 markdown fence 处理）
    cleaned = text
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2) 尝试从文本中提取 JSON 数组或对象（LLM 可能在前后加了说明文字）
    # 找最外层 [ ... ] 或 { ... }
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue

    # 3) 尝试提取 markdown fence 内的内容
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    if fallback is not None:
        return fallback
    raise
