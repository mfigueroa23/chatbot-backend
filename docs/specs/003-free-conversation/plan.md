# Plan 003 — Conversación libre en Google Chat

**Spec:** `docs/specs/003-free-conversation/spec.md` · **Estado:** borrador (2026-10-08)
Se reutiliza el grafo de la spec 002 (`coordinate → route → area_agent → finalize`) sin nodos nuevos: el grafo del canal
interno se compila en modo conversacional, el agente del canal redacta además el texto de sus respuestas en la misma
llamada, y `finalize` sustituye la plantilla de aclaración y el "sin respuesta" por una llamada de conversación.

## 1. Resumen
`build_graph(AreaScope.internal)` activa el modo conversacional; el web sigue igual (RF-1). La persona del asistente vive
en `agent_prompt` (`internal_persona`) y entra en los mensajes del agente del canal, de los agentes de área y de la
conversación (RF-2 a RF-4). El agente del canal devuelve, junto con su decisión, el texto del saludo, el cierre, el tema
ajeno, la pregunta sobre el asistente o la negativa; el código lo audita y usa el texto fijo si viene vacío (RF-5, RF-6,
RF-10 a RF-12, RF-19 a RF-24). Si ninguna área responde, `finalize` hace una llamada `converse`: con temas candidatos
redacta la pregunta que los propone (RF-7 a RF-9); sin ellos, o si el colaborador no eligió, da una respuesta libre
(RF-13 a RF-18). El orquestador interno solo avisa al área cuando el colaborador lo pide (RF-27, RF-28). La temperatura
del canal interno sube para que los textos varíen (RNF-4).

- **Alcance por canal (RF-1):** modo conversacional fijado por el ámbito al compilar el grafo.
- **Persona y textos redactados (RF-2 a RF-12):** `internal_persona`, campo `text` del agente del canal, kind `about_assistant`.
- **Respuestas libres y temas ajenos (RF-13 a RF-20):** llamada `converse` en `finalize`; ajeno con texto del agente del canal.
- **Seguridad (RF-21 a RF-26):** auditor sobre todo texto, detector de datos personales en las respuestas libres, negativa redactada con respaldo genérico.
- **Avisos y convivencia (RF-27 a RF-30):** orquestador interno y prioridad de RF-39 de la spec 002.

## 2. Módulos

| Módulo | Cambio | RF |
|---|---|---|
| `src/agents/llm.py` | `CoordinatorKind` añade `about_assistant`. `CoordinatorOutput` y `CoordinatorReply` añaden `text: str` (texto para el usuario cuando el kind es `greeting`, `closing`, `off_topic`, `about_assistant` o `manipulation` y el canal es conversacional; vacío en otro caso); la descripción de `kind` aclara que preguntar qué es el asistente, si es una IA o qué puede hacer es `about_assistant` y no `manipulation`, y que pedir avisar al área o que lo vea una persona es `wants_human`. `build_coordinator_messages(..., persona: str \| None)` añade la persona y la instrucción de redactar `text`. `build_area_messages(..., persona: str \| None)` añade la persona. Nuevo `AgentLLM.converse(messages) -> str` con salida estructurada `ConverseOutput(text)`. `build_converse_messages(persona, agent_prompt, area_names, topics, history, question, history_messages)`: con `topics` pide una pregunta natural que los proponga en ese orden y sin plantilla; sin `topics` pide una respuesta libre breve, con el aviso de no oficial con sus palabras si el tema es de Autofin, sin datos personales y con la cláusula de seguridad. `build_gemini_llm(session, temperature)`: `gemini_chat` recibe la temperatura (forma parte de la clave de `lru_cache`) | RF-2 a RF-7, RF-11 a RF-15, RF-19 a RF-22, RF-25, RNF-3, RNF-4 |
| `src/agents/graph.py` | `Catalog.persona`; `load_catalog` lee `{scope}_persona`. `build_graph(scope, checkpointer)` fija `conversational = scope == AreaScope.internal`. Outcomes `about_assistant` y `free_answer`. **`coordinate`** (conversacional): `manipulation` responde el `text` auditado o `GENERIC_REFUSAL`; `greeting`, `closing`, `off_topic` y `about_assistant` responden su `text` auditado o el texto fijo; con `own_area_ids`, `off_topic` y `about_assistant` delegan (RF-18, como R10 de la spec 002); al saludo y al tema ajeno les añade la línea de áreas solo si el texto no nombra ninguna. **`finalize`** (conversacional), sin respuestas: con candidatos y `can_clarify` llama a `converse` con las etiquetas de `build_options` y guarda la `Clarification` (outcome `clarify`); en otro caso llama a `converse` sin temas y responde `free_answer`; ambos textos pasan por el auditor y el libre además por `personal_data_leaks`. Nunca hace la pregunta de áreas | RF-4 a RF-24, RF-29, RF-30, RNF-1 |
| `src/agents/behavior.py` | `mentions_area(text, area_names) -> bool` y `ensure_areas(text, area_names)` (añade la línea de áreas solo si falta) | RF-5, RF-20 |
| `src/agents/audit.py` | `personal_data_leaks(text) -> list[str]`: RUT (con o sin puntos y dígito verificador), correo y teléfono chileno (`+56`/9 dígitos) | RF-25 |
| `src/services/chat_orchestrator.py` | `build_agent_context(session, requester, offer_pending=False, conversational=False)`: con `conversational` lee `conversation_temperature` (0.7) para `build_gemini_llm`. `handle_internal_message` pasa `conversational=True`; `rejected` responde `result.reply` si existe y si no `GENERIC_REFUSAL`; `free_answer`, `about_assistant` y `clarify` devuelven su texto sin `InternalStrategy`; solo `wants_human` (y lo que decida R1) pasa por `InternalStrategy.on_no_answer` | RF-17, RF-21 a RF-23, RF-27, RF-28, RNF-4 |
| `src/cli/behavior_check.py` | Caso interno «¿eres IA o un vil robot?» → `about_assistant`; `--variety N` cuenta textos distintos de N saludos en hilos nuevos; la clase `other` acepta `free_answer` y `clarify` | RF-11, RNF-4 |
| `src/cli/jailbreak_check.py` | `--scope internal` ejecuta la batería en proceso contra el grafo interno (como `behavior_check`), además del modo WebSocket del web | RF-21, RF-24, RNF-5 |
| `alembic/versions/<rev>_seed_internal_persona.py` (nuevo) | Migración de datos: `agent_prompt` `internal_persona` con la persona de la spec (`ON CONFLICT DO NOTHING`); el downgrade la borra | RF-2 |
| `README.md` | Modo conversacional de Google Chat, `internal_persona`, `conversation_temperature`, avisos al área solo a pedido y `jailbreak_check --scope internal` | — |

