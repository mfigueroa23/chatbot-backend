# Plan 002 — Comportamiento de asistente

**Spec:** `docs/specs/002-assistant-behavior/spec.md` · **Estado:** borrador (2026-10-07)
Vuelve al grafo de coordinador con agentes de área que la spec 001 tuvo antes del rediseño (`git show 60a517e^`:
`load_context → classify → Send(answer_area) → combine`, `src/agents/sub_agent.py`, `src/agents/tools.py`), y conserva
de la llamada única la recuperación previa, el guardarraíl, el flujo de procedimientos con plantillas y el auditor.

## 1. Resumen
Cada canal sigue con su grafo compilado (`internal_graph`, `external_graph`) y su checkpointer, pero el grafo pasa a
tener cuatro nodos. `coordinate` es el agente del canal: con una llamada estructurada clasifica el mensaje (saludo,
cierre, fuera de tema, manipulación, persona, oferta, elección) o elige las áreas a las que delegar; en paralelo con esa
llamada, el código calcula el embedding del mensaje y las señales del ámbito (candidatos, pregunta mixta, solo el otro
ámbito), sin contenido. Después aplica los niveles 1 a 6 de RF-39. `route` reparte con `Send` en paralelo a
`area_agent`, el agente de cada área: busca las FAQ y los procedimientos de su área con ese embedding y responde con su
prompt y sus tools. `finalize` combina en código, construye las aclaraciones o aplica el
"sin respuesta", y audita.

- **Arquitectura (RF-50 a RF-60, RNF-1, RNF-2):** nodos `coordinate`, `route`, `area_agent` y `finalize`.
- **Mensajes fijos (RF-1 a RF-9, RF-35 a RF-38):** textos en `agent_prompt`; los resuelve `coordinate`.
- **Aclaración y elección (RF-10 a RF-34):** candidatos de la búsqueda del ámbito; preguntas armadas en `finalize`;
  la elección la reconoce `coordinate` y la responde el agente del área elegida.
- **Prioridad y convivencia (RF-39 a RF-49):** niveles 1 a 6 en `coordinate`, 7 a 9 en `route`, 10 y 11 en `finalize`.

```
START → [coordinate] ──(niveles 1–6 resueltos)──────────────────────────► END
              │ route
              ├─(sin áreas)──────────────────────────────► [finalize] ──► END
              └─ Send × N ─► [area_agent: área A] ─┐
                             [area_agent: área B] ─┴──────► [finalize] ──► END
```

## 2. Módulos

### Agentes (`src/agents/`)

