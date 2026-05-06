"""Verify legacy skills.container_path config emits a deprecation warning."""
import logging

import pytest

from deerflow.config import app_config as app_config_module
from deerflow.config.app_config import AppConfig, warn_on_legacy_skills_container_path


@pytest.fixture(autouse=True)
def _reset_warning_cache():
    """Clear the once-per-process warning dedup so each test sees a fresh state."""
    app_config_module._warned_legacy_skills_container_path.clear()
    yield
    app_config_module._warned_legacy_skills_container_path.clear()


def test_legacy_skills_container_path_emits_warning(caplog):
    cfg = AppConfig.model_validate({
        "sandbox": {},
        "skills": {"container_path": "/mnt/skills"},
    })
    with caplog.at_level(logging.WARNING):
        warn_on_legacy_skills_container_path(cfg)

    matches = [r for r in caplog.records if "skills.container_path" in r.message]
    assert len(matches) == 1, f"expected exactly one warning, got: {[r.message for r in caplog.records]}"
    assert "no longer supported" in matches[0].message.lower()


def test_legacy_skills_container_path_warns_only_once(caplog):
    """Second call with the same value should not emit a duplicate warning."""
    cfg = AppConfig.model_validate({
        "sandbox": {},
        "skills": {"container_path": "/mnt/skills"},
    })
    with caplog.at_level(logging.WARNING):
        warn_on_legacy_skills_container_path(cfg)
        warn_on_legacy_skills_container_path(cfg)

    matches = [r for r in caplog.records if "skills.container_path" in r.message]
    assert len(matches) == 1


def test_no_warning_when_skills_container_path_absent(caplog):
    cfg = AppConfig.model_validate({"sandbox": {}, "skills": {}})
    with caplog.at_level(logging.WARNING):
        warn_on_legacy_skills_container_path(cfg)

    assert not [r for r in caplog.records if "skills.container_path" in r.message]


def test_skills_config_silently_accepts_legacy_field():
    """Old yaml with skills.container_path must keep loading without error."""
    from deerflow.config.skills_config import SkillsConfig

    cfg = SkillsConfig.model_validate({"path": "/x", "container_path": "/mnt/skills"})

    # Field is not exposed as an attribute; it lives in __pydantic_extra__.
    assert cfg.path == "/x"
    assert getattr(cfg, "__pydantic_extra__", {}).get("container_path") == "/mnt/skills"
