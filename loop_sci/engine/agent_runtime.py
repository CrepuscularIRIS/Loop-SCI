"""Thin adapter: LoopSCIConfig + provider → vendored Agent.

Design notes
------------
ToolRegistry vs vendored Tool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The vendored ``Agent`` dispatches tool calls internally via its own loop
(agent.py:471+) and expects a list of vendored ``Tool`` objects (subclasses of
``loop_sci._vendor.arbor.tools.base.Tool``) passed at construction time.  Our
``ToolRegistry`` (loop_sci.engine.tools) stores ``{name: {schema, fn, …}}`` and
has its own ``dispatch()`` — a standalone seam designed for prompt-tool protocol
usage, not for direct wiring into the vendored Agent.

For the foundation's stub tasks (pure-reasoning, no domain tools), an **empty
tool list** is passed to the Agent.  When domain tools must be exposed to the
Agent, the caller should construct vendored ``Tool`` subclasses (adapter pattern)
and supply them via the ``tools`` kwarg — the ToolRegistry itself is NOT wired
into the Agent constructor, keeping the two seams orthogonal.

auto_git
~~~~~~~~
``auto_git`` MUST remain ``False``.  The upstream ``GitManager`` runs
``git checkout / reset --hard / checkout -b`` which must NEVER fire inside this
harness.  This module delegates to ``loop_sci.config.hydra_to_agent_config``
which hard-codes ``auto_git=False`` and is the only construction path allowed.
"""
from __future__ import annotations

from typing import Any

from loop_sci._vendor.arbor.agent import Agent
from loop_sci._vendor.arbor.config import AgentConfig
from loop_sci._vendor.arbor.llm.base import LLMProvider
from loop_sci._vendor.arbor.tools.base import Tool

from loop_sci.config import hydra_to_agent_config as _hydra_to_agent_config
from loop_sci.config.schemas import LoopSCIConfig


def hydra_cfg_to_agent_config(
    cfg: LoopSCIConfig,
    *,
    bus: Any = None,
    node_id: str = "",
    agent_label: str = "executor",
) -> AgentConfig:
    """Bridge :class:`~loop_sci.config.schemas.LoopSCIConfig` → vendored :class:`AgentConfig`.

    Delegates to :func:`loop_sci.config.hydra_to_agent_config` which enforces
    ``auto_git=False`` — that hard requirement must never be bypassed here.

    Parameters
    ----------
    cfg:
        Top-level Loop-SCI config (loaded from Hydra or constructed directly).
    bus:
        Optional :class:`~loop_sci.events.EventBus` wired to ``event_bus``.
    node_id:
        Idea-tree node this agent is executing (used for event attribution).
    agent_label:
        Human-readable label stored in ``AgentConfig.agent_label``.
    """
    return _hydra_to_agent_config(cfg, bus=bus, node_id=node_id, agent_label=agent_label)


def build_agent(
    cfg: LoopSCIConfig,
    *,
    provider: LLMProvider | None = None,
    tools: list[Tool] | None = None,
    bus: Any = None,
    node_id: str = "",
    agent_label: str = "executor",
    system_prompt: str = "",
) -> Agent:
    """Construct a vendored :class:`~loop_sci._vendor.arbor.agent.Agent`.

    Parameters
    ----------
    cfg:
        Top-level Loop-SCI config.  Used to build ``AgentConfig`` and, when
        ``provider`` is not supplied, to construct the LLM provider.
    provider:
        Pre-built :class:`~loop_sci._vendor.arbor.llm.base.LLMProvider`.
        When ``None``, :func:`~loop_sci.provider.build_provider` is called with
        credentials drawn from ``cfg.provider``; if the API key is absent this
        will raise :class:`~loop_sci.provider.AuthError` immediately.
    tools:
        Vendored :class:`~loop_sci._vendor.arbor.tools.base.Tool` instances to
        register with the agent.  Defaults to an empty list (pure-reasoning
        stub tasks need no domain tools).

        **ToolRegistry relationship:** ``loop_sci.engine.ToolRegistry`` is a
        standalone seam for prompt-tool protocol usage and is NOT wired here.
        Callers who need the registry's functions inside the Agent must wrap
        each registered fn in a vendored Tool adapter themselves.
    bus:
        Optional :class:`~loop_sci.events.EventBus`; forwarded through
        ``AgentConfig.event_bus``.
    node_id:
        Idea-tree node identifier for event attribution.
    agent_label:
        Human-readable label for logs/events.
    system_prompt:
        System prompt string for the agent.

    Returns
    -------
    Agent
        Fully configured vendored Agent, ready to ``await agent.run(goal)``.
    """
    if provider is None:
        from loop_sci.provider import build_provider
        from loop_sci.provider.credentials import resolve_key

        # Resolve the API key from environment if not in config; fail fast with
        # a clear AuthError rather than an obscure downstream crash.
        api_key = cfg.provider.api_key or resolve_key("DASHSCOPE_API_KEY")
        provider = build_provider(
            model=cfg.provider.model,
            api_key=api_key,
            base_url=cfg.provider.base_url,
            timeout=cfg.provider.timeout,
            max_retries=cfg.provider.max_retries,
        )

    agent_cfg = hydra_cfg_to_agent_config(
        cfg,
        bus=bus,
        node_id=node_id,
        agent_label=agent_label,
    )

    return Agent(
        provider=provider,
        tools=tools if tools is not None else [],
        system_prompt=system_prompt,
        config=agent_cfg,
    )
