import logging
from dataclasses import dataclass
from typing import Literal
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from src.agents.llm import AgentLLM, AreaInfo, FinalText
from src.agents.tools import AreaToolbox

logger = logging.getLogger(__name__)

AreaAnswerKind = Literal["answered", "no_answer", "procedure_ask", "procedure_sent", "notification_failed", "gave_up"]

@dataclass(frozen=True)
class AreaAnswer:
    area: AreaInfo
    kind: AreaAnswerKind
    text: str | None
    attempts: dict[int, int]
    procedure_id: int | None = None  # procedimiento iniciado por la tool, si lo hubo

async def run_sub_agent(llm: AgentLLM, toolbox: AreaToolbox, messages: list[BaseMessage], max_steps: int) -> AreaAnswer:
    area = toolbox.area
    # Un área sin prompt no puede responder y no se llama al modelo.
    if not area.system_prompt:
        return AreaAnswer(area, "no_answer", None, toolbox.attempts)
    messages = list(messages)
    for _ in range(max_steps):
        step = await llm.step(messages, toolbox.specs())
        if isinstance(step, FinalText):
            # Guardarraíl: un texto que no se apoya en contenido del área se descarta.
            if not toolbox.evidence or not step.text.strip():
                logger.info("Respuesta del área %s descartada: no se apoyó en FAQ ni procedimientos", area.name)
                return AreaAnswer(area, "no_answer", None, toolbox.attempts)
            return AreaAnswer(area, "answered", step.text, toolbox.attempts)
        messages.append(AIMessage(content=step.text, tool_calls=[
            {"id": call.id, "name": call.name, "args": call.args, "type": "tool_call"} for call in step.calls]))
        for call in step.calls:
            output = await toolbox.execute(call, step.text)
            messages.append(ToolMessage(content=output, tool_call_id=call.id, name=call.name))
            if toolbox.result is not None and toolbox.procedure is not None:
                # La tool de procedimiento es terminal: su plantilla es la respuesta, sin volver al modelo.
                result, procedure_id = toolbox.result, toolbox.procedure.id
                match result.kind:
                    case "ask":
                        return AreaAnswer(area, "procedure_ask", result.text, result.attempts, procedure_id)
                    case "sent":
                        return AreaAnswer(area, "procedure_sent", result.text, result.attempts, procedure_id)
                    case "failed":
                        return AreaAnswer(area, "notification_failed", None, result.attempts, procedure_id)
                return AreaAnswer(area, "gave_up", None, result.attempts, procedure_id)
    logger.warning("El área %s superó el máximo de %s pasos sin responder", area.name, max_steps)
    return AreaAnswer(area, "no_answer", None, toolbox.attempts)
