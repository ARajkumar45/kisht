"""config.yaml -> which adapter plays which role. The only place adapters are chosen.

LLM roles (agent, planner, simulator) each point at a server. Roles on the same server share
its concurrency slots, because they share its GPU. API keys are never written in the file:
a server names the environment variable that holds its key (api_key_env).
"""
from __future__ import annotations

import os
import threading
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
    # When the model says "I sent the link" without calling the tool, the second try can be
    # made to call that tool (the API's tool_choice). Off by default: local servers differ in
    # whether they accept it. Switch on for a hosted model that does.
    force_tool_on_retry: bool = False


class LiveCall(_Strict):
    """Limits for the model while a person is waiting on a phone call. The server-wide ones
    (minutes) are sized for batch work: evals, the planner, reviews. On a call it is better to
    say the fallback line after a few seconds than to keep the caller in silence."""
    request_timeout_s: float = Field(20.0, gt=0)   # a cold read plus a full reply is ~13 s
    queue_timeout_s: float = Field(5.0, gt=0)
    max_retries: int = Field(0, ge=0)


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
    # "demo" allows the shortcuts a demo needs: a fixed clock (--at), the synthetic loan book,
    # a voice bridge with no token, a dashboard reachable from outside. A config that does not
    # say so is production, where all of those are refused.
    mode: Literal["demo", "production"] = "production"
    llm_servers: dict[str, LLMServer]
    llm_roles: dict[Role, LLMRole]
    stores: Stores = Stores()
    speech: Speech = Speech()
    tracing: Tracing = Tracing()
    live_call: LiveCall = LiveCall()
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
    """Builds one ChatModel per role (built once, then reused: each holds a connection pool);
    every role on a server shares that server's slots.

    live=True        the limits of `live_call` (voice bridge: someone is waiting).
    background=True  work nobody is waiting for (reviews, case notes of quiet calls): it may
                     never hold the server's last free slot, so a live turn is not stuck
                     behind a 700-token review. The reviewer and planner are always background.
    """

    BACKGROUND_ROLES = ("reviewer", "planner")

    def __init__(self, config: Config):
        self.config = config
        self.slots = {name: ServerSlots(s.max_concurrency, s.queue_timeout_s)
                      for name, s in config.llm_servers.items()}
        self._built: dict[tuple, ChatModel] = {}
        self._lock = threading.Lock()

    def for_role(self, role: Role, *, live: bool = False, background: bool = False) -> ChatModel:
        if role not in self.config.llm_roles:
            raise KeyError(f"no llm_roles.{role} in config")
        background = background or role in self.BACKGROUND_ROLES
        key = (role, live, background)
        with self._lock:
            if key not in self._built:
                self._built[key] = self._build(role, live, background)
            return self._built[key]

    def _build(self, role: Role, live: bool, background: bool) -> ChatModel:
        spec = self.config.llm_roles[role]
        server = self.config.llm_servers[spec.server]
        limits = self.config.live_call
        api_key = "local"
        if server.api_key_env:
            api_key = os.environ.get(server.api_key_env, "")
            if not api_key:
                raise RuntimeError(f"llm server {spec.server!r} needs the environment variable "
                                   f"{server.api_key_env} (put it in .env; never in config.yaml)")
        inner = OpenAICompatibleModel(
            base_url=server.base_url, model=spec.model, api_key=api_key,
            timeout_s=limits.request_timeout_s if live else server.request_timeout_s,
            max_retries=limits.max_retries if live else 1,
            max_tokens=spec.max_tokens,
            temperature=spec.temperature, disable_thinking=spec.disable_thinking,
            force_tools=spec.force_tool_on_retry,
            name=f"{spec.server}:{spec.model}")
        return LimitedModel(inner, self.slots[spec.server], background=background,
                            queue_timeout_s=limits.queue_timeout_s if live else None)
