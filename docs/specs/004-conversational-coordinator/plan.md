# Plan 004 — Coordinador conversacional de una sola voz

**Spec:** `docs/specs/004-conversational-coordinator/spec.md` · **Estado:** aprobado (2026-10-08)
Se conservan el grafo de LangGraph con su checkpointer, el recuperador y sus señales del ámbito, los agentes de área con
sus herramientas, la validación de procedimientos, el notificador, el auditor y el orquestador de ambos canales. Cambia
quién habla: un coordinador nuevo conversa en texto libre y deriva en el agente de ámbito, que es el agente del canal
actual reconvertido (decide áreas, sin hablar con el usuario); los agentes de área generan contenido para el coordinador.

## 1. Resumen
Tres niveles, una voz. El **coordinador** es un bucle con herramientas (patrón de `run_sub_agent` y del agente de
`agente-ti`): en cada paso responde en texto (la respuesta al usuario) o llama herramientas. Su contexto es su prompt, la
persona del canal y la conversación; no recibe áreas, FAQ ni procedimientos. Para cualquier consulta llama
`consultar_areas`, que el código ata al **agente de ámbito** del canal (interno en Google Chat, externo en el web). El
agente de ámbito ve las áreas de su ámbito con sus temas y trámites, decide en una llamada estructurada a qué áreas
corresponde la consulta (o si el usuario pregunta qué puede consultar) y lanza en paralelo a los **agentes de área**, que
buscan, generan el contenido y gestionan los procedimientos con su validación en código. Todo vuelve al coordinador, que
redacta. Antes de enviar, un control posterior aplica el auditor, los datos personales, las promesas y las acciones no
realizadas, con un reintento.
- **Una sola voz (RF-1 a RF-6):** el texto final del coordinador es la respuesta; sin textos fijos ni plantillas.
- **Derivación por canal (RF-7 a RF-14):** herramienta `consultar_areas` atada al ámbito; agente de ámbito con catálogo.
- **Conversación (RF-15 a RF-21):** prompt y persona del coordinador con el historial; sin clasificación previa.
- **Respuestas (RF-22 a RF-27):** agentes de área que generan contenido; respuesta libre solo en el interno.
- **Procedimientos (RF-28 a RF-38):** `iniciar_procedimiento` sigue en el agente de área sobre `handle_procedure`.
- **Ejecutivo web (RF-39 a RF-44):** herramientas `ofrecer_ejecutivo` y `responder_oferta`; las fases siguen en el orquestador.
- **Avisos internos (RF-45 a RF-48):** herramienta `avisar_area`.
- **Seguridad (RF-49 a RF-55):** control posterior en `audit.py` y reintento único.
- **Configuración y memoria (RF-56 a RF-58):** prompts en `agent_prompt`, sin caché; memoria con los textos enviados.

## 2. Módulos

### Datos y catálogo
| Módulo | Cambio | RF |
|---|---|---|
| `src/services/business_data.py` | `get_area_topics(session, area_ids, limit) -> dict[int, AreaTopics]`: nombres (`Faq.question`, `Procedure.name`) de las FAQ y procedimientos activos de cada área, por id y acotados | RF-9, RF-12, RF-57 |
| `src/agents/graph.py` (`Catalog`, `load_catalog`) | `Catalog` lleva `coordinator_prompt` (`{scope}_coordinator`), `scope_prompt` (`{scope}_agent`), `area_rules`, `persona` y las áreas del ámbito con sus `topics`; se eliminan `fixed` y `area_names` | RF-6, RF-9, RF-10, RF-56, RF-57 |