## 3. Modelo de datos
- **Sin cambios de esquema.**
- **Migración de datos** `seed_internal_persona`: inserta `internal_persona` en `agent_prompt` con el texto de la
  persona (cercano y profesional, trato de tú, humor ligero, sin modismos marcados, frases cortas, sin títulos ni
  negritas) y `ON CONFLICT (key) DO NOTHING`; el downgrade la borra. No hay `external_persona`: el web no la usa.
- **Property nueva** `conversation_temperature` (`float`, 0.7 por defecto en código, sin fila sembrada).
- **Checkpointer:** sin campos nuevos; los textos redactados se guardan como `AIMessage` igual que hoy (RF-30).

## 4. Contrato
- **Google Chat `/api/v1/google-chat/events`:** sin cambios de forma; cambian los textos (redactados) y deja de avisar al
  área salvo petición explícita.
- **WebSocket `/ws/v1/chat`:** sin cambios (RF-1).

## 5. Decisiones
- **D1 — Modo conversacional fijado por el ámbito al compilar el grafo.** La spec lo limita a Google Chat y cada canal ya
  tiene su grafo. *Descartada:* una property `conversational_channels` — configura algo que la spec fija.
- **D2 — El agente del canal redacta el texto en la misma llamada (`CoordinatorOutput.text`).** Saludos, cierres, temas
  ajenos, preguntas sobre el asistente y negativas no suman llamadas ni latencia. *Descartada:* una llamada aparte para
  redactar — duplica la latencia de los mensajes más frecuentes.
- **D3 — `converse` en `finalize` solo cuando ninguna área responde.** La aclaración y la respuesta libre necesitan saber
  que las áreas fallaron, cosa que el agente del canal no sabe al decidir; cuesta 1 llamada solo en ese camino (RNF-1).
  *Descartada:* que el agente del canal redacte siempre una respuesta libre de reserva — más tokens y latencia en cada
  mensaje para un caso minoritario.
- **D4 — La aclaración redactada usa las etiquetas y el orden de `build_options`.** El estado guarda las mismas opciones
  numeradas de la spec 002, así que el reconocimiento de la elección no cambia (RF-9), y «la segunda» corresponde al
  segundo tema mencionado. *Descartada:* que el modelo elija qué temas proponer — el estado no sabría qué opciones hay.
- **D5 — Las áreas se añaden por código solo si el texto no nombra ninguna.** Verifica RF-5 y RF-20 sin forzar una
  plantilla cuando el modelo ya las menciona. *Descartada:* confiar solo en el prompt — RF-5 y RF-20 dejarían de ser
  verificables.
