import pytest
import yaml
from pydantic import ValidationError

from kisht.adapters.llm import LimitedModel
from kisht.config import Config, LLMFactory, load_config

BASE = {
    "llm_servers": {"local": {"base_url": "http://localhost:8080/v1", "max_concurrency": 2},
                    "cloud": {"base_url": "https://example.test/v1", "api_key_env": "TEST_KEY"}},
    "llm_roles": {"agent": {"server": "local", "model": "m1"},
                  "simulator": {"server": "cloud", "model": "m2"}},
}


def test_repo_config_loads_and_is_local_first():
    cfg = load_config("config.yaml")
    assert set(cfg.llm_roles) == {"agent", "planner", "simulator", "reviewer"}
    assert all(cfg.llm_servers[r.server].api_key_env is None for r in cfg.llm_roles.values())


def test_roles_must_point_at_a_known_server():
    bad = {**BASE, "llm_roles": {"agent": {"server": "nowhere", "model": "m"}}}
    with pytest.raises(ValidationError, match="nowhere"):
        Config.model_validate(bad)


def test_unknown_keys_are_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate({**BASE, "lender": "typo"})


def test_roles_on_the_same_server_share_slots():
    cfg = Config.model_validate({**BASE, "llm_roles": {"agent": {"server": "local", "model": "a"},
                                                       "planner": {"server": "local", "model": "b"}}})
    f = LLMFactory(cfg)
    agent, planner = f.for_role("agent"), f.for_role("planner")
    assert isinstance(agent, LimitedModel) and agent.slots is planner.slots


def test_cloud_key_comes_from_the_environment_only(monkeypatch):
    f = LLMFactory(Config.model_validate(BASE))
    monkeypatch.delenv("TEST_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TEST_KEY"):
        f.for_role("simulator")
    monkeypatch.setenv("TEST_KEY", "sk-test")
    assert f.for_role("simulator").name == "cloud:m2"


def test_swapping_a_role_is_a_config_change(tmp_path):
    data = {**BASE, "llm_roles": {**BASE["llm_roles"], "agent": {"server": "cloud", "model": "m3"}}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    assert load_config(path).llm_roles["agent"].server == "cloud"
