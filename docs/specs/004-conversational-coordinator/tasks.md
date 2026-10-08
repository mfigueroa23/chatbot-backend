# Tareas 004 — Coordinador conversacional de una sola voz (chatbot-backend)

**Spec:** `spec.md` · **Plan:** `plan.md` · **Estado:** 38/39 hechas
Cada tarea dura menos de 30 min y deja los tests en verde. Se hacen en orden; `[P]` = puede ir en paralelo con la anterior.
"Verde" significa `uv run pyright` con 0 errores y `uv run pytest` sin fallos. Ningún test se conecta a la BD ni a la red
(constitución, punto 6). Los dobles compartidos viven en `tests/fakes.py`. Las fases 1 a 5 añaden piezas nuevas sin
cambiar el grafo vigente; la fase 6 lo sustituye.

## Fase 1 — Datos y catálogo
- [x] **T-1 — Leer los temas y trámites de cada área** · RF-9, RF-57 · ~20 min
  `get_area_topics(session, area_ids, limit)` en `src/services/business_data.py`: nombres de FAQ y procedimientos activos por área, por id, acotados por `limit`, sin respuestas ni pasos.
  Hecho cuando: `uv run pytest -q tests/business_data_test.py -k topics` pasa con dos áreas, el tope y FAQ inactivas excluidas.
- [x] **T-2 — Ampliar el catálogo con los prompts y temas de la spec 004** · RF-6, RF-9, RF-10, RF-56 · ~25 min
  `Catalog` añade `coordinator_prompt` (`{scope}_coordinator`), `scope_prompt` (`{scope}_agent`) y `topics` por área; `load_catalog` lee `scope_topics_per_area` (50) y solo áreas de su ámbito. Los campos viejos se mantienen hasta la fase 6.
  Hecho cuando: `uv run pytest -q tests/business_data_test.py -k "load_catalog and coordinador"` pasa con los prompts presentes y ausentes.

## Fase 2 — Control posterior
- [x] **T-3 — Devolver los datos personales con su valor** · RF-53 · ~15 min
  `personal_data_values(text)` en `src/agents/audit.py`; `personal_data_leaks` pasa a apoyarse en ella.
  Hecho cuando: `uv run pytest -q tests/audit_test.py -k personal_data` pasa, incluidos los tests existentes.
- [x] **T-4 — Detectar promesas de seguimiento y acciones afirmadas** · RF-54, RF-55 · ~20 min [P]
  `FUTURE_PROMISES`/`future_promises` («te avisaré», «te contactaremos», «le notificaremos»…) y `CLAIMED_ACTIONS`/`claimed_actions` («envié tu solicitud», «ya avisé al área», «quedaste en la cola»…).
  Hecho cuando: `uv run pytest -q tests/audit_test.py -k "promesa or accion"` pasa con frases de tú y de usted y un texto limpio.
- [x] **T-5 — Componer la revisión del texto final** · RF-13, RF-51, RF-53, RF-54, RF-55 · ~25 min
  `review(text, prompts, names, evidence, delivered) -> list[str]`; `INTERNAL_NAMES` añade `consultar_areas`, `avisar_area`, `ofrecer_ejecutivo` y `responder_oferta`.
  Hecho cuando: `uv run pytest -q tests/audit_test.py -k review` pasa con dato en la evidencia (permitido) y fuera (rechazado), promesa y acción con y sin entrega, y nombres prohibidos.

## Fase 3 — Agentes de área en modo contenido
- [x] **T-6 — Pedir a los agentes de área contenido para el coordinador** · RF-22 · ~15 min
  `build_area_messages` en `src/agents/llm.py`: sin persona y con la instrucción de generar contenido para el coordinador.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k area_messages` pasa y el mensaje no contiene la persona.
- [x] **T-7 — Volver informativos los textos de los procedimientos** · RF-29, RF-31, RF-33 · ~15 min [P]
  `MISSING_DATA`, `INVALID_DATA` y `REQUEST_SENT` en `src/agents/procedure_flow.py` nombran el procedimiento, los datos y el área como información para el coordinador; validación, intentos y plantilla sin cambios.
  Hecho cuando: `uv run pytest -q tests/procedure_flow_test.py` pasa.
- [x] **T-8 — Devolver la evidencia de cada agente de área** · RF-22, RF-23, RF-25 · ~20 min
  `AreaAnswer` añade `faqs` y `procedures` usados en `src/agents/sub_agent.py`; el guardarraíl de evidencia no cambia.
  Hecho cuando: `uv run pytest -q tests/sub_agent_test.py -k evidencia` pasa y `tests/sub_agent_test.py` sigue en verde.

## Fase 4 — Agente de ámbito
- [x] **T-9 — Convertir los mensajes del agente del canal en mensajes del agente de ámbito** · RF-9, RF-10, RF-19 · ~20 min
  `build_coordinator_messages` actual pasa a llamarse `build_scope_messages` e incluye los temas de cada área; se actualizan su llamada en `graph.py` y sus tests.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k scope_messages` pasa con temas solo del ámbito y la suite sigue verde.