| Módulo | Cambio | RF |
|---|---|---|
| `src/agents/llm.py` | `AgentLLM` pasa a tener `coordinate(messages) -> CoordinatorReply` y `step(messages, tools: list[ToolSpec]) -> AgentStep`; se elimina `respond`. `CoordinatorOutput` (salida estructurada): `kind` ∈ `delegate`, `no_answer`, `greeting`, `closing`, `off_topic`, `manipulation`, `wants_human`, `accept_offer`, `decline_offer`, `choice`; `area_ids: list[int]`; `chosen_options: list[int]`. Las descripciones de `kind` llevan las reglas de la spec (saludo o cierre solo sin consulta; elección por número, ordinal, texto parcial o paráfrasis, también con saludo o cierre; con otra consulta, solo la elección; ofertas solo si se indica). `build_coordinator_messages(agent_prompt, areas, options, offer_pending, pending_procedure, history, question, history_messages)`: nombre y descripción de cada área del ámbito (sin FAQ ni procedimientos), las etiquetas de las opciones pendientes del usuario y las líneas de oferta y de procedimiento en curso. `build_area_messages(area, rules, found, granted, pending, history, question, extra_fields)`: prompt del área, `area_rules`, lo que encontró la búsqueda de esa área y las opciones elegidas de esa área, con la regla «responde siempre en español». `GeminiAgentLLM.step` con `bind_tools` (se recupera de `60a517e^`), `temperature=0` y `thinking_budget=0` en ambas | RF-5, RF-7, RF-8, RF-23, RF-30, RF-31, RF-35, RF-41, RF-42, RF-49, RF-50 a RF-52, RF-57 |
| `src/agents/tools.py` (se recupera y se adapta) | `ToolSpec` y `AreaToolbox(area, retriever, notifier, requester, found, granted, attempts, max_attempts)`. Tools: `buscar_faq(consulta)` y `buscar_procedimiento(consulta)` para buscar de nuevo con una consulta reformulada (solo el área del toolbox, solo sobre el umbral de respuesta), e `iniciar_procedimiento(procedimiento_id, datos)`, **terminal**: llama a `procedure_flow.handle_procedure` y su resultado (`ask`, `sent`, `failed`, `gave_up`) cierra el agente con la plantilla. Registra las **evidencias**: lo encontrado por la búsqueda del área, lo elegido, lo devuelto por las búsquedas y la notificación entregada. El `area_id` lo fija el código | RF-25, RF-26, RF-45, RF-56, RF-57 |
| `src/agents/sub_agent.py` (se recupera y se adapta) | `run_sub_agent(llm, toolbox, messages, max_steps) -> AreaAnswer` con `kind` ∈ `answered`, `no_answer`, `procedure_ask`, `procedure_sent`, `notification_failed`, `gave_up`. Bucle modelo → tools con tope `max_steps`. **Guardarraíl:** un texto final sin evidencias se descarta (`no_answer`). Un área sin `system_prompt` responde `no_answer` sin llamar al modelo | RF-25, RF-26, RF-45, RF-46, RF-55, RNF-1 |
| `src/agents/retriever.py` | `search_scope` se sustituye por dos funciones. `scope_signals(scope, query) -> ScopeSignals(embedding, own_area_ids, candidates, other_scope_match)`: un embedding y consultas solo de ids, etiquetas y similitudes (sin respuestas ni pasos): áreas propias con algo sobre el umbral de respuesta, candidatos entre los dos umbrales y la mejor similitud del otro ámbito. `search_area(area_id, embedding) -> AreaKnowledge(faqs, procedures)`: FAQ y procedimientos de un área sobre el umbral de respuesta, reutilizando el embedding (sin otra llamada de embeddings). `search_area_faqs(area_id, query)` y `search_area_procedures(area_id, query)` para las tools, con su propio embedding. `FaqRetriever(..., min_similarity, clarify_similarity: float \| None)`. `get_faq(area_id, faq_id)` para releer una opción elegida. `read_clarify_similarity()`: si `rag_clarify_similarity` falta, no es número o es ≥ `rag_min_similarity`, devuelve `None` y registra un aviso | RF-10, RF-20 a RF-22, RF-56 |
| `src/agents/behavior.py` (nuevo) | Lógica pura: `ClarifyOption(number, kind, item_id, area_id, label)`, `Clarification(kind: "options"\|"areas", options)`, `build_options`, `options_text` (`CLARIFY_OPTIONS`), `areas_question` (`CLARIFY_AREAS`), `can_clarify`, `fixed_text(template, area_names)`, `chosen(options, numbers)` (FAQ elegidas y primer procedimiento), `OTHER_PROCEDURES`, `combine(answers) -> str` (una respuesta tal cual; varias, una por párrafo con el nombre del área; las áreas sin respuesta, en `PARTIAL_ANSWER`) y `requester_key(requester)` | RF-6, RF-11 a RF-19, RF-24, RF-27 a RF-29, RF-37, RF-40, RF-59 |
| `src/agents/graph.py` | `AgentState`: `messages`, `pending_area_id`, `pending_procedure_id`, `procedure_attempts`, `clarifications: dict[str, Clarification]` (persisten) y, por turno, `turn_candidates`, `area_answers` (reductor que acumula), `outcome`, `reply`, `selected_areas` (`coordinate` los reinicia). `AgentContext` añade `offer_pending` y `max_steps`. **`coordinate`**: carga el catálogo y lanza a la vez `llm.coordinate` (llamada 1) y `refresh_stale_embeddings` + `scope_signals` (`asyncio.gather`); guarda el embedding y los candidatos del turno; aplica en código los niveles 1 a 6 de RF-39 (manipulación, persona, oferta solo con `offer_pending`, mixta, mensaje fijo o solo el otro ámbito ⇒ `off_topic`; si falta el texto fijo, registra el error y sigue). **`route`**: nivel 7 (procedimiento en curso ⇒ su área), 8 (elección de opciones pendientes del mismo usuario ⇒ áreas de las opciones con lo elegido como `granted`), 9 (`area_ids` del coordinador ∩ áreas activas con prompt; si el coordinador delega sin áreas, las `own_area_ids` de las señales); sin áreas ⇒ `finalize`. **`area_agent`**: `search_area` con el embedding del turno y `run_sub_agent` con el `AreaTask` del `Send` (área, lo encontrado, lo elegido, procedimiento en curso, intentos). **`finalize`**: procedimiento (`ask` guarda `pending_*`; `sent`, `failed`, `gave_up` como hoy), `notification_failed` con prioridad, `behavior.combine` y auditor por texto; sin respuestas ⇒ aclaración si `can_clarify` (opciones con `turn_candidates` o pregunta de áreas) y si no `no_answer`; borra la aclaración del usuario en toda salida que no sea `clarify`. `CHECKPOINT_TYPES` registra los tipos nuevos. `load_catalog` añade las 3 keys fijas y `area_names` | RF-1 a RF-10, RF-16 a RF-19, RF-24 a RF-29, RF-32 a RF-36, RF-38 a RF-40, RF-43, RF-45 a RF-48, RF-50 a RF-60 |
| `src/agents/audit.py` | `INTERNAL_NAMES` añade los kinds nuevos, `area_ids`, `chosen_options` y los nombres de las tools | RF-47 |

