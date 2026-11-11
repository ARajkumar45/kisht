"""config.yaml -> which adapter plays which role. The only place adapters are chosen.

LLM roles (agent, planner, simulator) each point at a server. Roles on the same server share
its concurrency slots, because they share its GPU. API keys are never written in the file:
a server names the environment variable that holds its key (api_key_env).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kisht.adapters.llm import LimitedModel, OpenAICompatibleModel, ServerSlots
from kisht.ports import ChatModel

Role = Literal["agent", "planner", "simulator", "reviewer"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMServer(_Strict):
    base_url: str
    api_key_env: str | None = None      # e.g. DEEPINFRA_API_KEY; None for a local server
    max_concurrency: int = Field(2, ge=1)
    queue_timeout_s: float = Field(300.0, gt=0)
    request_timeout_s: float = Field(60.0, gt=0)


class LLMRole(_Strict):
    server: str
    model: str
    temperature: float = Field(0.3, ge=0, le=2)
    max_tokens: int = Field(400, ge=1)
    disable_thinking: bool = True


class Stores(_Strict):
    redis_url: str = "redis://localhost:6379/0"
    ledger_db: str = "data/ledger.sqlite"
    insights_db: str = "data/insights.sqlite"     # call log, traces, reviews, human desk
    audit_dir: str = "audit"


class Tracing(_Strict):
    otlp_endpoint: str | None = None   # e.g. http://localhost:4318 for Jaeger / Phoenix


class Speech(_Strict):
    provider: Literal["sarvam"] = "sarvam"
    stt_model: str = "saarika:v2.5"
    tts_model: str = "bulbul:v3"
    speaker: str = "shreya"


class Config(_Strict):
    llm_servers: dict[str, LLMServer]
    llm_roles: dict[Role, LLMRole]
    stores: Stores = Stores()
    speech: Speech = Speech()
    tracing: Tracing = Tracing()
    lenders_dir: str = "lenders"
    knowledge_dir: str = "knowledge"

    @model_validator(mode="after")
    def _roles_point_at_known_servers(self) -> Config:
        for role, spec in self.llm_roles.items():
            if spec.server not in self.llm_servers:
                raise ValueError(f"llm_roles.{role}.server {spec.server!r} is not in llm_servers "
                                 f"({', '.join(self.llm_servers)})")
        return self


def load_config(path: str | Path = "config.yaml") -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))


class LLMFactory:
    """Builds one ChatModel per role; every role on a server shares that server's slots."""

    def __init__(self, config: Config):
        self.config = config
        self.slots = {name: ServerSlots(s.max_concurrency, s.queue_timeout_s)
                      for name, s in config.llm_servers.items()}

    def for_role(self, role: Role) -> ChatModel:
        if role not in self.config.llm_roles:
            raise KeyError(f"no llm_roles.{role} in config")
        spec = self.config.llm_roles[role]
        server = self.config.llm_servers[spec.server]
        api_key = "local"
        if server.api_key_env:
            api_key = os.environ.get(server.api_key_env, "")
            if not api_key:
                raise RuntimeError(f"llm server {spec.server!r} needs the environment variable "
                                   f"{server.api_key_env} (put it in .env; never in config.yaml)")
        inner = OpenAICompatibleModel(
            base_url=server.base_url, model=spec.model, api_key=api_key,
            timeout_s=server.request_timeout_s, max_tokens=spec.max_tokens,
            temperature=spec.temperature, disable_thinking=spec.disable_thinking,
            name=f"{spec.server}:{spec.model}")
        return LimitedModel(inner, self.slots[spec.server])