- **D6 — Detector determinista de datos personales en las respuestas libres.** RUT, correo y teléfono por expresión
  regular; si aparece alguno, se usa una respuesta de respaldo sin datos. Solo en respuestas libres: las FAQ pueden
  contener correos oficiales. *Descartada:* solo instrucción en el prompt — RF-25 no sería verificable.
- **D7 — `about_assistant` como kind propio.** Separa la identidad de la manipulación (RF-11, RF-12) y permite medirlo en
  `behavior_check`. *Descartada:* delegarlo siempre en Ayuda General — sin FAQ de identidad cargada, terminaría en
  respuesta libre con una llamada más.
- **D8 — Temperatura 0.7 solo en el canal interno (`conversation_temperature`).** Cumple RNF-4 sin tocar la clasificación
  del web; la clasificación interna se valida con `behavior_check` al 100 %. *Descartada:* dos llamadas (clasificar a 0 y
  redactar a 0.7) — duplica la latencia; *descartada:* temperatura 0 — los saludos serían siempre idénticos.
- **D9 — Negativa redactada con respaldo genérico.** El texto de `manipulation` se audita; vacío o con fuga ⇒
  `GENERIC_REFUSAL` (RF-22, RF-23). *Descartada:* mantener siempre la negativa fija — contradice RF-22.
- **D10 — Persona en `agent_prompt` (`internal_persona`).** Editable sin desplegar, como los demás prompts (RF-2, RF-3).
  *Descartada:* incluirla dentro de `internal_agent` — los agentes de área y `converse` no leen ese prompt.

## 6. Estrategia de tests
Sin BD ni red. `FakeAgentLLM` añade `converse` guionizado y `text` en los `CoordinatorReply`.

- **Unidad — `tests/behavior_test.py`:** `mentions_area` y `ensure_areas` (con y sin áreas nombradas).
- **Unidad — `tests/audit_test.py`:** `personal_data_leaks` con RUT con y sin puntos, correo, teléfono y un texto limpio.
- **Unidad — `tests/gemini_llm_test.py`:** persona en los tres constructores de mensajes; `build_converse_messages` con y
  sin temas (orden de los temas, sin numeración impuesta); conversión de `text` y de `converse`; temperatura en `gemini_chat`.
- **Grafo — `tests/agent_graph_test.py`:** con el grafo interno: saludo, cierre, ajeno y `about_assistant` con su texto,
  vacío ⇒ fijo, fuga ⇒ fijo o negativa genérica; `about_assistant` y `off_topic` con FAQ propia delegan; negativa
  redactada y de respaldo; aclaración redactada que guarda las opciones y elección por texto; respuesta libre sin
  candidatos, tras no elegir y nunca con FAQ sobre el umbral; respuesta libre con RUT ⇒ respaldo; sin pregunta de áreas;
  `converse` solo cuando nadie responde (recuento de llamadas, RNF-1). Con el grafo web, los mismos mensajes siguen la
  spec 002 (RF-1).
- **Servicio — `tests/chat_orchestrator_test.py`:** `rejected` con texto y sin texto; `free_answer` sin aviso al área;
  `wants_human` interno avisa al área; temperatura del contexto interno y del web.
- **CLI — `tests/behavior_check_test.py` y `tests/jailbreak_check_test.py`:** `--variety`, caso `about_assistant` y modo
  `--scope internal` con grafos de dobles.
- **Migración:** `uv run alembic upgrade head` y `downgrade -1` en local, a mano.
- **Despliegue:** `behavior_check --scope internal` (incluido `--variety 5`), `jailbreak_check --scope internal` y la demo
  de 8 pasos.

## 7. Orden de implementación
1. Migración `seed_internal_persona` y `Catalog.persona`; tests.
2. `behavior.ensure_areas` y `audit.personal_data_leaks`; tests.
3. `llm.py`: `text`, `about_assistant`, persona en los mensajes, `converse` y temperatura; tests y dobles.
4. Grafo: modo conversacional en `coordinate` (textos, negativa, `about_assistant`, delegación con FAQ propia); tests.
5. Grafo: `finalize` conversacional (aclaración redactada y respuesta libre); tests.
6. Orquestador: contexto conversacional, `rejected` con texto y avisos solo a pedido; tests.
7. `behavior_check` y `jailbreak_check --scope internal`; README; `uv run pyright` y `uv run pytest`.
8. Despliegue: cargar el prompt `internal_agent` con la instrucción de redactar `text`, migrar, ejecutar las baterías y la demo.

