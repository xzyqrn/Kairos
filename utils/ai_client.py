from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import aiofiles
import aiohttp

from utils.providers import OPENAI_COMPAT_BASE_URLS, get_provider

log = logging.getLogger("kairos.ai_client")

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
AI_CONFIG_PATH = DATA_DIR / "ai_config.json"
LANG_PREFS_PATH = DATA_DIR / "lang_prefs.json"

SUPPORTED_PROVIDERS = {"claude", "gemini", "openai", "openrouter", "groq"}
SUPPORTED_TONES = {"warm", "formal", "balanced"}

OPENAI_COMPAT_BASE_URLS = OPENAI_COMPAT_BASE_URLS  # re-export for backward compat

TONE_SYSTEM_PROMPTS = {
    "warm": (
        "You are Kairos, a warm and friendly Christian youth bot. "
        "Speak like a caring older sibling in faith."
    ),
    "formal": (
        "You are Kairos, a reverent and knowledgeable Christian assistant. "
        "Speak with spiritual depth and respect."
    ),
    "balanced": (
        "You are Kairos, a biblically-grounded Christian youth bot. "
        "Be encouraging, clear, and relatable to young people aged 13-25."
    ),
}

SAFETY_APPEND = (
    "You never give harmful advice. Always point back to Scripture when relevant. "
    "Never produce content inappropriate for ages 13+."
)

# Maximum tokens to request from any AI provider.
# Keeps responses brief and predictable; the cog layer trims to char limits.
MAX_TOKENS = 600

# Retry configuration for transient provider errors.
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles on each successive attempt
_TRANSIENT_KEYWORDS = frozenset({"502", "503", "504", "529", "overloaded", "timeout", "connection"})