### Agentes
| Módulo | Cambio | RF |
|---|---|---|
| `src/agents/coordinator.py` (nuevo) | `CoordinatorToolbox` y `run_coordinator(llm, toolbox, messages, budget) -> CoordinatorTurn`. Herramientas: `consultar_areas(consulta)` (el código la ata al agente de ámbito del canal: el modelo no elige ámbito); `avisar_area(resumen)` solo en el interno; `ofrecer_ejecutivo()` y `responder_oferta(acepta)` solo en el web (la segunda solo con oferta pendiente). Cada herramienta devuelve al modelo un resultado en texto y deja en el toolbox los hechos que necesita el código: evidencia del turno, procedimiento y su resultado, aviso entregado, oferta | RF-1, RF-7, RF-8, RF-39 a RF-42, RF-45 a RF-48 |
| `src/agents/scope_agent.py` (nuevo) | `run_scope_agent(llm, catalog, retriever, request, budget) -> ScopeReport`. Reutiliza la llamada estructurada del actual `coordinate` (`ScopeDecision(area_ids, consulta, catalogo)`) en paralelo con `scope_signals` del recuperador; si no elige áreas válidas y hay coincidencias sobre el umbral, delega en ellas (respaldo de la spec 002). Con `catalogo` devuelve los temas y trámites del ámbito sin llamar a las áreas. Con un procedimiento en curso deriva siempre en su área. Lanza los agentes de área en paralelo y devuelve sus informes | RF-9 a RF-12, RF-14, RF-19 |
| `src/agents/sub_agent.py`, `src/agents/tools.py` | Sin cambios de mecánica (`buscar_faq`, `buscar_procedimiento`, `iniciar_procedimiento`, guardarraíl de evidencia). `AreaAnswer` añade la evidencia (`faqs`, `procedures`) para el control posterior. Su texto pasa a ser contenido para el coordinador | RF-22, RF-23, RF-25, RF-28 a RF-38 |
| `src/agents/procedure_flow.py` | Los textos `MISSING_DATA`, `INVALID_DATA` y `REQUEST_SENT` pasan a ser información para el coordinador (nombran los datos que faltan o fallaron y el área); la validación, los intentos y la plantilla de notificación no cambian | RF-29 a RF-33 |
| `src/agents/llm.py` | `CoordinatorOutput` se convierte en `ScopeDecision` (sin `kind` ni `text`); se eliminan `ConverseOutput`, `converse` y `build_converse_messages`. Nuevos `build_coordinator_messages(prompt, persona, offer_pending, pending_name, history, question, history_messages)` (sin áreas ni contenido) y `build_scope_messages(prompt, areas_with_topics, pending, history, question, history_messages)`. `build_area_messages` pide contenido para el coordinador y deja de llevar la persona | RF-6, RF-9, RF-10, RF-19, RF-22 |
| `src/agents/audit.py` | `personal_data_values(text) -> list[tuple[str, str]]`; `FUTURE_PROMISES`/`future_promises(text)`; `CLAIMED_ACTIONS`/`claimed_actions(text)`; `review(text, prompts, names, evidence, delivered) -> list[str]` con los motivos: fuga (RF-51), dato personal ausente de la evidencia (RF-53), promesa sin aviso entregado (RF-54), acción afirmada sin realizar (RF-55). `INTERNAL_NAMES` añade los nombres de las herramientas nuevas | RF-51 a RF-55 |
| `src/agents/graph.py` | Un nodo `respond`: carga el catálogo, arma los mensajes del coordinador, ejecuta `run_coordinator`, aplica `review` y, ante dato personal, promesa o acción no realizada, reintenta una vez con una nota de corrección; si persiste, o si hay fuga, `GENERIC_REFUSAL`. En el web, si se consultaron áreas, ninguna aportó evidencia y el coordinador no llamó `ofrecer_ejecutivo`, el resultado lleva la oferta igualmente. Estado: `messages`, `pending_area_id`, `pending_procedure_id`, `procedure_attempts`; se dejan de usar `clarifications`, `turn_*` y `area_tasks`. Outcomes: `answered`, `rejected`, `offer_human`, `offer_accepted`, `offer_declined`, `notification_failed` | RF-1 a RF-5, RF-25, RF-39, RF-51 a RF-55, RF-58 |
| `src/agents/behavior.py` | Se eliminan aclaraciones, opciones, textos fijos, `ensure_areas` y `combine`; queda `requester_key` | RF-2, RF-20, RF-21 |
| `src/agents/strategies.py` | Se elimina `InternalStrategy.on_no_answer` (aviso automático); `avisar_area` reutiliza `format_unanswered` y `get_fallback_space`. `ExternalStrategy` queda como `is_open` + canales oficiales, usados por `ofrecer_ejecutivo` | RF-39, RF-40, RF-45 a RF-48 |

