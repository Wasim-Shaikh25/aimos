# Adapted from HKUDS/Vibe-Trading (MIT) — research agent stack (ReAct/swarm/
# trade-journal analyzer/shadow account). Copied at vendoring time (§22.2A).
#
# ISOLATION BOUNDARY (§22.3 rule 3): this package runs as a SEPARATE PROCESS
# (services/research, its own venv/container). Its langchain/langgraph/frontend
# dependency tree must NEVER enter the trading runtime's environment. The trading
# runtime (aimos.*) is FORBIDDEN from importing this package — enforced by the
# import-linter contract "Runtime must not import vendor.vt_research". A1 (§18.3)
# reaches it only over its local MCP/stdio interface.
"""Research sidecar stack (§20.3, §22.2C) — separate runtime, never in the loop."""

RESEARCH_SIDECAR = True

__all__ = ["RESEARCH_SIDECAR"]