class AIClient:
    def __init__(self) -> None:
        self._config_lock = asyncio.Lock()

    async def _ensure_json_file(self, path: Path, default_payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        async with aiofiles.open(path, "w", encoding="utf-8") as target:
            await target.write(json.dumps(default_payload, indent=2))

    async def _read_json(self, path: Path, default_payload: Any) -> Any:
        await self._ensure_json_file(path, default_payload)

        async with aiofiles.open(path, encoding="utf-8") as source:
            raw = (await source.read()).strip()

        if not raw:
            return default_payload

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in {path.name}: {exc}") from exc

    async def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as target:
            await target.write(json.dumps(payload, indent=2))

    async def get_all_configs(self) -> dict[str, dict[str, Any]]:
        data = await self._read_json(AI_CONFIG_PATH, {})
        if not isinstance(data, dict):
            raise RuntimeError("ai_config.json must contain an object at the root")
        return data

    @staticmethod
    def _guild_key(guild_id: str) -> str:
        clean = str(guild_id).strip()
        if clean.startswith("guild_"):
            return clean
        return f"guild_{clean}"

    async def get_guild_config(self, guild_id: str) -> dict[str, Any] | None:
        configs = await self.get_all_configs()
        guild_key = self._guild_key(guild_id)
        return configs.get(guild_key) or configs.get(str(guild_id))

    async def upsert_guild_config(
        self,
        guild_id: str,
        provider: str,
        model: str,
        api_key: str,
        set_by: str,
        tone: str = "balanced",
    ) -> dict[str, Any]:
        provider_key = provider.strip().lower()
        tone_key = tone.strip().lower()

        if provider_key not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{provider}'. Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
            )
        if tone_key not in SUPPORTED_TONES:
            raise ValueError(f"Unsupported tone '{tone}'. Supported: warm, formal, balanced")
        if not model.strip():
            raise ValueError("Model name cannot be empty")
        if not api_key.strip():
            raise ValueError("API key cannot be empty")

        guild_key = self._guild_key(guild_id)
        config_payload = {
            "provider": provider_key,
            "model": model.strip(),
            "api_key": api_key.strip(),
            "tone": tone_key,
            "set_by": str(set_by),
            "set_at": dt.date.today().isoformat(),
        }

        async with self._config_lock:
            configs = await self.get_all_configs()
            configs[guild_key] = config_payload
            await self._write_json(AI_CONFIG_PATH, configs)

        return config_payload

    async def clear_guild_config(self, guild_id: str) -> bool:
        guild_key = self._guild_key(guild_id)
        legacy_key = str(guild_id)
        async with self._config_lock:
            configs = await self.get_all_configs()
            existed = guild_key in configs or legacy_key in configs
            if existed:
                configs.pop(guild_key, None)
                configs.pop(legacy_key, None)
                await self._write_json(AI_CONFIG_PATH, configs)
            return existed

    async def set_tone(self, guild_id: str, tone: str) -> dict[str, Any]:
        tone_key = tone.strip().lower()
        if tone_key not in SUPPORTED_TONES:
            raise ValueError("Tone must be one of: warm, formal, balanced")

        guild_key = self._guild_key(guild_id)
        legacy_key = str(guild_id)
        async with self._config_lock:
            configs = await self.get_all_configs()
            config = configs.get(guild_key) or configs.get(legacy_key)
            if not config:
                raise RuntimeError("AI is not configured for this server. Run /ai_setup first.")

            config["tone"] = tone_key
            config["set_at"] = dt.date.today().isoformat()
            configs[guild_key] = config
            await self._write_json(AI_CONFIG_PATH, configs)

        return config

    async def get_user_language(self, user_id: str) -> str | None:
        prefs = await self._read_json(LANG_PREFS_PATH, {})
        if not isinstance(prefs, dict):
            raise RuntimeError("lang_prefs.json must contain an object at the root")
        value = prefs.get(str(user_id))
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    async def get_system_prompt(self, tone: str, user_id: str | None = None) -> str:
        tone_key = tone if tone in SUPPORTED_TONES else "balanced"
        system_prompt = f"{TONE_SYSTEM_PROMPTS[tone_key]} {SAFETY_APPEND}"

        if user_id:
            language = await self.get_user_language(str(user_id))
            if language:
                system_prompt = f"{system_prompt} Respond in {language}."

        return system_prompt

    @staticmethod
    async def _with_retry(coro_fn, *args, **kwargs) -> str:
        """
        Call *coro_fn* with *args*/*kwargs*, retrying up to ``_RETRY_ATTEMPTS``
        times on network errors or known transient HTTP status codes.
        Non-transient ``RuntimeError``s are re-raised immediately.
        """
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                return await coro_fn(*args, **kwargs)
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_exc = exc
            except RuntimeError as exc:
                if any(k in str(exc).lower() for k in _TRANSIENT_KEYWORDS):
                    last_exc = exc
                else:
                    raise
            if attempt < _RETRY_ATTEMPTS - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                log.debug(
                    "Attempt %d/%d failed (%s) — retrying in %.1fs",
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                    last_exc,
                    delay,
                )
                await asyncio.sleep(delay)
        raise last_exc

    async def generate_response(self, prompt: str, guild_id: str, user_id: str | None = None) -> str:
        user_prompt = prompt.strip()
        if not user_prompt:
            raise ValueError("Prompt cannot be empty")

        config = await self.get_guild_config(str(guild_id))
        if not config:
            raise RuntimeError("AI is not configured for this server. Ask an admin to run /ai_setup.")

        provider = str(config.get("provider", "")).lower().strip()
        model = str(config.get("model", "")).strip()
        api_key = str(config.get("api_key", "")).strip()
        tone = str(config.get("tone", "balanced")).lower().strip() or "balanced"

        if provider not in SUPPORTED_PROVIDERS:
            raise RuntimeError(
                f"Configured provider '{provider}' is not supported. Re-run /ai_setup with a valid provider."
            )
        if not model:
            raise RuntimeError("Configured AI model is empty. Re-run /ai_setup.")
        if not api_key:
            raise RuntimeError("Configured API key is empty. Re-run /ai_setup.")

        system_prompt = await self.get_system_prompt(tone=tone, user_id=user_id)

        try:
            provider_impl = get_provider(provider)
            return await self._with_retry(
                provider_impl.generate,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                prompt=user_prompt,
            )
        except Exception as exc:
            raise RuntimeError(f"{provider} request failed: {exc}") from exc


def mask_api_key(api_key: str) -> str:
    clean = api_key.strip()
    if not clean:
        return "(empty)"
    
    # If key is very short, show very little
    if len(clean) <= 4:
        return f"{clean[0]}..." if len(clean) > 0 else "..."
    
    # Otherwise, show first 4 characters and some stars
    show = min(4, len(clean) // 3)
    if show < 4 and len(clean) > 8:
        show = 4
    
    return f"{clean[:show]}****{clean[-2:] if len(clean) > 8 else ''}"


ai_client = AIClient()
