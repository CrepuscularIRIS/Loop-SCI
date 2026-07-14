"""Loop-SCI configuration package.

Public surface
--------------
* :class:`LoopSCIConfig` — top-level typed config (composed of sub-configs)
* :class:`ProviderConf`, :class:`AgentConf`, :class:`EngineConf`, :class:`RunConf`
* :func:`load_config` — load Hydra config and return a :class:`LoopSCIConfig`
* :func:`hydra_to_agent_config` — bridge to the vendored :class:`AgentConfig`
"""

from .schemas import AgentConf, EngineConf, LoopSCIConfig, ProviderConf, RunConf
from .loader import load_config, hydra_to_agent_config

__all__ = [
    "LoopSCIConfig",
    "ProviderConf",
    "AgentConf",
    "EngineConf",
    "RunConf",
    "load_config",
    "hydra_to_agent_config",
]
