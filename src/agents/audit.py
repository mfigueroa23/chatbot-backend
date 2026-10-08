import re

GENERIC_REFUSAL = "Solo puedo ayudarte con consultas de las áreas de este canal."
# Nombres de la respuesta estructurada: si aparecen en un texto para el usuario, el modelo está mostrando su interior.
INTERNAL_NAMES = [
    "faq_ids", "procedure_id", "wants_human", "no_answer", "manipulation", "area_ids", "chosen_options", "accept_offer",
    "decline_offer", "off_topic", "buscar_faq", "buscar_procedimiento", "iniciar_procedimiento", "procedimiento_id",
    "about_assistant", "consultar_areas", "avisar_area", "ofrecer_ejecutivo", "responder_oferta", "buscar_tickets",
    "leer_ticket", "leer_edr", "guardar_edr", "edr_json",
]
# Un fragmento de este largo copiado de un prompt ya revela su contenido; uno más corto suele ser vocabulario del área
# (el nombre de un trámite o una sigla escrita completa) que el asistente usa con naturalidad.
LEAK_FRAGMENT_LENGTH = 50
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

# Frases con las que el modelo promete un seguimiento o afirma una acción: el asistente es reactivo y solo puede
# afirmarlas si una notificación al área se entregó en ese mismo mensaje.
FUTURE_PROMISES = [
    re.compile(r"\b(?:te|le|les)\s+(?:avisar|contactar|notificar|escribir|llamar|informar)(?:é|emos|á|án)\b", re.IGNORECASE),
    re.compile(r"\b(?:nos|se)\s+(?:pondremos|pondrá|pondrán)\s+en\s+contacto\b", re.IGNORECASE),
    re.compile(r"\b(?:te|le)\s+(?:mantendré|mantendremos)\s+informad[oa]\b", re.IGNORECASE),
]
CLAIMED_ACTIONS = [
    re.compile(r"\b(?:envié|enviamos|he enviado|hemos enviado|registré|registramos|derivé|derivamos)\b.{0,40}?"
               r"\b(?:solicitud|consulta|caso)\b", re.IGNORECASE),
    re.compile(r"\b(?:avisé|notifiqué|he avisado|hemos avisado|he notificado|hemos notificado)\b", re.IGNORECASE),
    re.compile(r"\b(?:quedaste|quedó|queda)\s+en\s+(?:la\s+)?cola\b", re.IGNORECASE),
    re.compile(r"\b(?:guardé|he guardado|hemos guardado|dejé guardado|quedó guardado|subí|he subido)\b.{0,40}?"
               r"\b(?:edr|documento|borrador)\b", re.IGNORECASE),
]

def personal_data_values(text: str) -> list[tuple[str, str]]:
    return [(kind, match.group(0)) for kind, pattern in PERSONAL_DATA for match in pattern.finditer(text)]

def personal_data_leaks(text: str) -> list[str]:
    return list(dict.fromkeys(kind for kind, _ in personal_data_values(text)))

def future_promises(text: str) -> list[str]:
    return [match.group(0) for pattern in FUTURE_PROMISES for match in pattern.finditer(text)]

def claimed_actions(text: str) -> list[str]:
    return [match.group(0) for pattern in CLAIMED_ACTIONS for match in pattern.finditer(text)]

def compact(value: str) -> str:
    return re.sub(r"[\s.\-]", "", value).lower()

def review(text: str, prompts: list[str], names: list[str], evidence: list[str], delivered: bool) -> list[str]:
    """Motivos para no enviar un texto del coordinador; vacío si puede enviarse."""
    problems = find_leaks(text, prompts, names)
    # Un dato que viene de una FAQ o un procedimiento es información oficial (p. ej. el correo de un área).
    sources = [compact(item) for item in evidence]
    problems += [f"dato personal {kind}" for kind, value in personal_data_values(text)
                 if not any(compact(value) in source for source in sources)]
    if not delivered:
        if future_promises(text):
            problems.append("promesa de seguimiento")
        if claimed_actions(text):
            problems.append("acción no realizada")
    return problems
