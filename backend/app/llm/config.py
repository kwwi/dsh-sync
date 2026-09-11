"""LLM 配置."""

from pydantic import SecretStr, model_validator

from app.config import Settings, get_settings

PROVIDER_PRESETS = {
    "deepseek": {"api_base": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"},
    "openai": {"api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "dashscope": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
}


def resolve_llm_config(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    preset = PROVIDER_PRESETS.get(s.llm_provider, {})
    api_base = s.llm_api_base
    model = s.llm_model
    if s.llm_provider != "custom" and preset:
        if api_base == "https://api.deepseek.com/v1" and s.llm_provider != "deepseek":
            pass
        elif s.llm_provider in PROVIDER_PRESETS:
            api_base = preset["api_base"]
            if s.llm_model in ("deepseek-chat", "deepseek-v4-flash") and s.llm_provider != "deepseek":
                model = preset["model"]
    return {
        "mock": s.llm_mock,
        "provider": s.llm_provider,
        "api_base": api_base,
        "api_key": s.llm_api_key.get_secret_value(),
        "model": model,
        "model_fate": s.llm_model_fate or model,
        "model_compose": s.llm_model_compose or model,
        "model_qa": s.llm_model_qa or model,
        "model_curator": s.llm_model_curator or s.llm_model_compose or model,
        "model_wuxing": s.llm_model_wuxing or s.llm_model_compose or model,
        "timeout": s.llm_timeout_seconds,
        "max_retries": s.llm_max_retries,
        "temperature": s.llm_temperature,
    }
