# Tareas 003 — Conversación libre en Google Chat (chatbot-backend)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 1/29 hechas
Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` = puede ir en paralelo con la anterior.
"Verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test se conecta a la BD ni a la red
(constitución, punto 6). Los dobles compartidos viven en `tests/fakes.py`. "Grafo interno" es `build_graph(AreaScope.internal)`.

## Fase 0 — Decisiones pendientes
- [x] **T-1 — Cerrar con el usuario el hueco R1 (procedimiento agotado en Google Chat)** · RF-27 · ~10 min
  Preguntar si se aprueba la propuesta de R1 (texto redactado que ofrece avisar al área, sin avisar) o se mantiene el aviso automático.
  Hecho cuando: R1 del plan dice «Decisión del usuario» y, si se aprueba la propuesta, la spec tiene el RF correspondiente.

## Fase 1 — Datos
- [ ] **T-2 — Crear la migración de datos de la persona** · RF-2 · ~20 min
  `alembic/versions/<rev>_seed_internal_persona.py` con `down_revision = '20be34b82e76'`: key `internal_persona` en `agent_prompt` con la persona de la sección 3 del plan y `ON CONFLICT (key) DO NOTHING`; el downgrade la borra.
  Hecho cuando: en local, `uv run alembic upgrade head` deja `internal_persona` en `agent_prompt` y `uv run alembic downgrade -1` la quita.
- [ ] **T-3 — Leer la persona en el catálogo** · RF-2, RF-3 · ~15 min
  `Catalog.persona: str | None`; `load_catalog` lee `{scope}_persona` con `get_agent_prompt`, sin caché.
  Hecho cuando: `uv run pytest -q tests/business_data_test.py -k persona` pasa con la persona presente y ausente.

## Fase 2 — Reglas deterministas
- [ ] **T-4 — Implementar `mentions_area` y `ensure_areas`** · RF-5, RF-20 · ~15 min
  En `src/agents/behavior.py`: detectar si un texto nombra alguna área (sin distinguir mayúsculas) y añadir la línea de áreas solo si no nombra ninguna.
  Hecho cuando: `uv run pytest -q tests/behavior_test.py -k "mentions_area or ensure_areas"` pasa con texto que nombra un área, que no nombra ninguna y sin áreas.
- [ ] **T-5 — Implementar `personal_data_leaks`** · RF-25 · ~25 min [P]
  En `src/agents/audit.py`: RUT con y sin puntos, correo y teléfono chileno (`+56` o 9 dígitos); devuelve la lista de tipos encontrados.
  Hecho cuando: `uv run pytest -q tests/audit_test.py -k personal_data` pasa con cada tipo y con un texto limpio que menciona montos y fechas.

## Fase 3 — Modelo (`src/agents/llm.py`)
- [ ] **T-6 — Añadir `text` y `about_assistant` a la decisión del agente del canal** · RF-11, RF-12, RF-21 · ~20 min
  `CoordinatorKind` con `about_assistant`; `text` en `CoordinatorOutput` y `CoordinatorReply`; la descripción de `kind` distingue identidad de manipulación y trata «avisa al área / que lo vea una persona» como `wants_human`.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k coordinate` pasa con `about_assistant` y con `text`, y la descripción contiene «IA» y «avisar al área».
- [ ] **T-7 — Añadir la persona a los mensajes del agente del canal y de los agentes de área** · RF-4, RNF-3 · ~20 min
  Parámetro `persona: str | None` en `build_coordinator_messages` (con la instrucción de redactar `text`) y en `build_area_messages`; sin persona, los mensajes no cambian.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k persona` pasa con y sin persona en ambos constructores.
- [ ] **T-8 — Crear `converse` y `build_converse_messages`** · RF-7, RF-8, RF-15, RF-25 · ~30 min
  `AgentLLM.converse(messages) -> str` con `ConverseOutput(text)`; con temas: pregunta natural que los propone en ese orden, sin numeración impuesta; sin temas: respuesta libre breve, aviso de no oficial si el tema es de Autofin, sin datos personales y con la cláusula de seguridad.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k converse` pasa con y sin temas, comprueba el orden de los temas y la conversión de la salida.
- [ ] **T-9 — Pasar la temperatura a `gemini_chat`** · RNF-4 · ~15 min
  `build_gemini_llm(session, temperature=0.0)` y `gemini_chat(model, api_key, timeout, temperature)`; la temperatura forma parte de la clave de `lru_cache`.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k temperature` pasa y dos temperaturas distintas dan clientes distintos.
- [ ] **T-10 — Ampliar los dobles del modelo** · (habilita RF-5 a RF-30) · ~15 min
  En `tests/fakes.py`: `FakeAgentLLM.converse` guionizado con contador `converse_calls`, incluido en `calls`.
  Hecho cuando: la suite sigue en verde y `uv run pytest -q tests/gemini_llm_test.py` no cambia de resultado.

## Fase 4 — Grafo: agente del canal conversacional
- [ ] **T-11 — Activar el modo conversacional y redactar saludo y cierre** · RF-1, RF-5, RF-6, RF-10, RF-24 · ~30 min
  `build_graph` fija `conversational` por el ámbito; en `coordinate`, `greeting` y `closing` responden su `text` auditado (el saludo con `ensure_areas`); vacío o con fuga ⇒ texto fijo; persona del catálogo en los mensajes.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k conversacional_saludo` pasa con texto, texto vacío y texto con fuga.