### Canales y herramientas de operación
| Módulo | Cambio | RF |
|---|---|---|
| `src/services/chat_orchestrator.py` | `build_agent_context` añade el presupuesto (property `agent_max_model_calls`, 100). Interno: devuelve `result.reply` (o `GENERIC_REFUSAL` si `rejected` sin texto); sin `InternalStrategy`. Web: `offer_human` → texto + `OfferHuman` y `start_offer` dentro de horario, o texto + canales fuera de él; `offer_accepted`/`offer_declined` como hoy; `notification_failed` → texto + canales oficiales; el resto no cambia la fase. Se eliminan `FIXED_OUTCOMES` y `MIXED_SCOPE` | RF-3, RF-4, RF-34, RF-39 a RF-44, RF-47, RF-48 |
| `src/services/google_chat.py` | El saludo al añadir el bot a un space lo redacta el coordinador a partir de una nota de sistema, sin mensaje del usuario | RF-2, RF-15 |
| `src/cli/behavior_check.py` | Se retiran las baterías de clasificación y elección (miden categorías que ya no existen); queda `--variety N` en ambos ámbitos | RNF-4 |
| `src/cli/jailbreak_check.py` | Sin cambios de forma; el informe deja de tratar la negativa genérica como la única negativa válida | RNF-5 |
| `README.md` | Diagrama de los tres niveles, keys de `agent_prompt` y su contenido esperado, properties nuevas y retiradas | RF-56 |

## 3. Modelo de datos
- **Sin cambios de esquema** y **sin migraciones**.
- **`agent_prompt`:** keys nuevas `internal_coordinator` y `external_coordinator` (prompt del coordinador de cada canal);
  `internal_agent` y `external_agent` pasan a ser el prompt del agente de ámbito (decidir áreas o catálogo, sin redactar
  para el usuario); `area_rules` pide contenido para el coordinador. Contenido mínimo en D9. Los textos solo viven en la
  BD (decisión de la spec): se cargan en local y en remoto con respaldo previo y tu aprobación. Las keys
  `{internal,external}_{greeting,closing,off_topic}` dejan de leerse y no se borran.
- **Properties nuevas:** `agent_max_model_calls` (int, 100, RNF-1) y `scope_topics_per_area` (int, 50: temas y trámites
  por área en el prompt del agente de ámbito).
- **Properties que dejan de usarse:** `rag_clarify_similarity`. Se mantienen `rag_min_similarity`, `rag_top_k`,
  `agent_max_steps`, `procedure_max_attempts`, `agent_history_messages` y `conversation_temperature`.
- **Checkpointer:** los hilos existentes conservan `clarifications` y `turn_*`; el nodo nuevo los ignora y
  `CHECKPOINT_TYPES` mantiene `Clarification`, `ClarifyOption` y `Candidate` registrados para deserializarlos.

## 4. Contrato
- **Google Chat `/api/v1/google-chat/events`:** sin cambios de forma.
- **WebSocket `/ws/v1/chat`:** sin cambios de forma (`message`, `offer_human`, `request_contact`, `official_channels`,
  `queued`, `error`). Cambia cuándo se emite la oferta (la decide el coordinador) y que un mensaje con una oferta
  pendiente ya no la cancela (RF-43).

## 5. Decisiones
- **D1 — Coordinador como bucle propio con herramientas (`run_coordinator`).** El patrón ya está probado en
  `run_sub_agent`, deja en código el control de cada herramienta y del presupuesto, y funciona con
  `GeminiAgentLLM.step`. *Descartada:* `langchain.agents.create_agent` como en `agente-ti` — exige la dependencia
  `langchain` (constitución, punto 1) y su middleware cubre límites que aquí son dos contadores; *descartada:*
  `create_react_agent` de `langgraph-prebuilt` — en desuso, y su estado de mensajes no deja guardar solo los textos
  enviados.
- **D2 — El canal elige el agente de ámbito en código, no el coordinador.** `consultar_areas` se ata al ámbito al
  compilar el grafo de cada canal (como hoy `build_graph(scope)`): el coordinador no puede consultar el otro ámbito ni
  por manipulación (RF-7, RF-8, RF-10). *Descartada:* dos herramientas (`consultar_interno`/`consultar_externo`) entre
  las que elija el modelo — abre la puerta a cruzar ámbitos.
- **D3 — El agente de ámbito es una llamada estructurada, no un bucle.** Decide áreas y consulta reformulada (o el
  catálogo) en una llamada, en paralelo con el embedding de `scope_signals`, y su respaldo por coincidencias se conserva.
  Un mensaje con consulta queda en 4 llamadas en serie (coordinador, ámbito, área, coordinador). *Descartada:* un bucle
  que además redacte un resumen — suma una llamada en serie sin aportar a la voz, que es del coordinador.