### Servicios, CLI y documentación

| Módulo | Cambio | RF |
|---|---|---|
| `src/services/chat_orchestrator.py` | `build_agent_context(session, requester, offer_pending=False)` lee además `agent_max_steps` (4). `handle_web_message`: `offer_pending = phase == offering_human`; `offer_accepted` ⇒ `answer_offer(…, True)` + `RequestContact(attempt=1)`; `offer_declined` ⇒ `OFFER_REJECTED` + canales; `greeting`/`closing`/`off_topic` no llaman a `reset_to_bot`. `handle_internal_message` sin cambios de flujo | RF-9, RF-29, RF-38, RF-41 a RF-44 |
| `src/routers/web_chat.py`, `src/services/google_chat.py` | Sin cambios: `queued` y `live` no llegan al agente; el `Requester` de Google Chat ya trae el correo | RF-24, RF-44 |
| `src/cli/behavior_check.py` (nuevo) | Batería en proceso contra la BD y Gemini reales (dentro del pod), `--scope internal\|external`: clasificación por `AgentResult.outcome` y elección con `--faqs ID,ID --procedure ID` fijando el estado con `graph.aupdate_state`. Notificador que solo registra; código 1 si algo falla | RNF-5 |
| `src/cli/jailbreak_check.py` | Ataques nuevos contra las tools (nombres de `buscar_faq`, `iniciar_procedimiento`) | RF-47 |
| `alembic/versions/<rev>_seed_fixed_messages.py` (nuevo) | Migración de datos: 6 keys de `agent_prompt` (`{internal,external}_{greeting,closing,off_topic}`) con `ON CONFLICT (key) DO NOTHING`; el downgrade las borra | RF-1 |
| `README.md` | Grafo de 4 nodos, cómo dar de alta un área (filas, requisitos de la descripción y del prompt, membresía de la app en el space), properties `rag_clarify_similarity` y `agent_max_steps`, keys nuevas de `agent_prompt`, papel de coordinador de `internal_agent`/`external_agent`, `behavior_check` y la oferta por texto | — |
| `docs/specs/001-agentic-pattern-coordinator/plan.md` | Nota en D32 y RNF-10: sustituidas por la spec 002 | — |

## 3. Modelo de datos
- **Sin cambios de esquema.**
- **Migración de datos** `seed_fixed_messages`: 6 filas en `agent_prompt` sin pisar ediciones (`ON CONFLICT DO NOTHING`);
  el downgrade las borra. Textos iniciales (la lista de áreas la añade el código):
  `*_greeting` «¡Hola! Soy el asistente virtual. ¿En qué te puedo ayudar?», `*_closing` «¡Con gusto! Si necesitas algo
  más, escríbeme.», `*_off_topic` «Lo siento, no puedo ayudarte con eso.»
