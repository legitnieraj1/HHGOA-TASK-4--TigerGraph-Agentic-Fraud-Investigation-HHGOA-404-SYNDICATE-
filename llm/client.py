"""Thin, swappable LLM wrapper (spec: "keep the model behind a thin llm/ wrapper so it's swappable"). Single-shot
JSON/text generation only -- no tool-calling loop here. The agent's fraud detection is 100% deterministic
(detectors/, graphrag/); the LLM only reasons over already-assembled evidence to select actions' phrasing,
synthesise explanations, and write the SAR narrative. See NOTES.md Phase 5 for why this split exists (Gemini
3.x's OpenAI-compat endpoint breaks on multi-turn tool calls; single-shot calls are unaffected and simpler).

Provider chain (.env LLM_CHAIN="gemini:model,gemini:model,nvidia:model,..."): tried in order on error/timeout.
Disk-cached by (model, messages, response_format) so the 20-case benchmark is deterministic and re-runs are free."""
import hashlib
import json
import os
import pathlib
import time

from dotenv import load_dotenv
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / "data" / "llm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BASE_URLS = {"gemini": os.environ.get("GEMINI_BASE_URL", ""), "nvidia": os.environ.get("NVIDIA_BASE_URL", "")}
API_KEYS = {"gemini": os.environ.get("GEMINI_API_KEY", ""), "nvidia": os.environ.get("NVIDIA_API_KEY", "")}


def _chain():
    raw = os.environ.get("LLM_CHAIN", "")
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        provider, _, model = item.partition(":")
        out.append((provider.strip(), model.strip()))
    return out


def _cache_key(model, messages, response_format, temperature):
    blob = json.dumps({"model": model, "messages": messages, "rf": response_format, "t": temperature}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _cache_path(key):
    return CACHE_DIR / f"{key}.json"


class LLMError(RuntimeError):
    pass


class LLMResult:
    def __init__(self, text, tokens, model, cached):
        self.text = text
        self.tokens = tokens
        self.model = model
        self.cached = cached


def _client_for(provider):
    return OpenAI(base_url=BASE_URLS[provider], api_key=API_KEYS[provider], timeout=90, max_retries=0)


def generate(messages, response_format=None, temperature=0.0, max_tokens=2000, use_cache=True) -> LLMResult:
    """messages: OpenAI chat format. response_format: e.g. {"type": "json_object"} or None for plain text.
    Falls through the provider chain on any error/timeout. Raises LLMError only if every provider fails."""
    errors = []
    for provider, model in _chain():
        key = _cache_key(model, messages, response_format, temperature)
        cpath = _cache_path(key)
        if use_cache and cpath.exists():
            d = json.loads(cpath.read_text())
            return LLMResult(d["text"], d["tokens"], model, cached=True)
        if not API_KEYS.get(provider):
            errors.append(f"{provider}:{model} -- no API key configured")
            continue
        try:
            t0 = time.time()
            client = _client_for(provider)
            kw = {}
            if response_format:
                kw["response_format"] = response_format
            r = client.chat.completions.create(model=model, messages=messages, temperature=temperature,
                                               max_tokens=max_tokens, **kw)
            text = r.choices[0].message.content or ""
            if not text.strip():
                raise LLMError("empty response")
            tokens = r.usage.total_tokens if r.usage else 0
            if use_cache:
                cpath.write_text(json.dumps({"text": text, "tokens": tokens, "model": model, "latency_s": time.time() - t0}))
            return LLMResult(text, tokens, model, cached=False)
        except Exception as e:  # noqa: BLE001 -- deliberately broad: fall through the chain on ANY provider failure
            errors.append(f"{provider}:{model} -- {type(e).__name__}: {str(e)[:150]}")
            continue
    raise LLMError("all providers failed: " + " | ".join(errors))


def generate_json(messages, temperature=0.0, max_tokens=2000, use_cache=True) -> dict:
    """Like generate(), but parses JSON and retries once (fresh, uncached) with a repair instruction on failure."""
    r = generate(messages, response_format={"type": "json_object"}, temperature=temperature, max_tokens=max_tokens, use_cache=use_cache)
    try:
        return json.loads(r.text)
    except json.JSONDecodeError:
        repair = messages + [{"role": "assistant", "content": r.text},
                             {"role": "user", "content": "That was not valid JSON. Return ONLY the corrected JSON object, nothing else."}]
        r2 = generate(repair, response_format={"type": "json_object"}, temperature=temperature, max_tokens=max_tokens, use_cache=False)
        return json.loads(r2.text)
