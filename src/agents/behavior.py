"""Tipos de la aclaración de la spec 002 y la clave de cada usuario de un hilo.

Desde la spec 004 el coordinador aclara con sus palabras; los tipos se mantienen porque los hilos guardados antes aún los
traen en su estado y el checkpointer necesita deserializarlos.
"""
from dataclasses import dataclass, field
from typing import Literal
from src.services.area_notifier import Requester

ItemKind = Literal["faq", "procedure"]
ClarificationKind = Literal["options", "areas"]

@dataclass(frozen=True)
class Candidate:
    """FAQ o procedimiento entre el umbral de aclaración y el de respuesta: solo su etiqueta, nunca su contenido."""
    kind: ItemKind
    item_id: int
    area_id: int
    label: str
    similarity: float

@dataclass(frozen=True)
class ClarifyOption:
    number: int
    kind: ItemKind
    item_id: int
    area_id: int
    label: str

@dataclass(frozen=True)
class Clarification:
    kind: ClarificationKind
    options: list[ClarifyOption] = field(default_factory=list)

def requester_key(requester: Requester | None) -> str:
    # En un space de grupo varias personas comparten el hilo: cada una tiene su propia aclaración.
    if requester is None:
        return "web"
    return requester.contact or "anonymous"