- **D4 — Los procedimientos siguen en el agente de área.** El área es quien identifica el trámite y conoce sus datos; la
  validación y la notificación son las de la spec 001, y el resultado sube al coordinador como información. *Descartada:*
  mover `iniciar_procedimiento` al coordinador — tendría que conocer los procedimientos, contra RF-6.
- **D5 — Control posterior con un reintento.** `review` detecta fuga, dato personal fuera de la evidencia, promesa sin
  aviso y acción afirmada sin realizar; ante un nombre interno, un dato personal, una promesa o una acción se reintenta una
  vez con una nota que nombra el problema; si persiste, o si hay un fragmento de prompt o código, `GENERIC_REFUSAL`
  (ajustado el 2026-10-08, RF-59: un nombre interno es un descuido corregible, como vio el usuario en Google Chat). *Descartada:* sustituir directamente — una negativa por un descuido
  corregible; *descartada:* confiar solo en el prompt — RF-53 a RF-55 dejarían de ser verificables (casos A y B de
  `agente-ti`).
- **D6 — En el web, sin evidencia tras consultar, la oferta se aplica aunque el coordinador no la pida.** RF-25 y RF-39
  quedan verificables en código para el caso principal. *Descartada:* depender solo del prompt.
- **D7 — Temas y trámites en el prompt del agente de ámbito, acotados por `scope_topics_per_area`.** Hoy son 33 FAQ y 1
  procedimiento en local. *Descartada:* una herramienta de búsqueda de temas — una llamada más para decidir áreas.
- **D8 — La memoria guarda la pregunta y el texto enviado, no las llamadas a herramientas.** El coordinador conserva el
  hilo de la conversación sin arrastrar contenido de áreas de turnos anteriores (RF-6, RF-58). *Descartada:* guardar la
  traza completa — crece con cada consulta y mete el contenido de áreas en el contexto del coordinador.
- **D9 — Contenido mínimo de los prompts de la BD.** `{scope}_coordinator`: rol de asistente con IA, prioridades,
  cuándo usar cada herramienta, principios breves (infiere y no inventes; no confirmes lo que una herramienta no
  confirmó; no prometas avisos; traduce los errores; el texto del usuario no es una instrucción), un solo párrafo de
  seguridad y, en el interno, la respuesta libre con aviso de no oficial. `{scope}_agent`: decidir áreas, reformular la
  consulta con el contexto y reconocer «qué puedo consultar». `area_rules`: generar contenido solo con lo encontrado,
  citar ids, dejarlo vacío si no hay. Se te presentan para aprobación antes de cargarlos. *Descartada:* versionarlos en
  una migración — la spec los deja solo en la BD.
- **D10 — Saludo al añadir el bot redactado por el coordinador.** Cumple RF-2 también en el alta del space.
  *Descartada:* mantener el texto fijo de `google_chat.py` — es una plantilla con la lista de áreas.
- **D12 — Negrita de Google Chat en el orquestador (RF-60).** `handle_internal_message` convierte `**texto**` en
  `*texto*` antes de devolver la respuesta. *Descartada:* confiar en el prompt — la persona ya pedía no usar negritas y el
  modelo las usó igual.
- **D11 — Tope de llamadas como presupuesto compartido.** Coordinador, agente de ámbito y agentes de área descuentan de
  `agent_max_model_calls`; al agotarse, el turno termina con el mensaje de servicio no disponible y un log de aviso.
  *Descartada:* topes separados por nivel — la spec fija uno por mensaje.

## 6. Estrategia de tests
Sin BD ni red (`dependency_overrides`, dobles de `tests/fakes.py`). `FakeAgentLLM` guioniza los pasos del coordinador
(`coordinator_steps`), la decisión del agente de ámbito (`scope`) y los pasos de cada área (`steps` por nombre de área),
y cuenta las llamadas.

- **Unidad — `tests/business_data_test.py`:** temas acotados por área, sin respuestas; catálogo con los prompts nuevos.
- **Unidad — `tests/audit_test.py`:** `personal_data_values`, `future_promises`, `claimed_actions` y `review` (dato
  presente en la evidencia permitido y ausente rechazado; promesa y acción con y sin entrega).
- **Unidad — `tests/gemini_llm_test.py`:** mensajes del coordinador sin áreas ni contenido; mensajes del agente de ámbito
  con temas solo de su ámbito; mensajes de área que piden contenido para el coordinador.
