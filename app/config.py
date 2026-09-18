from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=10.0, gt=0, le=12, allow_inf_nan=False)
    request_timeout_seconds: float = Field(default=27.0, gt=0, le=28, allow_inf_nan=False)
    llm_response_format: Literal["json_schema", "json_object", "text"] = "json_schema"
    llm_temperature: float | None = Field(default=0.0, ge=0, le=0, allow_inf_nan=False)
    llm_max_tokens: int = Field(default=1600, ge=256, le=8192)
    llm_token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"

    @field_validator("llm_base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("base URL must be HTTP(S) without credentials, query, or fragment")
        return value.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.llm_model.strip() and self.llm_api_key.get_secret_value().strip())

    @classmethod
    def from_env(cls) -> "Settings":
        import os

        load_dotenv(override=False)
        values: dict[str, object] = {}
        for name in cls.model_fields:
            value = os.getenv(name.upper())
            if value is not None and value != "":
                values[name] = None if name == "llm_temperature" and value == "omit" else value
        return cls.model_validate(values)