## 8. Matriz de cobertura
| RF | Módulos | Tests |
|---|---|---|
| RF-1 | `graph.build_graph` (D1), `chat_orchestrator` | `agent_graph_test` (grafo web), `chat_orchestrator_test` |
| RF-2 | migración, `graph.load_catalog` | `business_data_test` |
| RF-3 | `graph.load_catalog` (sin caché) | `agent_graph_test` |
| RF-4 | `llm.build_*_messages` (persona) | `gemini_llm_test` |
| RF-5 | `graph.coordinate`, `behavior.ensure_areas` | `agent_graph_test`, `behavior_test` |
| RF-6 | `graph.coordinate` | `agent_graph_test` |
| RF-7 | `graph.finalize`, `llm.build_converse_messages` | `agent_graph_test`, `gemini_llm_test` |
| RF-8 | `llm.build_converse_messages` | `gemini_llm_test` |
| RF-9 | `graph.finalize` (D4), `graph.coordinate` (nivel 8) | `agent_graph_test` |
| RF-10 | `graph.coordinate`, `graph.finalize` | `agent_graph_test` |
| RF-11 | `llm.CoordinatorKind` (`about_assistant`), `graph.coordinate` | `agent_graph_test`, `behavior_check_test` |
| RF-12 | `llm.CoordinatorOutput` (descripción) | `gemini_llm_test`, `behavior_check` |
| RF-13 | `graph.finalize` | `agent_graph_test` |
| RF-14 | `graph.finalize` | `agent_graph_test` |
| RF-15 | `llm.build_converse_messages` | `gemini_llm_test`, demo |
| RF-16 | `graph.finalize` | `agent_graph_test` |
| RF-17 | `chat_orchestrator` (existente) | `chat_orchestrator_test` |
| RF-18 | `graph.coordinate`, `graph.finalize` | `agent_graph_test` |
| RF-19 | `graph.coordinate` | `agent_graph_test` |
| RF-20 | `behavior.ensure_areas` | `behavior_test`, `agent_graph_test` |
| RF-21 | `llm.CoordinatorOutput`, `graph.coordinate` | `agent_graph_test`, `jailbreak_check` |
| RF-22 | `graph.coordinate` (D9) | `agent_graph_test` |
| RF-23 | `graph.coordinate` | `agent_graph_test` |
| RF-24 | `graph.audited` en `coordinate` y `finalize` | `agent_graph_test` |
| RF-25 | `audit.personal_data_leaks`, `graph.finalize` | `audit_test`, `agent_graph_test` |
| RF-26 | `tools`, `procedure_flow` (sin cambios) | `sub_agent_test` (existente) |
| RF-27 | `chat_orchestrator.handle_internal_message` | `chat_orchestrator_test` |
| RF-28 | `chat_orchestrator.handle_internal_message` | `chat_orchestrator_test` |
| RF-29 | `graph.finalize` | `agent_graph_test` |
| RF-30 | `graph.finish` | `agent_graph_test` |
| RF-31 | `graph.finalize` (`gave_up` conversacional), `chat_orchestrator` | `agent_graph_test`, `chat_orchestrator_test` |
| RNF-1 | `graph.finalize` (D3) | `agent_graph_test` (recuento de llamadas) |
| RNF-2 | — | prueba de carga en el despliegue |
| RNF-3 | persona y prompts | revisión en la demo |
| RNF-4 | `chat_orchestrator` (temperatura), `cli/behavior_check --variety` | `chat_orchestrator_test`, `behavior_check_test` |
| RNF-5 | `cli/jailbreak_check --scope internal` | `jailbreak_check_test`, ejecución en el despliegue |

## 9. Riesgos y dudas
- **R1 — Hueco en la spec: procedimiento agotado en Google Chat.** Tras 3 datos inválidos, la spec 001 (RF-94) aplica
  "sin respuesta", que en el canal interno avisa al área; RF-27 dice que solo se avisa si el colaborador lo pide.
  **Decisión del usuario (2026-10-08):** en el canal interno, un texto redactado que explica que no se pudo validar el
  dato y ofrece avisar al área si el colaborador lo pide, sin avisar; queda en RF-31 de la spec. `finalize` llama a
  `converse` con una instrucción de procedimiento agotado (nombre del procedimiento, sin los datos entregados) y el
  orquestador no pasa ese resultado por `InternalStrategy`.
- **R2 — La temperatura puede desestabilizar la clasificación.** *Mitigación:* `behavior_check --scope internal` al 100 %
  con 0.7; si falla, bajar `conversation_temperature` sin desplegar.
- **R3 — Las respuestas libres pueden inventar datos de Autofin.** Riesgo aceptado por la spec; el aviso de no oficial lo
  redacta el modelo y no es verificable en código. *Mitigación:* la demo y la revisión de `converse` en `behavior_check`.
- **R4 — Prompts de la BD.** `internal_agent` debe pedir redactar `text` con la persona; si no, el modelo deja `text`
  vacío y se usan los textos fijos (RF-10). Se actualiza en el paso 8.
- **R5 — Latencia del camino sin respuesta.** Suma una llamada (`converse`) tras los agentes de área. *Mitigación:* se
  mide aparte en la prueba de carga (RNF-2).
