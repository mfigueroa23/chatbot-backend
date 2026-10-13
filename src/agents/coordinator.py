from langchain_core.messages import SystemMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime
from src.agents.context import CoordinatorContext
from src.agents.tools.delegate import delegar_area

TOOLS = [delegar_area]

def build_prompt(context: CoordinatorContext) -> str:
  areas = "\n".join(f"- {sub_agent.area}: {sub_agent.description}" for sub_agent in context.sub_agents.values())
  return f"{context.system_prompt}\n\nÁreas disponibles:\n{areas}"

async def coordinator(state: MessagesState, runtime: Runtime[CoordinatorContext]) -> dict:
  context = runtime.context
  llm = context.llm.bind_tools(TOOLS)
  response = await llm.ainvoke([SystemMessage(build_prompt(context)), *state["messages"]])
  return { "messages": [response] }

coordinator_builder = StateGraph(MessagesState, context_schema=CoordinatorContext)
coordinator_builder.add_node("coordinator", coordinator)
coordinator_builder.add_node("tools", ToolNode(TOOLS))
coordinator_builder.add_edge(START, "coordinator")
coordinator_builder.add_conditional_edges("coordinator", tools_condition)
coordinator_builder.add_edge("tools", "coordinator")