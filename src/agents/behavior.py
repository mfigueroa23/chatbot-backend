"""Reglas deterministas del comportamiento de asistente: aclaraciones, elección de opciones y textos fijos.

Sin E/S: el grafo decide cuándo aplicarlas y aquí solo se arman los textos y se comparan los estados.
"""
from dataclasses import dataclass, field
from typing import Literal
from src.services.area_notifier import Requester

ItemKind = Literal["faq", "procedure"]
ClarificationKind = Literal["options", "areas"]

MAX_OPTIONS = 3
CLARIFY_OPTIONS = "¿A cuál de estos temas te refieres?"
CLARIFY_OPTIONS_HINT = "Responde con el número o el nombre del tema."
CLARIFY_AREAS = "¿Con qué necesitas ayuda?"
AREAS_LINE = "Puedo ayudarte con temas de: {names}."
OTHER_PROCEDURES = "También elegiste: {names}. Pídemelo cuando terminemos este trámite."
PARTIAL_ANSWER = "No encontré información sobre: {names}."

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

@dataclass(frozen=True)
class Chosen:
    faqs: list[ClarifyOption]
    procedure: ClarifyOption | None
    other_procedures: list[ClarifyOption]

def requester_key(requester: Requester | None) -> str:
    # En un space de grupo varias personas comparten el hilo: cada una tiene su propia aclaración.
    if requester is None:
        return "web"
    return requester.contact or "anonymous"

def normalize_label(label: str) -> str:
    return " ".join(label.split()).casefold()

def build_options(candidates: list[Candidate]) -> list[ClarifyOption]:
    ordered = sorted(candidates, key=lambda candidate: (-candidate.similarity, normalize_label(candidate.label)))
    seen: set[str] = set()
    unique = []
    for candidate in ordered:
        label = normalize_label(candidate.label)
        if label not in seen:
            seen.add(label)
            unique.append(candidate)
    return [ClarifyOption(number, c.kind, c.item_id, c.area_id, c.label)
            for number, c in enumerate(unique[:MAX_OPTIONS], start=1)]

def join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} y {names[-1]}"

def areas_line(area_names: list[str]) -> str | None:
    return AREAS_LINE.format(names=join_names(area_names)) if area_names else None

def options_text(options: list[ClarifyOption]) -> str:
    lines = [f"{option.number}. {option.label}" for option in options]
    return "\n".join([CLARIFY_OPTIONS, *lines, CLARIFY_OPTIONS_HINT])

def areas_question(area_names: list[str]) -> str:
    line = areas_line(area_names)
    return f"{CLARIFY_AREAS} {line}" if line else CLARIFY_AREAS

def mentions_area(text: str, area_names: list[str]) -> bool:
    plain = text.casefold()
    return any(name.casefold() in plain for name in area_names)

def ensure_areas(text: str, area_names: list[str]) -> str:
    # Un texto redactado que ya nombra un área no se completa: repetir la lista suena a plantilla.
    line = areas_line(area_names)
    return f"{text}\n\n{line}" if line and not mentions_area(text, area_names) else text

def fixed_text(template: str, area_names: list[str]) -> str:
    # La lista la añade el código: si se editara como parte del texto, un cambio en la BD podría borrarla.
    line = areas_line(area_names)
    return f"{template}\n\n{line}" if line else template

def can_clarify(pending: Clarification | None, kind: ClarificationKind) -> bool:
    # Tras una pregunta con opciones no hay otra aclaración; tras una de áreas sí cabe una con opciones.
    if pending is None:
        return True
    return pending.kind == "areas" and kind == "options"

def chosen(options: list[ClarifyOption], numbers: list[int]) -> Chosen:
    by_number = {option.number: option for option in options}
    picked = [by_number[number] for number in dict.fromkeys(numbers) if number in by_number]
    procedures = [option for option in picked if option.kind == "procedure"]
    return Chosen(
        [option for option in picked if option.kind == "faq"],
        procedures[0] if procedures else None,
        procedures[1:],
    )

def other_procedures_text(options: list[ClarifyOption]) -> str:
    return OTHER_PROCEDURES.format(names=join_names([f"«{option.label}»" for option in options]))

def combine(answers: list[tuple[str, str | None]]) -> str | None:
    answered = [(area, text) for area, text in answers if text]
    if not answered:
        return None
    if len(answered) == 1:
        body = answered[0][1]
    else:
        body = "\n\n".join(f"Sobre {area}:\n{text}" for area, text in answered)
    missing = [area for area, text in answers if not text]
    return f"{body}\n\n{PARTIAL_ANSWER.format(names=join_names(missing))}" if missing else body
