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


def test_sandbox_config_no_docker_fields():
    """SandboxConfig exposes only the three output-truncation fields."""
    cfg = SandboxConfig()
    declared = set(cfg.model_fields.keys())
    assert declared == {
        "bash_output_max_chars",
        "read_file_output_max_chars",
        "ls_output_max_chars",
    }


def test_legacy_docker_fields_silently_accepted():
    """Old configs with image/replicas/mounts still load without error."""
    cfg = SandboxConfig.model_validate({
        "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
        "image": "some-image:tag",
        "replicas": 5,
        "mounts": [{"host_path": "/data", "container_path": "/mnt/data"}],
        "environment": {"FOO": "bar"},
        "bash_output_max_chars": 5000,
    })
    assert cfg.bash_output_max_chars == 5000
    for legacy in ("use", "image", "replicas", "mounts", "environment", "container_prefix", "idle_timeout"):
        assert legacy not in cfg.model_fields
