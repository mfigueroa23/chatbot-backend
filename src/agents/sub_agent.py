import logging
from dataclasses import dataclass
from typing import Literal
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from src.agents.llm import AgentLLM, AreaInfo, FinalText, build_area_messages
from src.agents.tools import AreaToolbox

logger = logging.getLogger(__name__)

SubAgentKind = Literal["answered", "no_answer", "wants_human", "notification_failed", "gave_up"]

@dataclass(frozen=True)
class SubAgentResult:
    kind: SubAgentKind
    text: str | None
    attempts: dict[int, int]

async def run_sub_agent(
    llm: AgentLLM, area: AreaInfo, rules: str, question: str, history: list[BaseMessage], toolbox: AreaToolbox, max_steps: int
) -> SubAgentResult:
    # Un área sin prompt no puede responder y no se llama al modelo.
    if not area.system_prompt:
        return SubAgentResult("no_answer", None, toolbox.attempts)
    messages = build_area_messages(area, rules, question, history)
    for _ in range(max_steps):
        step = await llm.step(messages, toolbox.specs())
        if isinstance(step, FinalText):
            # Guardarraíl: un texto que no se apoyó en FAQ, procedimientos o una notificación entregada se descarta.
            if not toolbox.evidence or not step.text.strip():
                logger.info("Respuesta del área %s descartada: no se apoyó en FAQ ni procedimientos", area.name)
                return SubAgentResult("no_answer", None, toolbox.attempts)
            return SubAgentResult("answered", step.text, toolbox.attempts)
        messages.append(AIMessage(content="", tool_calls=[
            {"id": call.id, "name": call.name, "args": call.args, "type": "tool_call"} for call in step.calls]))
        for call in step.calls:
            output = await toolbox.execute(call)
            messages.append(ToolMessage(content=output, tool_call_id=call.id, name=call.name))
            if toolbox.outcome is not None:
                return SubAgentResult(toolbox.outcome, None, toolbox.attempts)
    logger.warning("El área %s superó el máximo de %s pasos sin responder", area.name, max_steps)
    return SubAgentResult("no_answer", None, toolbox.attempts)