- [x] **T-10 — Añadir la decisión del agente de ámbito** · RF-11, RF-12 · ~20 min
  `ScopeDecision(area_ids, consulta, catalogo)` y `GeminiAgentLLM.decide_scope(messages)` con salida estructurada; `AgentLLM` la declara.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k decide_scope` pasa con conversión y error del proveedor.
- [x] **T-11 — Ampliar los dobles del modelo** · (habilita RF-1 a RF-58) · ~20 min
  `FakeAgentLLM` en `tests/fakes.py`: `decide_scope` guionizado (`scope=`), `coordinator_steps` guionizados y, sin guion, un coordinador que llama `consultar_areas` con la pregunta y responde con el contenido recibido.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k fake` pasa y la suite sigue verde.
- [x] **T-12 — Añadir el presupuesto de llamadas** · RNF-1 · ~15 min
  `CallBudget(limit)` en `src/agents/llm.py` con `spend()`; al agotarse lanza `LlmUnavailableError` y registra un aviso.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k presupuesto` pasa.
- [x] **T-13 — Crear el agente de ámbito con derivación a las áreas** · RF-11, RF-14, RF-19 · ~30 min (depende de T-8, T-10, T-12)
  `run_scope_agent` en `src/agents/scope_agent.py`: decisión en paralelo con `scope_signals`, respaldo por coincidencias, procedimiento en curso a su área y agentes de área en paralelo; devuelve `ScopeReport`.
  Hecho cuando: `uv run pytest -q tests/scope_agent_test.py -k "elige or respaldo or en_curso"` pasa.
- [x] **T-14 — Responder el catálogo del ámbito** · RF-10, RF-12, RF-13 · ~20 min
  Con `catalogo`, `run_scope_agent` devuelve los temas y trámites sin llamar a las áreas; el agente externo nunca recibe áreas internas.
  Hecho cuando: `uv run pytest -q tests/scope_agent_test.py -k "catalogo or externo"` pasa.

## Fase 5 — Coordinador
- [x] **T-15 — Crear los mensajes del coordinador** · RF-6, RF-19 · ~15 min
  Nuevo `build_coordinator_messages(prompt, persona, offer_pending, pending_name, history, question, history_messages)` sin áreas ni contenido.
  Hecho cuando: `uv run pytest -q tests/gemini_llm_test.py -k coordinador_mensajes` pasa y el mensaje no contiene temas ni respuestas.
- [x] **T-16 — Atar `consultar_areas` al agente de ámbito del canal** · RF-7, RF-8, RF-14 · ~25 min (depende de T-13)
  `CoordinatorToolbox` en `src/agents/coordinator.py` con `consultar_areas`; guarda evidencia, respuestas de área y estado del procedimiento.
  Hecho cuando: `uv run pytest -q tests/coordinator_test.py -k consultar` pasa con el ámbito fijado por el código.
- [x] **T-17 — Añadir `avisar_area` al coordinador interno** · RF-45, RF-46, RF-47, RF-48 · ~25 min
  Solo en el interno; usa `format_unanswered`, el space del área o `get_fallback_space`, y registra si se entregó.
  Hecho cuando: `uv run pytest -q tests/coordinator_test.py -k avisar` pasa con entrega, fallo, área sin space y canal web sin la herramienta.
- [x] **T-18 — Añadir `ofrecer_ejecutivo` y `responder_oferta` al coordinador web** · RF-39, RF-40, RF-41, RF-42 · ~25 min [P]
  Solo en el web; `ofrecer_ejecutivo` consulta `is_open` y deja la oferta o los canales; `responder_oferta` solo con oferta pendiente.
  Hecho cuando: `uv run pytest -q tests/coordinator_test.py -k "ofrecer or oferta"` pasa dentro y fuera de horario y sin oferta pendiente.
- [x] **T-19 — Escribir el bucle del coordinador** · RF-1, RNF-1 · ~25 min (depende de T-16)
  `run_coordinator(llm, toolbox, messages, budget) -> CoordinatorTurn`, con el patrón de `run_sub_agent` y el presupuesto compartido.
  Hecho cuando: `uv run pytest -q tests/coordinator_test.py -k "bucle or presupuesto"` pasa, incluido el presupuesto agotado.

## Fase 6 — Grafo
> Nota de implementación (2026-10-08): sustituir el grafo rompe también los tests del orquestador y de las CLIs, que
> dependían de los outcomes y dobles de la spec 002/003. Para no dejar un commit en rojo, T-20 a T-31 (fases 6, 7 y las
> CLIs de la 8) se entregaron en un único commit en verde; T-20 no fue un commit aparte que solo tocara `tests/`.
- [x] **T-20 — Retirar los tests de requisitos sustituidos** · (habilita RF-1 a RF-58) · ~25 min
  Quitar los tests de clasificación, mensajes fijos, aclaración y elección, prioridad de RF-39, `converse` y aviso automático en `agent_graph_test`, `behavior_test`, `gemini_llm_test`, `chat_orchestrator_test`, `behavior_check_test` y `channel_strategy_test`, listándolos en el commit.
  Hecho cuando: la suite sigue verde y `git diff --stat` solo toca archivos de `tests/`.
- [x] **T-21 — Sustituir el grafo por el nodo `respond`** · RF-1, RF-2, RF-5, RF-6, RF-14, RF-19, RF-21, RF-24, RF-58 · ~30 min (depende de T-19)
  `build_graph` en `src/agents/graph.py` con un solo nodo que ejecuta el coordinador, guarda la pregunta y el texto enviado y devuelve los outcomes nuevos.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k "una_voz or seguimiento or dos_areas or otro_ambito or memoria"` pasa y la suite sigue verde.
