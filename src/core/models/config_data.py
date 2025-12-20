"""Data models for agent configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Dict, Type

from .base_types import AgentConfig, AgentFeatures

__all__ = ["AgentConfigData", "AgentFeatures"]


@dataclass  # pylint: disable=too-few-public-methods
class AgentConfigData:
    """Data container for agent configuration."""

    agent_type: str
    root_path: Path
    features: AgentFeatures | None = None

    def __post_init__(self) -> None:
        if not self.agent_type:
            raise ValueError("agent_type cannot be an empty string")


class AgentRegistry:
    """Global registry of available AI agents."""

    _agents: ClassVar[Dict[str, Type[AgentConfig]]] = {}

    @classmethod
    def register(cls, config: Type[AgentConfig]) -> None:
        """Register an agent configuration type."""
        cls._agents[config.agent_type] = config

    @classmethod
    def get(cls, agent_type: str) -> Type[AgentConfig] | None:
        """Retrieve a registered agent configuration type."""
        return cls._agents.get(agent_type)

    @classmethod
    def all(cls) -> Dict[str, Type[AgentConfig]]:
        """Return a copy of all registered agent configuration types."""
        return dict(cls._agents)
