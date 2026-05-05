"""Verify SandboxConfig keeps loading legacy fields silently after isolation removal."""
from deerflow.config.sandbox_config import SandboxConfig


def test_legacy_allow_host_bash_field_ignored():
    """SandboxConfig.extra='allow' silently accepts the now-removed allow_host_bash field."""
    cfg = SandboxConfig.model_validate({
        "use": "deerflow.sandbox.local:LocalSandboxProvider",
        "allow_host_bash": True,
        "bash_output_max_chars": 5000,
    })
    assert cfg.bash_output_max_chars == 5000
    # Field is no longer declared on the model
    assert "allow_host_bash" not in cfg.model_fields
