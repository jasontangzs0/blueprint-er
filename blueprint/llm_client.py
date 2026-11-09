"""Chat client for any OpenAI-compatible endpoint (Responses API), with usage logging.

Configuration comes from the environment or a .env file at the repository root:

  LLM_ENDPOINT    base URL of the endpoint, e.g. https://<host>/v1
  LLM_API_KEY     API key for that endpoint
  LLM_MODEL       default model name (each script can override it with --model)
  LLM_TIMEOUT_S   optional request timeout in seconds (default 1800)

The design model and the matching model may be served by different endpoints. To do
that, run the design step and the matching step with different environments, or pass
`endpoint=` and `api_key=` to ChatClient.

Every call returns the model text plus a normalised usage dict read from the API's own
`usage` object (never estimated): prompt, cached, completion and reasoning tokens, and
wall latency. Costs in the paper are computed from these counts at list prices.

Reasoning models may reject `temperature` or a JSON output format; the client retries
once with the offending parameter dropped.
"""
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


def load_env(path: Optional[str] = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (existing variables win)."""
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class ChatError(RuntimeError):
    pass


class ChatClient:
    def __init__(
        self,
        deployment: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        load_env()
        self.endpoint = (endpoint or os.environ.get("LLM_ENDPOINT", "")).rstrip("/")
        self.deployment = deployment or os.environ.get("LLM_MODEL", "")
        key = api_key or os.environ.get("LLM_API_KEY", "")
        if not self.endpoint or not self.deployment or not key:
            raise ChatError(
                "endpoint, model or key not configured: set LLM_ENDPOINT, LLM_MODEL and "
                "LLM_API_KEY in the environment or in .env (see .env.example)."
            )
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ChatError("the `openai` package is missing: pip install openai") from error
        timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "1800"))
        self._client = OpenAI(base_url=self.endpoint, api_key=key, timeout=timeout_s, max_retries=0)

    def chat(
        self,
        system: str,
        user: str,
        response_format: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_completion_tokens: int = 8192,
        retries: int = 4,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        import openai

        request: Dict[str, Any] = {
            "model": self.deployment,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_completion_tokens,
        }
        if response_format is not None:
            request["text"] = {"format": response_format}
        if temperature is not None:
            request["temperature"] = temperature
        if reasoning_effort is not None:
            request["reasoning"] = {"effort": reasoning_effort}

        attempt = 0
        while True:
            started = time.time()
            try:
                response = self._client.responses.create(**request)
            except openai.BadRequestError as error:
                detail = str(error)
                if "temperature" in detail and "temperature" in request:
                    request.pop("temperature")
                    continue
                if ("text" in detail or "format" in detail) and "text" in request:
                    request.pop("text")
                    continue
                if "reasoning" in detail and "reasoning" in request:
                    request.pop("reasoning")
                    continue
                raise ChatError(f"bad request: {detail[:500]}") from error
            except (openai.RateLimitError, openai.APIStatusError, openai.APIConnectionError) as error:
                if attempt < retries:
                    time.sleep(2**attempt)
                    attempt += 1
                    continue
                raise ChatError(f"API error after {retries} retries: {error}") from error

            latency = time.time() - started
            usage = response.usage
            input_details = getattr(usage, "input_tokens_details", None)
            output_details = getattr(usage, "output_tokens_details", None)
            return {
                "text": response.output_text or "",
                "finish_reason": response.status,
                "model": response.model,
                "latency_s": round(latency, 3),
                "usage": {
                    "prompt_tokens": getattr(usage, "input_tokens", None),
                    "cached_tokens": getattr(input_details, "cached_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "output_tokens", None),
                    "reasoning_tokens": getattr(output_details, "reasoning_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", None),
                },
            }