- **Properties** (valor por defecto en código, sin fila sembrada): `rag_clarify_similarity` = `0.55`,
  `agent_max_steps` = `4`.
- **Prompts existentes con otro papel:** `internal_agent` y `external_agent` pasan a ser los prompts de los agentes del
  canal (coordinadores); `business_area.system_prompt` + `area_rules` son los de los agentes de área. Sin cambio de
  columnas; el texto se actualiza en la BD (R1).
- **Checkpointer:** campos de estado nuevos; los hilos existentes no los tienen y se leen con valores vacíos. Los
  campos por turno se reinician en `coordinate`. Retención y borrado sin cambios (barrido de la spec 001).

## 4. Contrato
- **WebSocket `/ws/v1/chat`: sin mensajes ni campos nuevos.** Cambia la semántica:
  - `message` en `offering_human`: una confirmación responde `request_contact`; una negativa, `message` +
    `official_channels` (RF-41, RF-42). Un saludo, cierre o fuera de tema mantiene la oferta (R6); otro texto la cancela
    como hoy.
  - `message` en `collecting_contact`: un saludo, cierre o fuera de tema responde su `message` sin cambiar de fase (RF-43).
  - Este backend es el dueño del contrato; el frontend debe permitir escribir en esas fases (R4).
- **Google Chat `/api/v1/google-chat/events`:** sin cambios.

## 5. Decisiones
- **D1 — Grafo `coordinate → route(Send) → area_agent → finalize`.** Refleja el coordinador con agentes de área de la
  constitución (punto 3) y reutiliza el código de `60a517e^`. *Descartada:* el nodo único actual — decisión del usuario.
- **D2 — El agente del canal decide con salida estructurada, sin tools.** Una llamada clasifica y elige áreas.
  *Descartada:* coordinador con tools de traspaso (*handoff*) — añade una vuelta al modelo por mensaje.
- **D3 — Cada agente de área busca en su área por código antes de su llamada (decisión del usuario).** Usa el embedding
  que `coordinate` calculó en paralelo con su llamada, así que la búsqueda es solo SQL de esa área y el agente responde
  en 1 llamada en el caso normal; `buscar_*` queda para reformular. Camino mínimo: llamada 1 (con el embedding en
  paralelo) + SQL del área + llamada 2. *Descartadas:* buscar todo el ámbito antes de la llamada 1 y precargar — pone el
  embedding y la búsqueda de contenido delante del coordinador; solo tools, como antes del rediseño — 3 llamadas en
  serie, p95 local de 8,69 s.
- **D4 — Combinación en código.** `behavior.combine` une las respuestas por área en párrafos. *Descartada:*
  `llm.combine` — una llamada más en serie solo para unir textos.
- **D5 — `iniciar_procedimiento` es una tool terminal con plantillas.** Reutiliza `procedure_flow.handle_procedure`
  (validación, intentos y notificación en código, D25 y D35 de la spec 001) y no vuelve al modelo. *Descartada:*
  devolver el resultado al modelo para que redacte — una llamada más y texto no determinista.
- **D6 — Textos fijos como keys de `agent_prompt`.** Se leen sin caché (RF-2) y no cambian el esquema. *Descartada:*
  tabla `channel_message` — misma función con una migración de esquema.
- **D7 — Señales del ámbito en paralelo con el coordinador.** Una consulta de ids, etiquetas y similitudes da los
  candidatos (RF-10), la pregunta mixta (D11), el «solo el otro ámbito» (D12) y un respaldo de enrutado si el coordinador
  no elige áreas; no añade latencia porque corre durante la llamada 1. *Descartada:* sacar los candidatos de los agentes
  de área — solo existen si se delegó en esa área, y con «necesito ayuda» no se delega en ninguna.
- **D8 — Aclaraciones armadas en código en `finalize`.** La numeración coincide con el estado y ningún modelo ve el
  contenido de los candidatos (RF-34). *Descartada:* que las redacte un modelo — puede inventar o reordenar opciones.
