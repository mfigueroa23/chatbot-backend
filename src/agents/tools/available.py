"""Herramientas en código disponibles para las áreas, por nombre (spec 001, RF-27; spec 002, RF-17, RF-18). Un área
las usa si su nombre está en business_area.tools."""
from src.agents.tools.jira import jira_tools
from src.agents.tools.registry import AreaTool

TOOLS: dict[str, AreaTool] = {tool.name: tool for tool in jira_tools()}