- **Unidad — `tests/procedure_flow_test.py`:** textos informativos de faltantes, inválidos y enviado.
- **Agentes — `tests/scope_agent_test.py` (nuevo):** áreas elegidas en paralelo; respaldo por coincidencias; catálogo
  sin llamar a áreas; procedimiento en curso a su área; el agente externo nunca ve áreas internas.
- **Agentes — `tests/coordinator_test.py` (nuevo):** `consultar_areas` atada al ámbito; `avisar_area` entregado y
  fallido; `ofrecer_ejecutivo` dentro y fuera de horario; `responder_oferta` sin oferta pendiente; presupuesto agotado.
- **Grafo — `tests/agent_graph_test.py`:** respuesta igual al texto final sin añadidos (RF-2); coordinador sin contenido
  de áreas en sus mensajes (RF-6); un texto con dos áreas (RF-5, RF-24); seguimiento con historial (RF-19); tema del otro
  ámbito (RF-14); respuesta libre en el interno sin aviso (RF-26); oferta forzada en el web sin evidencia (D6); reintento
  y negativa genérica (RF-51 a RF-55); procedimiento con dato inválido, tercer intento y notificación fallida (RF-31 a
  RF-36); memoria con el texto enviado (RF-58).
- **Servicio — `tests/chat_orchestrator_test.py`:** salida de cada outcome por canal; fase del web que no cambia con un
  mensaje normal (RF-43); proveedor caído y mensajes vacío o largo (RF-3, RF-4).
- **API — `tests/google_chat_test.py`:** saludo al añadir el bot redactado por el coordinador (D10).
- **CLI — `tests/behavior_check_test.py` y `tests/jailbreak_check_test.py`:** variedad en ambos ámbitos; batería interna
  en proceso.
- **Tests que se retiran**, porque verifican requisitos que la spec 004 sustituye: clasificación del agente del canal,
  mensajes fijos, aclaración con opciones y elección, prioridad de RF-39, `converse` y aviso automático (en
  `agent_graph_test`, `behavior_test`, `gemini_llm_test`, `chat_orchestrator_test`, `behavior_check_test` y
  `channel_strategy_test`). Cada commit los nombra.
- **Casos límite de la spec con test propio:** saludo sin lista pegada; «¿qué puedo consultarte?» en cada canal;
  «¿y de Remuneraciones?» como seguimiento; dos áreas en un texto; tema del otro ámbito; web sin FAQ dentro y fuera de
  horario; dato inválido y tercer intento; notificación fallida sin confirmación; promesa sin aviso; oferta pendiente que
  sigue tras otro mensaje.

## 7. Orden de implementación
1. Datos: temas por área y `Catalog` con los prompts nuevos (sin quitar aún lo viejo); tests.
2. `audit.py`: `personal_data_values`, `future_promises`, `claimed_actions` y `review`; tests.
3. Agentes de área en modo contenido (`build_area_messages`, `procedure_flow`, evidencia en `AreaAnswer`); tests.
4. `scope_agent.py`: decisión estructurada, señales, catálogo y fan-out a las áreas; tests.
5. `coordinator.py`: toolbox, bucle y presupuesto; tests.
6. Grafo: nodo `respond` con el coordinador y el control posterior; se retiran clasificación, aclaración, textos fijos y
   `converse`, con sus tests; tests nuevos del grafo.
7. Orquestador y Google Chat: outcomes nuevos, fases del web y saludo al añadir el bot; se retira `InternalStrategy`.
8. CLIs y README; `uv run pyright` y `uv run pytest`.
9. Despliegue: aprobación y carga de los prompts (local y remoto, con respaldo), `jailbreak_check` en ambos canales,
   `behavior_check --variety 5` en ambos, prueba de carga y demo manual.