- [x] **T-22 — Llevar los procedimientos por el grafo nuevo** · RF-28 a RF-38 · ~25 min
  Estado `pending_*` y `procedure_attempts` desde el toolbox; tercer intento: en el interno el coordinador ofrece avisar, en el web oferta de ejecutivo; notificación fallida → `notification_failed`.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k procedimiento` pasa con dato inválido, tercer intento en cada canal y fallo de notificación.
- [x] **T-23 — Aplicar el control posterior con reintento** · RF-33, RF-49, RF-51 a RF-55 · ~25 min
  `review` sobre el texto final; un reintento con nota de corrección; si persiste o hay fuga, `GENERIC_REFUSAL`; en el web, nombres de áreas internas prohibidos.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k control` pasa con fuga, dato personal, promesa y acción corregidos y no corregidos.
- [x] **T-24 — Forzar la oferta en el web sin evidencia** · RF-25, RF-39 · ~20 min
  Si se consultaron áreas, ninguna aportó evidencia y no se llamó `ofrecer_ejecutivo`, el resultado lleva la oferta; nunca en el interno.
  Hecho cuando: `uv run pytest -q tests/agent_graph_test.py -k oferta_forzada` pasa en ambos canales.
- [x] **T-25 — Eliminar el código sustituido** · RF-2, RF-20, RF-21 · ~25 min
  Fuera `CoordinatorKind`/`CoordinatorOutput`/`coordinate`, `converse`, `FIXED_KINDS`, aclaraciones y `combine` de `behavior.py`; `CHECKPOINT_TYPES` mantiene los tipos viejos.
  Hecho cuando: `grep -rn "CoordinatorOutput\|converse\|options_text" src` no devuelve nada y la suite sigue verde.

