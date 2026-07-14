"""Load Hydra config and bridge to vendored AgentConfig.

Key design notes
----------------
* Hydra is the user-facing config surface (conf/*.yaml).
* The vendored ``AgentConfig`` (a pydantic ProxyModel) is an internal detail.
* ``ContextConfig`` stores the context-window size in a field named ``window``
  (not ``context_window``).  The SHARED_FLAT proxy maps the flat alias
  ``"context_window"`` -> ``("context", "window")``, so we can pass it as a
  flat key into AgentConfig directly.
* ``auto_git`` MUST be ``False``.  The vendored default is ``True``, and the
  upstream GitManager runs destructive git operations (checkout, reset --hard,
  checkout -b) that must never fire in this harness.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra
from omegaconf import OmegaConf

from loop_sci._vendor.arbor.config import AgentConfig
from loop_sci._vendor.arbor.config_schema import LLMConfig, ContextConfig, TimeoutConfig

from .schemas import AgentConf, EngineConf, LoopSCIConfig, ProviderConf, RunConf


def load_config(
    config_dir: str = "conf",
    config_name: str = "config",
    overrides: list[str] | None = None,
) -> LoopSCIConfig:
    """Load Hydra config from ``config_dir`` and return a :class:`LoopSCIConfig`.

    Parameters
    ----------
    config_dir:
        Absolute or relative path to the Hydra config directory.
        Relative paths are resolved relative to the current working directory.
    config_name:
        Name of the root config file (without ``.yaml``).
    overrides:
        Hydra-style override strings, e.g. ``["provider.model=qwen-turbo"]``.

    Notes
    -----
    * Missing ``DASHSCOPE_API_KEY`` resolves to an empty string via OmegaConf's
      ``oc.env`` resolver with a default — config loading never crashes on a
      missing key (the provider layer fails-fast later).
    * ``GlobalHydra`` is cleared before each call so the function is safe to
      call multiple times within a process (e.g. in tests).
    """
    # Resolve to absolute path so Hydra's initialize_config_dir works regardless
    # of the current working directory.
    abs_conf_dir = str(Path(config_dir).resolve())

    GlobalHydra.instance().clear()
    with initialize_config_dir(config_dir=abs_conf_dir, version_base="1.3"):
        raw = compose(config_name=config_name, overrides=overrides or [])

    d = OmegaConf.to_container(raw, resolve=True, throw_on_missing=False)
    assert isinstance(d, dict), f"Expected dict from OmegaConf, got {type(d)}"

    p = d.get("provider", {})
    a = d.get("agent", {})
    e = d.get("engine", {})
    r = d.get("run", {})

    # Build real dataclass instances for each sub-config.
    # Filter only known fields to avoid unexpected keyword arguments.
    provider_fields = {f for f in vars(ProviderConf()).keys()}
    agent_fields = {f for f in vars(AgentConf()).keys()}
    engine_fields = {f for f in vars(EngineConf()).keys()}
    run_fields = {f for f in vars(RunConf()).keys()}

    return LoopSCIConfig(
        provider=ProviderConf(**{k: v for k, v in p.items() if k in provider_fields}),
        agent=AgentConf(**{k: v for k, v in a.items() if k in agent_fields}),
        engine=EngineConf(**{k: v for k, v in e.items() if k in engine_fields}),
        run=RunConf(**{k: v for k, v in r.items() if k in run_fields}),
    )


def hydra_to_agent_config(
    cfg: LoopSCIConfig,
    *,
    bus: Any = None,
    node_id: str = "",
    agent_label: str = "executor",
) -> AgentConfig:
    """Bridge :class:`LoopSCIConfig` → vendored :class:`AgentConfig`.

    Construction strategy
    ---------------------
    We use the nested-object construction path (``llm=LLMConfig(...)``,
    ``context=ContextConfig(...)``) rather than flat kwargs, for two reasons:

    1. It is explicit: no dependency on the PROXY flat-alias registry.
    2. ``ContextConfig.window`` vs the flat alias ``context_window``: using the
       real sub-model avoids any ambiguity.

    Hard requirements
    -----------------
    * ``auto_git=False`` — the vendored default is ``True``.  Upstream's
      ``GitManager`` runs ``git checkout``/``git reset --hard``/``checkout -b``
      which must NEVER execute inside this harness.
    """
    llm = LLMConfig(
        provider="openai_compat",
        model=cfg.provider.model,
        api_key=cfg.provider.api_key,
        base_url=cfg.provider.base_url,
        max_tokens=cfg.agent.max_tokens,
    )

    context = ContextConfig(
        window=cfg.agent.context_window,
        compact_threshold=cfg.agent.compact_threshold,
        compact_keep_recent=cfg.agent.compact_keep_recent,
    )

    timeout = TimeoutConfig()

    return AgentConfig(
        llm=llm,
        context=context,
        timeout=timeout,
        max_turns=cfg.agent.max_turns,
        event_bus=bus,
        node_id=node_id,
        agent_label=agent_label,
        auto_git=False,   # HARD REQUIREMENT: never run git ops in this harness
        track_stats=True,
    )