- **D9 — La elección la reconoce el coordinador y la responde el agente del área elegida.** El coordinador solo ve las
  etiquetas; `route` pasa al agente de área el contenido elegido como `granted`, que cuenta como evidencia (RF-45).
  *Descartada:* que el coordinador responda la opción — necesitaría el contenido del área (RF-57).
- **D10 — Aclaración por usuario en el estado del hilo** (`clarifications[requester_key]`, RF-24). *Descartada:* una
  por hilo — cualquiera del space podría elegir.
- **D11 — La pregunta mixta se resuelve tras la llamada del coordinador.** RF-39 pone manipulación, persona y oferta
  por delante. *Descartada:* comprobarla antes sin modelo (D33 de la spec 001) — invierte el orden.
- **D12 — Solo el otro ámbito ⇒ `off_topic` en código.** Ningún agente ve el otro ámbito (RF-36). *Descartada:* dejarlo
  al coordinador — no tiene con qué decidirlo.
- **D13 — Oferta por texto con `offer_pending`.** El coordinador solo puede devolver `accept_offer`/`decline_offer` en la
  fase `offering_human`. *Descartada:* una lista de «sí»/«ok» en el orquestador — la spec decidió clasificar con el modelo.
- **D14 — Lista de áreas añadida por código al texto fijo.** No se rompe al editar el texto. *Descartada:* marcador
  `{areas}` — si se borra, RF-6 y RF-37 fallan sin aviso.
- **D15 — `rag_clarify_similarity` = 0.55**, calibrado en el despliegue. *Descartada:* desfase relativo al umbral de
  respuesta — oculta el valor efectivo.
- **D16 — `agent_max_steps` = 4 en `property`.** Acota RNF-1 y la latencia. *Descartada:* sin tope — un bucle de tools
  sin fin bloquea la respuesta.
- **D17 — Estado por turno en el estado del grafo, reiniciado en `coordinate`.** Los nodos se comunican por el estado y
  el `Send`, aunque el checkpointer guarde más por mensaje. *Descartada:* volver a un nodo único para no guardarlo — es
  la arquitectura que el usuario descartó.
- **D18 — Batería `behavior_check` en proceso.** Ve `AgentResult` y las opciones atendidas en ambos canales sin avisos
  reales. *Descartada:* por WebSocket — solo cubre el web y no ve la opción atendida.

## 6. Estrategia de tests
Todos sin BD ni red. `tests/fakes.py`: `FakeAgentLLM` guioniza `coordinate` y los pasos de `step` por área y cuenta las
llamadas de cada tipo; `FakeRetriever` con candidatos y búsquedas por área.

- **Unidad — `tests/behavior_test.py` (nuevo):** opciones (máximo 3, orden único, empate alfabético, texto repetido),
  textos numerados sin respuestas ni pasos, pregunta de áreas con y sin áreas, `can_clarify`, `chosen` con varias FAQ y
  procedimientos, `fixed_text`, `combine` (una, varias y parcial), `requester_key`.
- **Unidad — `tests/gemini_llm_test.py`:** `build_coordinator_messages` sin contenido de FAQ, con etiquetas de opciones
  solo del usuario y línea de oferta solo con `offer_pending`; `build_area_messages` solo con su área (RF-57);
  conversión de `CoordinatorOutput` y de `tool_calls`.
- **Unidad — `tests/retriever_test.py`:** `scope_signals` sin respuestas ni pasos, candidatos entre umbrales y señal del otro ámbito; `search_area` filtra por área y reutiliza el embedding (el `FakeEmbedder` no se llama); búsquedas de las tools; `read_clarify_similarity`
  ausente, no numérico y ≥ umbral de respuesta, con aviso en el log.
- **Unidad — `tests/sub_agent_test.py` (se recupera y se adapta):** respuesta en 1 paso con lo encontrado en su área; búsqueda y
  respuesta en 2; tope de pasos; guardarraíl sin evidencias; lo elegido cuenta como evidencia; `iniciar_procedimiento`
  terminal (`ask`, `sent`, `failed`, `gave_up`); las tools no ven otras áreas.
