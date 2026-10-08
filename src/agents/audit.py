import re

GENERIC_REFUSAL = "Solo puedo ayudarte con consultas de las áreas de este canal."
# Nombres de la respuesta estructurada: si aparecen en un texto para el usuario, el modelo está mostrando su interior.
INTERNAL_NAMES = [
    "faq_ids", "procedure_id", "wants_human", "no_answer", "manipulation", "area_ids", "chosen_options", "accept_offer",
    "decline_offer", "off_topic", "buscar_faq", "buscar_procedimiento", "iniciar_procedimiento", "procedimiento_id",
    "about_assistant",
]
# Un fragmento de este largo copiado de un prompt ya revela su contenido.
LEAK_FRAGMENT_LENGTH = 30
CODE_PATTERNS = [
    re.compile(r"```"),
    re.compile(r"^\s*(def|class|import)\s+\w+", re.MULTILINE),
    re.compile(r"\bselect\b[\s\S]+\bfrom\b", re.IGNORECASE),
]
CITATION = re.compile(r"\s*\[[FP]\d+\]")
# Datos personales que una respuesta libre nunca debe incluir: RUT, correo y teléfono chileno.
PERSONAL_DATA = [
    ("RUT", re.compile(r"\b\d{1,2}(?:\.?\d{3}){2}-[\dkK]\b")),
    ("correo", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("teléfono", re.compile(r"\+56[\s-]*\d(?:[\s-]*\d){7,8}\b|\b9\d{8}\b")),
]

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()

def strip_citations(text: str) -> str:
    # Los ids [F…]/[P…] son para el modelo; el usuario no debe verlos.
    return CITATION.sub("", text).strip()

def find_leaks(text: str, prompts: list[str], names: list[str]) -> list[str]:
    # La negativa genérica está en los propios prompts porque es la respuesta autorizada: no cuenta como fuga.
    plain = normalize(text).replace(normalize(GENERIC_REFUSAL), "")
    leaks = []
    for prompt in map(normalize, prompts):
        starts = range(0, max(len(prompt) - LEAK_FRAGMENT_LENGTH, 0) + 1, 5)
        if any(len(window := prompt[i:i + LEAK_FRAGMENT_LENGTH]) == LEAK_FRAGMENT_LENGTH and window in plain for i in starts):
            leaks.append("fragmento del prompt")
            break
    leaks += [f"nombre interno {name}" for name in names if normalize(name) in plain]
    if any(pattern.search(text) for pattern in CODE_PATTERNS):
        leaks.append("código")
    return leaks

def personal_data_leaks(text: str) -> list[str]:
    return [kind for kind, pattern in PERSONAL_DATA if pattern.search(text)]
