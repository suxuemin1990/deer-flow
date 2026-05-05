from pydantic import BaseModel, ConfigDict, Field


class SandboxConfig(BaseModel):
    """Config section for sandbox-related runtime knobs.

    Only output-truncation knobs remain; isolation backends and host-side
    safety gates have been removed (see
    docs/superpowers/specs/2026-05-05-remove-sandbox-isolation-design.md).

    Legacy fields (``use``, ``mounts``, ``image``, ``replicas``,
    ``container_prefix``, ``idle_timeout``, ``environment``,
    ``allow_host_bash``) are silently accepted via ``extra="allow"`` so old
    config.yaml files keep loading; a startup warning is emitted when
    ``use`` is non-empty.
    """

    bash_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from bash tool output. Output exceeding this limit is middle-truncated (head + tail), preserving the first and last half. Set to 0 to disable truncation.",
    )
    read_file_output_max_chars: int = Field(
        default=50000,
        ge=0,
        description="Maximum characters to keep from read_file tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )
    ls_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from ls tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )

    model_config = ConfigDict(extra="allow")
