"""Base configuration interfaces for AI agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Dict, Type

from ..models.base_types import AgentFeatures
from ..models.config_data import AgentConfigData

__all__ = ["AgentConfig", "AgentFeatures"]


class AgentConfig(ABC):
    """Base configuration for an AI agent.

    This class provides a consistent interface for agent configuration while
    delegating data storage to the AgentConfigData container.
    """

    # Class variable to store registered agent types
    _agents: ClassVar[Dict[str, Type[AgentConfig]]] = {}
    """Base configuration for an AI agent.
    
    This class provides a consistent interface for agent configuration while
    delegating data storage to the AgentConfigData container.
    """

    def __init__(
        self, agent_type: str, root_path: Path, features: AgentFeatures | None = None
    ) -> None:
        """Initialize agent configuration.

        Args:
            agent_type: Type identifier for the AI agent
            root_path: Root directory containing agent logs
            features: Optional feature flags for this agent
        """
        self._data = AgentConfigData(
            agent_type=agent_type,
            root_path=root_path,
            features=features or AgentFeatures(),
        )

        # Register this agent type if not already registered
        if agent_type not in self._agents:
            self._agents[agent_type] = self.__class__

    @property
    def agent_type(self) -> str:
        """Get the agent type identifier."""
        return self._data.agent_type

    @property
    def root_path(self) -> Path:
        """Get the root directory path."""
        return self._data.root_path

    @property
    def features(self) -> AgentFeatures:
        """Get the agent's feature flags."""
        return self._data.features or AgentFeatures()

    @abstractmethod
    def validate(self) -> None:
        """Validate the configuration.

        Raises:
            ValueError: If configuration is invalid
        """

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert config to a dictionary for storage/serialization.

        Returns:
            Dictionary representation of the config
        """

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentConfig:
        """Create a config instance from a dictionary.

        Args:
            data: Dictionary containing config data

        Returns:
            New config instance
        """
