"""
ai_pool.py - Multi-provider API key pool with round-robin rotation and fallback.

Supports:
  - Multiple Gemini keys: GEMINI_API_KEY, GEMINI_API_KEY_1 .. GEMINI_API_KEY_N
  - Multiple Groq keys:   GROQ_API_KEY_1 .. GROQ_API_KEY_N
  - Round-robin within each provider group
  - HTTP 429 triggers exponential backoff and rotation to next key
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderKey:
    provider: str
    key: str
    index: int
    backoff_until: float = field(default=0.0)
    fail_count: int = field(default=0)


class AIKeyPool:
    """Thread-safe round-robin API key pool supporting Gemini and Groq."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: list[ProviderKey] = []
        self._cursor = 0
        self._gemini_cursor = 0
        self._groq_cursor = 0
        self._load_keys()

    def _load_keys(self) -> None:
        keys: list[ProviderKey] = []
        idx = 0

        primary = os.environ.get("GEMINI_API_KEY", "").strip()
        if primary:
            keys.append(ProviderKey(provider="gemini", key=primary, index=idx))
            idx += 1

        i = 1
        while True:
            val = os.environ.get(f"GEMINI_API_KEY_{i}", "").strip()
            if not val:
                break
            keys.append(ProviderKey(provider="gemini", key=val, index=idx))
            idx += 1
            i += 1

        i = 1
        while True:
            val = os.environ.get(f"GROQ_API_KEY_{i}", "").strip()
            if not val:
                break
            keys.append(ProviderKey(provider="groq", key=val, index=idx))
            idx += 1
            i += 1

        self._keys = keys
        if keys:
            providers = {}
            for k in keys:
                providers[k.provider] = providers.get(k.provider, 0) + 1
            logger.info("AI key pool loaded: %s", providers)
        else:
            logger.warning("AI key pool: no API keys found")

    def available(self) -> bool:
        return bool(self._keys)

    def _next_available(self) -> Optional[ProviderKey]:
        """
        Return the next available key using round-robin rotation with
        Gemini-first priority.

        Gemini keys are iterated in round-robin (using _cursor within the
        Gemini key list). Groq keys are only tried when all Gemini keys are
        in backoff and are themselves iterated in round-robin.
        """
        now = time.monotonic()
        gemini_keys = [k for k in self._keys if k.provider == "gemini"]
        groq_keys = [k for k in self._keys if k.provider == "groq"]

        n_gemini = len(gemini_keys)
        if n_gemini:
            for i in range(n_gemini):
                idx = (self._gemini_cursor + i) % n_gemini
                candidate = gemini_keys[idx]
                if candidate.backoff_until <= now:
                    self._gemini_cursor = (idx + 1) % n_gemini
                    return candidate

        n_groq = len(groq_keys)
        if n_groq:
            for i in range(n_groq):
                idx = (self._groq_cursor + i) % n_groq
                candidate = groq_keys[idx]
                if candidate.backoff_until <= now:
                    self._groq_cursor = (idx + 1) % n_groq
                    return candidate

        return None

    def mark_rate_limited(self, pk: ProviderKey, is_rate_limit: bool = True) -> float:
        with self._lock:
            if is_rate_limit:
                delay = min(60.0, 2.0 ** pk.fail_count)
            else:
                delay = min(30.0, 1.0 * (2 ** pk.fail_count))
            pk.fail_count += 1
            pk.backoff_until = time.monotonic() + delay
            logger.warning(
                "Key %s/%d %s; backoff %.1fs (fail_count=%d)",
                pk.provider, pk.index,
                "rate-limited" if is_rate_limit else "transient error",
                delay, pk.fail_count
            )
            return delay

    def mark_success(self, pk: ProviderKey) -> None:
        with self._lock:
            pk.fail_count = max(0, pk.fail_count - 1)
            pk.backoff_until = 0.0

    def call_with_retry(
        self,
        prompt: str,
        *,
        max_attempts: int = 6,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """
        Call the AI with the prompt. Tries keys in round-robin order.
        Returns the text response.
        Raises RuntimeError if all keys fail.
        """
        if not self._keys:
            raise RuntimeError("No AI API keys configured")

        last_error: Exception = RuntimeError("No keys tried")
        tried: set[int] = set()

        for attempt in range(max_attempts):
            with self._lock:
                pk = self._next_available()
            if pk is None:
                soonest = min(k.backoff_until for k in self._keys)
                wait = max(0.0, soonest - time.monotonic())
                logger.info("All keys in backoff; waiting %.1fs", wait)
                time.sleep(wait + 0.5)
                with self._lock:
                    pk = self._next_available()
            if pk is None:
                continue

            if pk.index in tried and len(tried) >= len(self._keys):
                break
            tried.add(pk.index)

            try:
                if pk.provider == "gemini":
                    result = self._call_gemini(pk, prompt, system=system, json_mode=json_mode)
                elif pk.provider == "groq":
                    result = self._call_groq(pk, prompt, system=system)
                else:
                    raise ValueError(f"Unknown provider: {pk.provider}")

                self.mark_success(pk)
                return result

            except Exception as exc:
                err_str = str(exc).lower()
                if "429" in err_str or "rate" in err_str or "quota" in err_str or "resource exhausted" in err_str:
                    delay = self.mark_rate_limited(pk, is_rate_limit=True)
                    logger.info("Rate-limited on attempt %d; sleeping %.1fs", attempt, delay)
                    time.sleep(min(delay, 5.0))
                else:
                    delay = self.mark_rate_limited(pk, is_rate_limit=False)
                    logger.warning("AI call failed (transient, attempt %d): %s", attempt, exc)
                    time.sleep(min(delay, 2.0))
                last_error = exc

        raise RuntimeError(f"All AI call attempts exhausted. Last error: {last_error}")

    def _call_gemini(
        self,
        pk: ProviderKey,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=pk.key)

        config_kwargs: dict = {}
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        contents = []
        if system:
            contents.append(types.Content(role="user", parts=[types.Part(text=f"[SYSTEM]: {system}\n\n{prompt}")]))
        else:
            contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))

        _GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash"]
        last_exc: Exception | None = None
        for model in _GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=8192,
                        **config_kwargs,
                    ),
                )
                return response.text or ""
            except Exception as exc:
                err_str = str(exc).lower()
                if "not found" in err_str or "404" in err_str or "deprecated" in err_str:
                    last_exc = exc
                    continue
                raise
        raise last_exc or RuntimeError("All Gemini models failed")

    def _call_groq(
        self,
        pk: ProviderKey,
        prompt: str,
        *,
        system: str | None = None,
    ) -> str:
        import groq as groq_sdk

        client = groq_sdk.Groq(api_key=pk.key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=messages,
            temperature=0.3,
            max_tokens=8192,
        )
        return resp.choices[0].message.content or ""


_pool_instance: AIKeyPool | None = None
_pool_lock = threading.Lock()


def get_ai_pool() -> AIKeyPool:
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = AIKeyPool()
    return _pool_instance