- **Grafo — `tests/agent_graph_test.py` (se reescribe):** cada nivel de RF-39 frente al siguiente; `llm.coordinate` y `scope_signals` se lanzan a la vez (dobles con eventos); respaldo de enrutado con `own_area_ids`; delegación en
  paralelo a dos áreas y combinación; respuesta parcial; procedimiento en curso enruta a su área sin pasar por las
  `area_ids`; elección enruta al área de la opción; recuento de llamadas (saludo = 1; FAQ = 2; dos áreas = 1 + 1 + 1;
  nunca más de 1 + 4 por área, RNF-1). Casos límite con test propio: saludo tras aclaración, pregunta de áreas →
  opciones → "sin respuesta", opción inactiva, «2» sin aclaración, otra persona del hilo elige, saludo durante un
  procedimiento sin tocar los intentos, texto fijo ausente, solo el otro ámbito, web sin áreas internas (RNF-4). Se
  conservan los casos de la spec 001: memoria e hilos aislados, seguimiento con contexto, auditor, guardarraíl.
- **Servicio — `tests/chat_orchestrator_test.py`:** mensajes fijos y aclaraciones en ambos canales sin aviso ni oferta;
  oferta aceptada y rechazada por texto; saludo en `collecting_contact`; `queued`; proveedor caído ante «hola»;
  "sin respuesta" fuera de horario tras aclaración fallida.
- **CLI — `tests/behavior_check_test.py` (nuevo).**
- **Migración:** `uv run alembic upgrade head` y `downgrade -1` en local, a mano.
- **Despliegue:** `behavior_check` en ambos ámbitos, `jailbreak_check`, 10 preguntas legítimas, demo de 8 pasos y
  prueba de carga de 50 sesiones para fijar RNF-2.

## 7. Orden de implementación
1. Migración de datos y `load_catalog` con textos fijos y `area_names`; tests.
2. `behavior.py` con `tests/behavior_test.py`.
3. Recuperador: `scope_signals`, `search_area`, búsquedas de las tools, `get_faq`, `read_clarify_similarity`; tests.
4. `llm.py`: `coordinate`, `step` (de `60a517e^`), constructores de mensajes; tests.
5. `tools.py` y `sub_agent.py` (de `60a517e^`) con lo encontrado en el área, lo elegido y la tool terminal; tests.
6. Grafo de 4 nodos con el comportamiento de la spec 001 (respuesta, mixta, persona, manipulación, procedimiento,
   auditor, memoria); tests del grafo en verde. **Medición local de latencia** con 50 sesiones y aviso al usuario
   antes de seguir (R3).
7. Grafo: mensajes fijos, fuera de tema, solo el otro ámbito y oferta.
8. Grafo: aclaraciones, elección y estado por usuario.
9. Orquestador: oferta por texto y fases que se mantienen.
10. `behavior_check`, `audit.py`, `jailbreak_check`; README y nota en el plan 001; `uv run pyright` y `uv run pytest`.
11. Despliegue: reescribir los prompts de coordinador (R1), calibrar `rag_clarify_similarity` (R2), baterías, demo y
    prueba de carga; el usuario fija RNF-2.