## Fase 7 — Orquestador y Google Chat
- [x] **T-26 — Responder el canal interno con el resultado del coordinador** · RF-3, RF-4, RF-45 · ~20 min
  `build_agent_context` lee `agent_max_model_calls` (100); `handle_internal_message` devuelve `result.reply` o `GENERIC_REFUSAL` sin `InternalStrategy`.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k interno` pasa, incluidos proveedor caído y mensajes vacío y largo.
- [x] **T-27 — Responder el chat web con oferta, canales y fases** · RF-34, RF-39 a RF-44 · ~30 min
  `offer_human` dentro y fuera de horario, `offer_accepted`/`offer_declined`, `notification_failed` con canales; un mensaje normal no cambia la fase; fuera `FIXED_OUTCOMES` y `MIXED_SCOPE`.
  Hecho cuando: `uv run pytest -q tests/chat_orchestrator_test.py -k web` y `uv run pytest -q tests/web_chat_ws_test.py` pasan.
- [x] **T-28 — Retirar el aviso automático del canal interno** · RF-45 · ~15 min
  Eliminar `InternalStrategy.on_no_answer` y reducir `ExternalStrategy` a horario y canales en `src/agents/strategies.py`.
  Hecho cuando: `grep -n "InternalStrategy" -r src` no devuelve nada y `uv run pytest -q tests/channel_strategy_test.py` pasa.
- [x] **T-29 — Redactar el saludo al añadir el bot** · RF-2, RF-15 · ~20 min
  `handle_event` en `src/services/google_chat.py` ejecuta el coordinador con una nota de sistema en lugar del texto fijo.
  Hecho cuando: `uv run pytest -q tests/google_chat_test.py -k added_to_space` pasa y la respuesta es el texto del coordinador.

## Fase 8 — Baterías y cierre
- [x] **T-30 — Dejar `behavior_check` con la batería de variedad** · RNF-4 · ~20 min
  Retirar clasificación y elección de `src/cli/behavior_check.py`; `--variety N` en ambos ámbitos.
  Hecho cuando: `uv run pytest -q tests/behavior_check_test.py` pasa y `uv run python -m src.cli.behavior_check --help` termina con 0.
- [x] **T-31 — Ajustar el informe de `jailbreak_check`** · RNF-5 · ~15 min [P]
  El resumen deja de contar la negativa genérica como única negativa válida; sin cambios en la detección de fugas.
  Hecho cuando: `uv run pytest -q tests/jailbreak_check_test.py` pasa.
- [x] **T-32 — Actualizar el README** · RF-56 · ~20 min
  Diagrama de tres niveles, keys `{scope}_coordinator`/`{scope}_agent`/`area_rules` y su contenido esperado, `agent_max_model_calls`, `scope_topics_per_area` y `rag_clarify_similarity` retirada.
  Hecho cuando: `grep -c "internal_coordinator\|agent_max_model_calls\|scope_topics_per_area" README.md` da al menos 3.
- [x] **T-33 — Verificación completa** · todos · ~15 min
  `uv run pyright` y `uv run pytest` (AGENTS.md); cada archivo de tests de la matriz del plan existe y recoge tests.
  Hecho cuando: pyright da 0 errores, pytest no tiene fallos y `uv run pytest --collect-only -q tests/scope_agent_test.py tests/coordinator_test.py` recoge tests.

## Fase 9 — Despliegue de prueba
- [x] **T-34 — Redactar los prompts de la BD para tu aprobación** · RF-15 a RF-18, RF-20, RF-26 a RF-28, RF-50, RNF-3 · ~30 min
  Textos de `internal_coordinator`, `external_coordinator`, `internal_agent`, `external_agent` y `area_rules` según D9, en un archivo fuera del repo.
  Hecho cuando: apruebas los cinco textos.
- [x] **T-35 — Cargar los prompts en local y en remoto** · RF-56 · ~20 min (depende de T-34)
  Con respaldo previo de `agent_prompt` en ambas BD, justo antes de fusionar.
  Hecho cuando: existen los respaldos y las cinco keys tienen el texto aprobado en ambas BD.
  Nota (2026-10-08): por decisión del usuario se cargaron en remoto antes de fusionar, con la 1.3.0 aún desplegada; también se aprobó y cargó una `internal_persona` más suelta (emojis ocasionales, largo variable). Los textos solo viven en la BD; los respaldos previos quedaron fuera del repo.
- [x] **T-36 — Ejecutar `jailbreak_check` en ambos canales** · RF-49, RF-50, RNF-5 · ~15 min
  `--scope internal` en proceso y el WebSocket del web, contra el despliegue.
  Hecho cuando: ambas ejecuciones terminan con código 0.
- [x] **T-37 — Medir la variedad de los saludos** · RNF-4 · ~15 min [P]
  `behavior_check --scope internal --variety 5` y `--scope external --variety 5`.
  Hecho cuando: ambas terminan con código 0.
- [x] **T-38 — Medir la latencia** · RNF-2 · ~30 min
  Prueba de carga de 50 sesiones con preguntas con FAQ y sin FAQ en ambos canales.
  Hecho cuando: R3 del plan registra p50, p95 y máximo, y fijas el umbral.
  Nota de la verificación en el despliegue (2026-10-08):
  - T-36: interno 24/24 sin fugas; web 22/24 en la primera vuelta por un falso positivo (la frase genérica
    «asistente virtual de Autofin,» coincidía con el prompt del área interna Ayuda General) y 24/24 tras quitarla de
    ese prompt.
  - T-37: interno 5/5 y web 4/5 distintos, pero el web tuteaba en 3 de 5; tras añadir el trato de usted a
    `external_coordinator`, web 5/5 distintos y todos de usted.
  - T-38: el pod (256 MiB, 300m) cayó dos veces por memoria al correr baterías dentro y saturaba la CPU con 50 sesiones;
    se subió a 1 CPU y 192/512 MiB en el repo de manifiestos del clúster. Cifras en R3 del plan; RNF-2 fijado en 15 s.
  - Datos remotos corregidos: «Servicio al Cliente» pasa a área externa (el web no tenía ninguna); se crea el área
    interna «Proyectos» sin space. Pendiente: ninguna área tiene space de Google Chat (la app solo es miembro de dos
    mensajes directos), así que trámites y avisos a pedido fallan al notificar.
- [ ] **T-39 — Ejecutar la demo manual** · RF-12 a RF-21, RF-26, RF-27, RF-50, RNF-3 · ~30 min
  Los mensajes de los criterios de finalización de la spec en Google Chat y en el web.
  Hecho cuando: cada mensaje da el resultado esperado y apruebas el tono.

## Cobertura
| RF | Tareas |
|---|---|
| RF-1 | T-19, T-21 |
| RF-2 | T-21, T-25, T-29 |
| RF-3 | T-26 |
| RF-4 | T-26 |
| RF-5 | T-21 |
| RF-6 | T-2, T-15, T-21 |
| RF-7 | T-16 |
| RF-8 | T-16 |
| RF-9 | T-1, T-2, T-9 |
| RF-10 | T-2, T-9, T-14 |
| RF-11 | T-10, T-13 |
| RF-12 | T-10, T-14, T-39 |
| RF-13 | T-5, T-14, T-39 |
| RF-14 | T-13, T-16, T-21, T-39 |
| RF-15 | T-29, T-34, T-39 |
| RF-16 | T-34, T-39 |
| RF-17 | T-34, T-39 |
| RF-18 | T-34, T-39 |
| RF-19 | T-9, T-13, T-15, T-21, T-39 |
| RF-20 | T-25, T-34, T-39 |
| RF-21 | T-21, T-25, T-39 |
| RF-22 | T-6, T-8 |
| RF-23 | T-8 |
| RF-24 | T-21 |
| RF-25 | T-8, T-24 |
| RF-26 | T-34, T-39 |
| RF-27 | T-34, T-39 |
| RF-28 | T-22, T-34 |
| RF-29 | T-7, T-22 |
| RF-30 | T-22 |
| RF-31 | T-7, T-22 |
| RF-32 | T-22 |
| RF-33 | T-7, T-22, T-23 |
| RF-34 | T-22, T-27 |
| RF-35 | T-22 |
| RF-36 | T-22 |
| RF-37 | T-22 |
| RF-38 | T-22 |
| RF-39 | T-18, T-24, T-27 |
| RF-40 | T-18, T-27 |
| RF-41 | T-18, T-27 |
| RF-42 | T-18, T-27 |
| RF-43 | T-27 |
| RF-44 | T-27 |
| RF-45 | T-17, T-26, T-28 |
| RF-46 | T-17 |
| RF-47 | T-17 |
| RF-48 | T-17 |
| RF-49 | T-23, T-36 |
| RF-50 | T-34, T-36, T-39 |
| RF-51 | T-5, T-23 |
| RF-52 | T-23 |
| RF-53 | T-3, T-5, T-23 |
| RF-54 | T-4, T-5, T-23 |
| RF-55 | T-4, T-5, T-23 |
| RF-56 | T-2, T-32, T-35 |
| RF-57 | T-1, T-2 |
| RF-58 | T-21 |
| RNF-1 | T-12, T-19 |
| RNF-2 | T-38 |
| RNF-3 | T-34, T-39 |
| RNF-4 | T-30, T-37 |
| RNF-5 | T-31, T-36 |

| Módulo del plan | Tareas |
|---|---|
| `src/services/business_data.py` | T-1 |
| `src/agents/graph.py` | T-2, T-9, T-21 a T-25 |
| `src/agents/audit.py` | T-3, T-4, T-5 |
| `src/agents/llm.py` | T-6, T-9, T-10, T-12, T-15, T-25 |
| `src/agents/procedure_flow.py` | T-7 |
| `src/agents/sub_agent.py`, `src/agents/tools.py` | T-8 |
| `src/agents/scope_agent.py` | T-13, T-14 |
| `src/agents/coordinator.py` | T-16 a T-19 |
| `src/agents/behavior.py` | T-25 |
| `src/agents/strategies.py` | T-28 |
| `src/services/chat_orchestrator.py` | T-26, T-27 |
| `src/services/google_chat.py` | T-29 |
| `src/cli/behavior_check.py` | T-30 |
| `src/cli/jailbreak_check.py` | T-31 |
| `README.md` | T-32 |
| Prompts de `agent_prompt` | T-34, T-35 |