## 8. Matriz de cobertura
| RF | Módulos | Tests |
|---|---|---|
| RF-1 | `graph.respond`, `coordinator` | `agent_graph_test` |
| RF-2 | `graph.respond`, `behavior` (retirada), `google_chat` (D10) | `agent_graph_test`, `google_chat_test` |
| RF-3 | `chat_orchestrator` | `chat_orchestrator_test` |
| RF-4 | `chat_orchestrator` (sin cambios) | `chat_orchestrator_test` |
| RF-5 | `graph.respond` | `agent_graph_test` |
| RF-6 | `llm.build_coordinator_messages`, D8 | `gemini_llm_test`, `agent_graph_test` |
| RF-7 | `coordinator.consultar_areas` (D2) | `coordinator_test` |
| RF-8 | `coordinator.consultar_areas` (D2) | `coordinator_test` |
| RF-9 | `business_data.get_area_topics`, `llm.build_scope_messages` | `business_data_test`, `gemini_llm_test` |
| RF-10 | `graph.load_catalog`, D2 | `scope_agent_test` |
| RF-11 | `scope_agent` | `scope_agent_test` |
| RF-12 | `scope_agent` (catálogo) | `scope_agent_test`, demo |
| RF-13 | `scope_agent` (ámbito externo), `audit.review` | `scope_agent_test`, `audit_test` |
| RF-14 | `scope_agent`, prompt (D9) | `agent_graph_test`, demo |
| RF-15 | prompt (D9), `google_chat` (D10) | `google_chat_test`, demo |
| RF-16 | prompt (D9) | demo |
| RF-17 | prompt (D9) | demo |
| RF-18 | prompt (D9) | demo |
| RF-19 | historial en coordinador y ámbito (D8) | `agent_graph_test`, demo |
| RF-20 | prompt (D9) | demo |
| RF-21 | historial (D8) | `agent_graph_test`, demo |
| RF-22 | `sub_agent`, `llm.build_area_messages` | `sub_agent_test`, `gemini_llm_test` |
| RF-23 | `sub_agent` (sin cambios) | `sub_agent_test` |
| RF-24 | `graph.respond` | `agent_graph_test` |
| RF-25 | `sub_agent` (guardarraíl), `graph.respond` (D6) | `agent_graph_test` |
| RF-26 | prompt interno (D9) | `agent_graph_test`, demo |
| RF-27 | prompt interno (D9) | demo |
| RF-28 | `sub_agent`, prompt | `agent_graph_test`, demo |
| RF-29 | `procedure_flow` | `procedure_flow_test`, `agent_graph_test` |
| RF-30 | `procedure_flow` (sin cambios) | `procedure_flow_test` |
| RF-31 | `procedure_flow` | `procedure_flow_test`, `agent_graph_test` |
| RF-32 | `procedure_flow` (sin cambios) | `procedure_flow_test` |
| RF-33 | `procedure_flow`, `audit.review` | `agent_graph_test`, `audit_test` |
| RF-34 | `coordinator`, `chat_orchestrator` | `agent_graph_test`, `chat_orchestrator_test` |
| RF-35 | `graph.respond` (agotado en el interno) | `agent_graph_test` |
| RF-36 | `graph.respond` (agotado en el web → oferta) | `agent_graph_test` |
| RF-37 | `procedure_flow` (sin cambios) | `procedure_flow_test` |
| RF-38 | `procedure_flow` (sin cambios) | `procedure_flow_test` |
| RF-39 | `coordinator.ofrecer_ejecutivo`, `graph.respond` (D6), `chat_orchestrator` | `coordinator_test`, `chat_orchestrator_test` |
| RF-40 | `coordinator.ofrecer_ejecutivo`, `strategies` | `coordinator_test`, `chat_orchestrator_test` |
| RF-41 | `coordinator.ofrecer_ejecutivo`, prompt | `coordinator_test` |
| RF-42 | `coordinator.responder_oferta` | `coordinator_test`, `chat_orchestrator_test` |
| RF-43 | `chat_orchestrator` | `chat_orchestrator_test` |
| RF-44 | `chat_orchestrator` (sin cambios de forma) | `web_chat_ws_test` |
| RF-45 | `coordinator.avisar_area` (solo interno), prompt | `coordinator_test` |
| RF-46 | `coordinator.avisar_area` | `coordinator_test` |
| RF-47 | `coordinator.avisar_area`, `audit.review` | `coordinator_test`, `audit_test` |
| RF-48 | `coordinator.avisar_area` | `coordinator_test` |
| RF-49 | prompt (D9), `audit.review` | `jailbreak_check`, `agent_graph_test` |
| RF-50 | prompt (D9) | `jailbreak_check`, demo |
| RF-51 | `audit.review`, `graph.respond` | `audit_test`, `agent_graph_test` |
| RF-52 | `graph.respond` | `agent_graph_test` |
| RF-53 | `audit.review` (D5) | `audit_test`, `agent_graph_test` |
| RF-54 | `audit.review` (D5) | `audit_test`, `agent_graph_test` |
| RF-55 | `audit.review` (D5) | `audit_test`, `agent_graph_test` |
| RF-56 | `graph.load_catalog` | `business_data_test` |
| RF-57 | `business_data` (sin caché) | `business_data_test` |
| RF-58 | `graph.respond` (D8) | `agent_graph_test` |
| RF-59 | `graph.respond` (`RETRYABLE`, D5) | `agent_graph_test` |
| RF-60 | `chat_orchestrator.handle_internal_message` (D12) | `chat_orchestrator_test` |
| RNF-1 | presupuesto compartido (D11) | `coordinator_test` |
| RNF-2 | — | prueba de carga |
| RNF-3 | persona y prompts | demo |
| RNF-4 | `cli/behavior_check --variety` | `behavior_check_test`, ejecución en el despliegue |
| RNF-5 | `cli/jailbreak_check` | `jailbreak_check_test`, ejecución en el despliegue |