## 8. Matriz de cobertura
| RF | Módulos | Tests |
|---|---|---|
| RF-1 | migración, `graph.load_catalog` | `agent_graph_test` |
| RF-2 | `graph.load_catalog` (sin caché) | `agent_graph_test` |
| RF-3 | `graph.coordinate` | `agent_graph_test` (`caplog`) |
| RF-4 | `graph.coordinate` | `agent_graph_test` |
| RF-5 | `llm.CoordinatorOutput`, `graph.coordinate` | `agent_graph_test`, `chat_orchestrator_test` |
| RF-6 | `behavior.fixed_text` | `behavior_test` |
| RF-7 | `llm.CoordinatorOutput`, `graph.coordinate` | `agent_graph_test`, `chat_orchestrator_test` |
| RF-8 | `llm.CoordinatorOutput` (descripción), `graph.route` | `agent_graph_test` |
| RF-9 | `graph.coordinate`, `chat_orchestrator` | `chat_orchestrator_test` |
| RF-10 | `retriever.scope_signals`, `graph.finalize` | `retriever_test`, `agent_graph_test` |
| RF-11 | `behavior.build_options` | `behavior_test` |
| RF-12 | `behavior.build_options` | `behavior_test` |
| RF-13 | `behavior.build_options` | `behavior_test` |
| RF-14 | `behavior.options_text` | `behavior_test` |
| RF-15 | `behavior.options_text` | `behavior_test` |
| RF-16 | `behavior.areas_question`, `graph.finalize` | `behavior_test`, `agent_graph_test` |
| RF-17 | `behavior.can_clarify` | `behavior_test`, `agent_graph_test` |
| RF-18 | `behavior.can_clarify` | `behavior_test`, `agent_graph_test` |
| RF-19 | `graph.finalize` | `agent_graph_test` |
| RF-20 | `retriever.build_faq_retriever` | `retriever_test` |
| RF-21 | `retriever.read_clarify_similarity` | `retriever_test` |
| RF-22 | `retriever.read_clarify_similarity` | `retriever_test` |
| RF-23 | `llm.CoordinatorOutput` (`chosen_options`) | `gemini_llm_test`, `behavior_check` |
| RF-24 | `behavior.requester_key`, `AgentState.clarifications` | `agent_graph_test` |
| RF-25 | `graph.route` (`granted`), `tools`, `retriever.get_faq` | `sub_agent_test`, `agent_graph_test` |
| RF-26 | `graph.route`, `tools.iniciar_procedimiento` | `sub_agent_test`, `agent_graph_test` |
| RF-27 | `behavior.chosen`, `behavior.combine` | `behavior_test`, `agent_graph_test` |
| RF-28 | `behavior.chosen` | `behavior_test` |
| RF-29 | `behavior.OTHER_PROCEDURES`, `graph.finalize` | `behavior_test`, `agent_graph_test` |
| RF-30 | `llm.CoordinatorOutput` (descripción) | `gemini_llm_test`, `behavior_check` |
| RF-31 | `llm.CoordinatorOutput` (descripción) | `gemini_llm_test`, `behavior_check` |
| RF-32 | `graph.finalize` | `agent_graph_test` |
| RF-33 | `graph.finalize` | `agent_graph_test` |
| RF-34 | `llm.build_coordinator_messages`, `graph.route` | `gemini_llm_test`, `agent_graph_test` |
| RF-35 | `llm.CoordinatorOutput`, `graph.coordinate` | `agent_graph_test`, `chat_orchestrator_test` |
| RF-36 | `graph.coordinate` (D12) | `agent_graph_test` |
| RF-37 | `behavior.fixed_text` | `behavior_test` |
| RF-38 | `graph.coordinate`, `chat_orchestrator` | `chat_orchestrator_test` |
| RF-39 | `graph.coordinate`, `graph.route`, `graph.finalize` | `agent_graph_test` |
| RF-40 | `graph.finalize` | `agent_graph_test` |
| RF-41 | `llm.build_coordinator_messages`, `chat_orchestrator` | `chat_orchestrator_test` |
| RF-42 | `llm.build_coordinator_messages`, `chat_orchestrator` | `chat_orchestrator_test` |
| RF-43 | `graph.coordinate`, `chat_orchestrator` | `agent_graph_test`, `chat_orchestrator_test` |
| RF-44 | `chat_orchestrator`, `routers/web_chat` (sin cambios) | `chat_orchestrator_test`, `web_chat_ws_test` |
| RF-45 | `tools` (evidencias), `sub_agent` (guardarraíl) | `sub_agent_test` |
| RF-46 | `sub_agent` (guardarraíl), `graph.finalize` | `sub_agent_test`, `agent_graph_test` |
| RF-47 | `graph.finalize` (auditor), `audit.INTERNAL_NAMES` | `agent_graph_test`, `audit_test` |
| RF-48 | `graph.coordinate`, `graph.finalize` | `agent_graph_test` |
| RF-49 | `llm` (descripciones y `build_area_messages`) | `gemini_llm_test`, `behavior_check` |
| RF-50 | `graph` (`START → coordinate`) | `agent_graph_test` |
| RF-51 | `graph.coordinate` | `agent_graph_test` |
| RF-52 | `graph.route` (con respaldo de `own_area_ids`) | `agent_graph_test` |
| RF-53 | `graph.route` (nivel 7) | `agent_graph_test` |
| RF-54 | `graph.route` (nivel 8) | `agent_graph_test` |
| RF-55 | `graph.area_agent`, `sub_agent` | `agent_graph_test` |
| RF-56 | `retriever.search_area`, `tools.AreaToolbox`, `retriever.search_area_*` | `sub_agent_test`, `retriever_test` |
| RF-57 | `llm.build_area_messages`, `graph.route` | `gemini_llm_test`, `agent_graph_test` |
| RF-58 | `graph.route` (`Send`) | `agent_graph_test` (dos áreas en un superpaso) |
| RF-59 | `behavior.combine`, `graph.finalize` | `behavior_test`, `agent_graph_test` |
| RF-60 | `graph.finalize` | `agent_graph_test` |
| RF-61 | `chat_orchestrator.handle_web_message` | `chat_orchestrator_test` |
| RNF-1 | `graph`, `sub_agent` (`max_steps`) | `agent_graph_test`, `sub_agent_test` |
| RNF-2 | — | prueba de carga local (paso 6) y en el despliegue (paso 11) |
| RNF-3 | migración, constantes de `behavior` | revisión en el PR |
| RNF-4 | `Catalog.area_names` por ámbito | `agent_graph_test` |
| RNF-5 | `cli/behavior_check` | `behavior_check_test`, ejecución en el despliegue |

