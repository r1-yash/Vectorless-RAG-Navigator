"""LLM client supporting Groq API with structured output and rate-limit backoff handling."""

import json
import time
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError

from groq import Groq, RateLimitError as GroqRateLimitError, APIError as GroqAPIError

from src import config

T = TypeVar("T", bound=BaseModel)


class LLMClientError(Exception):
    """Raised when LLM service execution or structured output validation fails."""
    pass


class LLMClient:
    """
    Groq LLM client wrapper enforcing Pydantic structured outputs and automatic 429 backoff retries.
    """

    def __init__(self):
        api_key = config.get_groq_api_key()
        self.model_name = config.get_groq_model()
        self.client = Groq(api_key=api_key) if api_key else None

    def call_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        temperature: float = 0.2,
    ) -> T:
        """
        Execute an LLM call enforcing structured JSON output validated against response_model.
        Applies exponential backoff on 429 rate limits.
        """
        if not self.client:
            raise LLMClientError(
                "Tree construction/query failed: GROQ_API_KEY environment variable is not configured, "
                "and no secondary fallback provider is configured."
            )

        # Inject strict JSON schema instructions directly into the system prompt
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        augmented_system_prompt = (
            f"{system_prompt}\n\n"
            f"CRITICAL REQUIREMENT: You MUST respond ONLY with a valid JSON object matching this exact JSON schema:\n"
            f"```json\n{schema_json}\n```\n"
            f"Do not include any preambles, explanations, or markdown code fences outside the raw JSON object."
        )

        messages = [
            {"role": "system", "content": augmented_system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        fallback_models = [
            self.model_name,
            "openai/gpt-oss-120b",
            "groq/compound-mini",
            "groq/compound",
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-20b",
        ]
        # Remove duplicates while preserving order
        candidate_models = list(dict.fromkeys(fallback_models))

        last_exception = None

        for model in candidate_models:
            attempt = 0
            backoff_seconds = 1.0

            while attempt < config.MAX_RETRIES:
                try:
                    attempt += 1
                    completion = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        response_format={"type": "json_object"},
                    )

                    raw_content = completion.choices[0].message.content or ""
                    return self._parse_and_validate(raw_content, response_model)

                except GroqRateLimitError as e:
                    last_exception = e
                    if attempt >= config.MAX_RETRIES:
                        break  # Try next fallback model
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0

                except (ValidationError, json.JSONDecodeError) as e:
                    last_exception = e
                    if attempt >= config.MAX_RETRIES:
                        break
                    time.sleep(0.5)

                except GroqAPIError as e:
                    last_exception = e
                    # If model not found or invalid, try next model immediately
                    break

        raise LLMClientError(
            f"Tree construction/query failed across candidate LLM models. Details: {str(last_exception)}"
        )

    def _parse_and_validate(self, content: str, response_model: Type[T]) -> T:
        """Strip backtick wrappers if present and parse with Pydantic."""
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        return response_model.model_validate_json(cleaned)