- [ ] **T-12 — Redactar tema ajeno y respuesta sobre el asistente** · RF-11, RF-18, RF-19, RF-20 · ~25 min
  `off_topic` y `about_assistant` con su `text` auditado y `ensure_areas` en el ajeno; con `own_area_ids` delegan en esas áreas.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "conversacional_ajeno or about_assistant"` pasa, incluido el caso con FAQ propia.
- [ ] **T-13 — Redactar la negativa con respaldo genérico** · RF-21, RF-22, RF-23, RF-24 · ~20 min
  `manipulation` responde su `text` auditado; vacío o con fuga ⇒ `GENERIC_REFUSAL`; nunca llama a agentes de área.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k conversacional_negativa` pasa con texto, vacío y con fuga.
- [ ] **T-14 — Comprobar que el grafo web no cambia** · RF-1 · ~15 min [P]
  Con el grafo web, `greeting`, `off_topic` y `manipulation` con `text` siguen respondiendo el texto fijo y la negativa genérica; sin respuesta sigue la spec 002.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k web_sin_cambios` pasa.

## Fase 5 — Grafo: `finalize` conversacional
- [ ] **T-15 — Redactar la aclaración con los temas candidatos** · RF-7, RF-9, RF-10 · ~30 min
  Sin respuestas, con candidatos y `can_clarify`: `converse` con las etiquetas de `build_options` en su orden; guarda la `Clarification`; texto vacío ⇒ plantilla de la spec 002; la elección se reconoce por texto.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k aclaracion_redactada` pasa con texto redactado, texto vacío y elección «la del seguro» en el turno siguiente.
- [ ] **T-16 — Dar la respuesta libre en lugar de "sin respuesta"** · RF-13, RF-14, RF-16, RF-18, RF-29 · ~30 min
  Sin candidatos, o con opciones pendientes sin elección: `converse` sin temas y outcome `free_answer`; nunca la pregunta de áreas; con FAQ sobre el umbral responde la FAQ.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k respuesta_libre` pasa con los cuatro casos.
- [ ] **T-17 — Auditar la respuesta libre y guardarla** · RF-24, RF-25, RF-30, RNF-1 · ~25 min
  Auditor y `personal_data_leaks` sobre la respuesta libre (fuga o dato personal ⇒ respaldo sin datos); el texto queda en la memoria; `converse` solo cuando ninguna área responde.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "libre_auditada or libre_memoria or llamadas_converse"` pasa.
- [ ] **T-18 — Ofrecer avisar al área cuando un procedimiento se agota** · RF-27, RF-31 · ~20 min (depende de T-1)
  En el grafo interno, `gave_up` llama a `converse` con la instrucción de procedimiento agotado (sin los datos entregados), responde ese texto auditado y no deja el resultado como `no_answer`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k procedimiento_agotado_interno` pasa y el orquestador no avisa al área en ese caso.

## Fase 6 — Orquestador
- [ ] **T-19 — Contexto conversacional con su temperatura** · RNF-4 · ~15 min
  `build_agent_context(..., conversational=False)` lee `conversation_temperature` (0.7) solo si es conversacional y la pasa a `build_gemini_llm`; `handle_internal_message` lo activa.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k temperatura` pasa para el canal interno y el web.
