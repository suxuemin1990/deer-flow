from pathlib import Path

from pydantic import BaseModel, Field


def _default_repo_root() -> Path:
    """Resolve the repo root without relying on the current working directory."""
    return Path(__file__).resolve().parents[5]


class SkillsConfig(BaseModel):
    """Configuration for skills system"""

    path: str | None = Field(
        default=None,
        description="Path to skills directory. If not specified, defaults to ../skills relative to backend directory",
    )

    def get_skills_path(self) -> Path:
        """
        Get the resolved skills directory path.

        Returns:
            Path to the skills directory
        """
        if self.path:
            # Use configured path (can be absolute or relative)
            path = Path(self.path)
            if not path.is_absolute():
                # If relative, resolve from the repo root for deterministic behavior.
                path = _default_repo_root() / path
            return path.resolve()
        else:
            # Default: ../skills relative to backend directory
            from deerflow.skills.loader import get_skills_root_path

            return get_skills_root_path()
