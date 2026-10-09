"""Herramientas en código disponibles para las áreas, por nombre (spec 001, RF-27; spec 002, RF-17, RF-18; spec 003,
RF-7, RF-13). Un área las usa si su nombre está en business_area.tools."""
from src.agents.tools.edr import edr_tools
from src.agents.tools.jira import jira_tools
from src.agents.tools.registry import AreaTool

JIRA = {tool.name: tool for tool in jira_tools()}
TOOLS: dict[str, AreaTool] = {**JIRA, **{tool.name: tool for tool in edr_tools(JIRA["leer_ticket"])}}