## 9. Riesgos y dudas
- **R1 — Rechazo tras el reintento** (dato personal, promesa o acción no realizada). **Decisión del usuario
  (2026-10-08):** se envía la negativa genérica (RF-52), la única excepción a RF-2 (D5).
- **R2 — Presupuesto agotado (RNF-1).** **Decisión del usuario (2026-10-08):** mensaje de servicio no disponible y log
  de aviso (D11).
- **R3 — Latencia.** Una consulta son al menos 4 llamadas en serie (coordinador, ámbito, área, coordinador); con 2 la
  spec 002 midió 8,69 s. Google Chat tiene la respuesta diferida de 30 s (spec 001, RF-68); el web espera por el
  WebSocket. *Mitigación:* áreas en paralelo, embedding en paralelo con el ámbito, `thinking_budget=0` y medición con la
  prueba de carga antes de fusionar (RNF-2). **Medición en el despliegue (2026-10-08, 1.4.0, `gemini-3.1-flash-lite`,
  50 sesiones simultáneas por ronda; web por WebSocket, interno en proceso):**
  - Con 300m de CPU: web p50 22,5 s, p95 23,7 s, máx 25,0 s (50/50); interno con FAQ p95 22,0 s (44/50); interno sin
    FAQ p95 18,6 s (48/50). Prometheus: 99,5 % de los periodos con throttling. Una sesión sola: ~3,2 s.
  - Con 1 CPU (manifiestos del clúster actualizados): web con FAQ p50 10,6 s, p95 13,1 s, máx 14,1 s (50/50); interno
    con FAQ p50 3,8 s, p95 6,6 s (49/50); interno sin FAQ p50 6,6 s, p95 8,0 s (50/50). Throttling máx 14,5 %.
  - Perfil de una consulta web con FAQ en reposo (5,5–7,5 s): coordinador 0,9–1,9 s → ámbito 1,0 s (en paralelo con
    el embedding, 0,4–1,1 s) → área 1,5–1,8 s (+1,4 s por cada búsqueda extra) → coordinador 1,4–1,8 s.
  - **Decisión del usuario:** RNF-2 queda en p95 ≤ 15 s. Mejoras para bajar a 10 s: precargar las señales del ámbito
    mientras el coordinador da su primer paso y limitar las búsquedas extra de las áreas (`agent_max_steps`).
- **R4 — Requisitos que solo cumple el prompt** (RF-15 a RF-18, RF-20, RF-26, RF-27, RF-50): no son verificables en
  código; se aceptan en la demo manual, como decidiste.
- **R5 — Prompts de la BD.** Si se despliega el código sin `{scope}_coordinator` cargado, el coordinador solo tendría la
  persona. *Mitigación:* cargar los prompts justo antes de fusionar, con respaldo; sin `{scope}_coordinator`, log de
  error en cada mensaje.
- **R6 — Más libertad, más riesgo de inventar.** En las capturas, el agente de `agente-ti` explicó un fallo con causas que
  no constaban («entorno sandbox»). *Mitigación:* principio «infiere, no inventes» en el prompt y RF-55 en el control
  posterior.
- **R7 — Hilos existentes.** Una conversación con una aclaración o un procedimiento a medias de la 1.3.0 sigue tras el
  despliegue: la aclaración se ignora; el procedimiento en curso se mantiene (mismas claves de estado).
- **R8 — Volumen de temas.** Si un área supera `scope_topics_per_area`, el agente de ámbito no conoce todos sus temas;
  el agente de área sigue encontrándolos al buscar.
