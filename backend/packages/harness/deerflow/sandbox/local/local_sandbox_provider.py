import logging
from pathlib import Path

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

logger = logging.getLogger(__name__)

_singleton: LocalSandbox | None = None


class LocalSandboxProvider(SandboxProvider):
    uses_thread_data_mounts = True

    def __init__(self):
        """Initialize the local sandbox provider with path mappings."""
        self._path_mappings = self._setup_path_mappings()

    def _setup_path_mappings(self) -> list[PathMapping]:
        """
        Setup path mappings for local sandbox.

        Maps container paths to actual local paths, including skills directory
        and any custom mounts configured in config.yaml.

        Returns:
            List of path mappings
        """
        mappings: list[PathMapping] = []

        # Map skills container path to local skills directory
        try:
            from deerflow.config import get_app_config

            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # Only add mapping if skills directory exists
            if skills_path.exists():
                mappings.append(
                    PathMapping(
                        container_path=container_path,
                        local_path=str(skills_path),
                        read_only=True,  # Skills directory is always read-only
                    )
                )

            # Map custom mounts from sandbox config (legacy field, dict-shaped).
            _RESERVED_CONTAINER_PREFIXES = [container_path, "/mnt/acp-workspace", "/mnt/user-data"]
            sandbox_config = config.sandbox
            legacy_mounts: list[dict] = []
            if sandbox_config is not None:
                legacy_mounts = (getattr(sandbox_config, "__pydantic_extra__", None) or {}).get("mounts") or []
            for mount in legacy_mounts:
                if not isinstance(mount, dict):
                    continue
                raw_host = mount.get("host_path")
                raw_container = mount.get("container_path")
                read_only = bool(mount.get("read_only", False))
                if not raw_host or not raw_container:
                    continue
                host_path = Path(raw_host)
                container_path = str(raw_container).rstrip("/") or "/"

                if not host_path.is_absolute():
                    logger.warning(
                        "Mount host_path must be absolute, skipping: %s -> %s",
                        raw_host,
                        raw_container,
                    )
                    continue

                if not container_path.startswith("/"):
                    logger.warning(
                        "Mount container_path must be absolute, skipping: %s -> %s",
                        raw_host,
                        raw_container,
                    )
                    continue

                # Reject mounts that conflict with reserved container paths
                if any(container_path == p or container_path.startswith(p + "/") for p in _RESERVED_CONTAINER_PREFIXES):
                    logger.warning(
                        "Mount container_path conflicts with reserved prefix, skipping: %s",
                        raw_container,
                    )
                    continue
                # Ensure the host path exists before adding mapping
                if host_path.exists():
                    mappings.append(
                        PathMapping(
                            container_path=container_path,
                            local_path=str(host_path.resolve()),
                            read_only=read_only,
                        )
                    )
                else:
                    logger.warning(
                        "Mount host_path does not exist, skipping: %s -> %s",
                        raw_host,
                        raw_container,
                    )
        except Exception as e:
            # Log but don't fail if config loading fails
            logger.warning("Could not setup path mappings: %s", e, exc_info=True)

        return mappings

    def acquire(self, thread_id: str | None = None) -> str:
        global _singleton
        if _singleton is None:
            _singleton = LocalSandbox("local", path_mappings=self._path_mappings)
        return _singleton.id

    def get(self, sandbox_id: str) -> Sandbox | None:
        if sandbox_id == "local":
            if _singleton is None:
                self.acquire()
            return _singleton
        return None

    def release(self, sandbox_id: str) -> None:
        # LocalSandbox uses singleton pattern - no cleanup needed.
        # Note: This method is intentionally not called by SandboxMiddleware
        # to allow sandbox reuse across multiple turns in a thread.
        # For Docker-based providers (e.g., AioSandboxProvider), cleanup
        # happens at application shutdown via the shutdown() method.
        pass