- [ ] **T-20 — Responder los nuevos resultados en Google Chat y avisar solo a pedido** · RF-17, RF-21, RF-22, RF-23, RF-27, RF-28 · ~25 min
  `rejected` con `reply` lo usa y sin él `GENERIC_REFUSAL`; `free_answer`, `about_assistant` y `clarify` devuelven su texto sin `InternalStrategy`; `wants_human` avisa al área; el proveedor caído sigue respondiendo no disponible.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k "interno_negativa or interno_libre or interno_aviso"` pasa y el `FakeNotifier` solo recibe el aviso de `wants_human`.

## Fase 7 — Baterías y cierre
- [ ] **T-21 — Ampliar `behavior_check` para el canal conversacional** · RF-11, RNF-4 · ~25 min
  Caso interno «¿eres IA o un vil robot?» → `about_assistant`; la clase `other` acepta `free_answer` y `clarify`; `--variety N` cuenta textos distintos de N saludos en hilos nuevos (falla si hay menos de 3 de 5).
  Hecho cuando: `uv run pytest -q tests/behavior_check_test.py -k "about_assistant or variety"` pasa.
- [ ] **T-22 — Añadir `jailbreak_check --scope internal`** · RF-21, RF-24, RNF-5 · ~25 min [P]
  Ejecuta la batería en proceso contra el grafo interno, con notificador que solo registra; el modo WebSocket sigue siendo el de por defecto.
  Hecho cuando: `uv run pytest -q tests/jailbreak_check_test.py -k internal` pasa con un grafo de dobles que no filtra y otro que sí.
- [ ] **T-23 — Actualizar el README** · RF-1, RF-2, RF-27 · ~15 min
  Modo conversacional de Google Chat, `internal_persona`, `conversation_temperature`, avisos al área solo a pedido y `jailbreak_check --scope internal`.
  Hecho cuando: `grep -c "internal_persona\|conversation_temperature\|--scope internal" README.md` da al menos 3.
- [ ] **T-24 — Verificación completa** · todos, RF-26 · ~15 min
  `uv run pyright` y `uv run pytest` (AGENTS.md); los tests de procedimientos (`sub_agent_test`, `procedure_flow_test`) siguen en verde sin cambios (RF-26).
  Hecho cuando: pyright da 0 errores, pytest no tiene fallos y cada test citado en la matriz del plan existe (`uv run pytest --collect-only -q`).

## Fase 8 — Despliegue de prueba
- [ ] **T-25 — Cargar el prompt `internal_agent` que pide redactar el texto** · RF-5, RF-6, RF-11, RF-19, RF-22 · ~20 min
  Con autorización del usuario: añadir al prompt `internal_agent` de la BD remota (y la local) la instrucción de redactar `text` con la persona; respaldo previo de `agent_prompt`.
  Hecho cuando: el respaldo existe y `behavior_check --scope internal` muestra textos redactados (no los fijos) en el saludo.
- [ ] **T-26 — Ejecutar `behavior_check` interno con variedad** · RF-11, RNF-4 · ~20 min
  `behavior_check --scope internal --variety 5` contra la BD remota, con `conversation_temperature` en 0.7.
  Hecho cuando: termina con código 0; si la clasificación falla, se baja `conversation_temperature` y se registra el valor en R2 del plan.
- [ ] **T-27 — Ejecutar `jailbreak_check --scope internal`** · RNF-5 · ~15 min [P]
  Contra la BD remota con el grafo interno.
  Hecho cuando: termina con código 0.
- [ ] **T-28 — Ejecutar la demo en Google Chat** · RF-15, RNF-3, todos · ~30 min
  Con la imagen desplegada: los 8 pasos de la spec, anotando el resultado de cada uno.
  Hecho cuando: los 8 pasos dan el resultado esperado y quedan anotados en R3 del plan.
- [ ] **T-29 — Medir la latencia del camino de respuesta libre** · RNF-1, RNF-2 · ~30 min
  Prueba de carga de 50 sesiones con preguntas sin FAQ, aparte de la de FAQ.
  Hecho cuando: R5 del plan registra p50, p95 y máximo del camino libre.

## Cobertura
| RF | Tareas |
|---|---|
| RF-1 | T-11, T-14, T-23 |
| RF-2 | T-2, T-3, T-23 |
| RF-3 | T-3 |
| RF-4 | T-7 |
| RF-5 | T-4, T-11, T-25 |
| RF-6 | T-11, T-25 |
| RF-7 | T-8, T-15 |
| RF-8 | T-8 |
| RF-9 | T-15 |
| RF-10 | T-11, T-15 |
| RF-11 | T-6, T-12, T-21, T-25, T-26 |
| RF-12 | T-6 |
| RF-13 | T-16 |
| RF-14 | T-16 |
| RF-15 | T-8, T-28 |
| RF-16 | T-16 |
| RF-17 | T-20 |
| RF-18 | T-12, T-16 |
| RF-19 | T-12, T-25 |
| RF-20 | T-4, T-12 |
| RF-21 | T-6, T-13, T-20, T-22 |
| RF-22 | T-13, T-20, T-25 |
| RF-23 | T-13, T-20 |
| RF-24 | T-11, T-13, T-17, T-22 |
| RF-25 | T-5, T-8, T-17 |
| RF-26 | T-24 |
| RF-27 | T-1, T-18, T-20, T-23 |
| RF-28 | T-20 |
| RF-29 | T-16 |
| RF-30 | T-17 |
| RF-31 | T-18, T-20 |
| RNF-1 | T-17, T-29 |
| RNF-2 | T-29 |
| RNF-3 | T-7, T-28 |
| RNF-4 | T-9, T-19, T-21, T-26 |
| RNF-5 | T-22, T-27 |

| Módulo del plan | Tareas |
|---|---|
| `src/agents/llm.py` | T-6 a T-9 |
| `src/agents/graph.py` | T-3, T-11 a T-18 |
| `src/agents/behavior.py` | T-4 |
| `src/agents/audit.py` | T-5 |
| `src/services/chat_orchestrator.py` | T-19, T-20 |
| `src/cli/behavior_check.py` | T-21 |
| `src/cli/jailbreak_check.py` | T-22 |
| migración `seed_internal_persona` | T-2 |
| `README.md` | T-23 |