## 9. Riesgos y dudas
- **R1 — Prompts de la BD con otro papel.** `internal_agent` y `external_agent` hoy instruyen una respuesta única; deben
  pasar a instruir al coordinador (clasificar y delegar). No se versionan. *Mitigación:* las descripciones de
  `CoordinatorOutput` llevan las reglas; en el paso 11 se reescriben los prompts y se repiten `behavior_check` y
  `jailbreak_check`.
- **R2 — Calibración del umbral de aclaración** (0.55). *Mitigación:* medir las frases de la demo con las FAQ reales y
  ajustar la property sin desplegar.
- **R3 — Latencia (RNF-2).** Con D3 y D7 el camino de una FAQ es: llamada 1 (embedding y señales en paralelo) + SQL del
  área + llamada 2 (antes del rediseño eran 3 llamadas en serie, p95 8,69 s; con 1, p95 ≤ 4,75 s). Un saludo, un cierre
  o un fuera de tema solo hacen la llamada 1. El enrutado del coordinador depende de la descripción de cada área
  (`business_area.description`). *Mitigación:* medición local en el paso 6 y aviso al usuario con los números antes de seguir;
  el umbral definitivo lo fija el usuario con la prueba en el despliegue.
- **R4 — Frontend web.** Si deshabilita el texto durante la oferta o el formulario, RF-41 a RF-43 no se pueden ejercer.
  **Estado (2026-10-07, T-1):** no hay frontend de este chatbot en el workspace ni en la cuenta de GitHub, y el usuario no
  sabe aún cómo será. Queda pendiente de verificar cuando exista; el backend implementa igual.
- **R5 — Hilos guardados antes del despliegue.** No tienen los campos nuevos; se leen vacíos. Los tipos nuevos van en
  `CHECKPOINT_TYPES`.
- **R6 — Hueco: saludo con la oferta de ejecutivo pendiente.** **Decisión del usuario (2026-10-07, T-2):** la oferta se
  mantiene; queda en RF-61 de la spec.
- **R7 — Hueco: otro ámbito con candidatos propios.** **Decisión del usuario (2026-10-07, T-2):** fuera de tema (D12);
  queda en RF-36 de la spec.
- **R8 — Concurrencia en un space de grupo.** Dos mensajes a la vez en el mismo hilo: el checkpointer guarda la última
  escritura. Riesgo existente desde la spec 001; se acepta.
- **R9 — Más escrituras al checkpointer y más llamadas a Gemini.** 4 superpasos por mensaje y hasta 1 + 4 llamadas por
  área. *Mitigación:* la prueba de carga mide el pool de la BD y los errores de cuota de Gemini (`429`).
