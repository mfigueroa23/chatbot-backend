from langgraph.graph import END, START, MessagesState, StateGraph
from src.agents.context import AgentContext
from src.agents.nodes import assistant

builder = StateGraph(MessagesState, context_schema=AgentContext)
builder.add_node("assistant", assistant)
builder.add_edge(START, "assistant")
builder.add_edge("assistant", END)
