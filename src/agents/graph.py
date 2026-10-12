from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from src.agents.context import AgentContext
from src.agents.nodes import TOOLS, assistant

builder = StateGraph(MessagesState, context_schema=AgentContext)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition)
builder.add_edge("tools", "assistant")
