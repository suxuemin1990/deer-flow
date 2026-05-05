"""Verify legacy sandbox.use config emits a deprecation warning."""
import logging

from deerflow.config.app_config import AppConfig, warn_on_legacy_sandbox_use


def test_legacy_sandbox_use_emits_warning(caplog):
    cfg = AppConfig.model_validate({
        "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider"},
    })
    with caplog.at_level(logging.WARNING):
        warn_on_legacy_sandbox_use(cfg)

    matches = [r for r in caplog.records if "sandbox.use" in r.message]
    assert len(matches) == 1, f"expected exactly one warning, got: {[r.message for r in caplog.records]}"
    assert "no longer supported" in matches[0].message.lower()


def test_no_warning_when_sandbox_use_absent(caplog):
    cfg = AppConfig.model_validate({"sandbox": {}})
    with caplog.at_level(logging.WARNING):
        warn_on_legacy_sandbox_use(cfg)

    assert not [r for r in caplog.records if "sandbox.use" in r.message]
