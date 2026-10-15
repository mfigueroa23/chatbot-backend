# Plan 001 — Respuesta diferida en Google Chat

Spec: [spec.md](spec.md) · Constitución: [docs/constitution.md](../../constitution.md)

## Contexto
Hoy `POST /api/v1/google-chat/events` (`src/routers/google_chat.py`) hace todo dentro de la petición HTTP:
verifica el token, lee los adjuntos, llama a `ask` (`src/services/assistant.py`) y, si se supera `google_timeout`,
responde `DEMORA`. La respuesta síncrona del complemento (`chat_reply`) es la única vía de salida.
El plan agrega una segunda vía: publicar mensajes nuevos con la API de Google Chat, reutilizando la cuenta de servicio
que ya se usa para descargar adjuntos (`service_account_token`, scope `chat.bot`).

## Flujo
```
evento ─► router: verificar token (401 si falla) ─► bienvenida / evento vacío (igual que hoy)
                │
                ▼
        servicio: lanzar tarea "procesar" (adjuntos + ask, con su propia sesión de BD,
                  acotada por el tiempo máximo total; devuelve SIEMPRE un texto: respuesta, DEMORA o NO_DISPONIBLE)
                │
        esperar la tarea hasta el umbral de aviso
          ├─ terminó  ─► respuesta síncrona en el hilo con el texto de la tarea          (RF-01)
          └─ no terminó ─► registrar tarea "entregar" y responder el AVISO síncrono       (RF-02, RF-03)
                              │
                              ▼
                     entregar: esperar la tarea "procesar" ─► mención (si es space) + texto
                               ─► crear mensaje nuevo en el space, sin hilo               (RF-04, RF-05, RF-07, RF-08)
                               ─► si la publicación falla: log, sin reintento             (RF-09)
```
La decisión "síncrono o diferido" se toma una sola vez, en el manejador, por eso cada solicitud produce un aviso como
máximo y un único mensaje final (RF-12).

## Módulos
| Módulo | Cambio | RF |
|---|---|---|
| `src/interfaces/google_chat.py` | Nuevo esquema `ChatUser` (`name`, `type`) y campo `sender` en `ChatMessage`, para poder mencionar al remitente. | RF-05 |
| `src/services/google_chat.py` | `create_message(space, texto, token, http)`: crea un mensaje nuevo en el space sin indicar hilo. `mention_of(event)`: devuelve `<users/…>` solo si el space no es `DIRECT_MESSAGE` y el evento trae remitente. `chat_token(session, http)`: obtiene el token de la cuenta de servicio, extraído de lo que hoy hace `read_files`. | RF-04, RF-05, RF-09 |
| `src/services/google_chat_reply.py` (nuevo) | Orquestación: `process` (adjuntos + `ask` con `asyncio.timeout(máximo)` y mapeo de excepciones a `DEMORA`/`NO_DISPONIBLE`), `answer` (espera hasta el umbral y decide entre la vía síncrona y la diferida), `deliver` (publica el resultado), registro de tareas pendientes y `cancel_pending()`. Se mueven aquí `read_files` y las constantes de mensajes; se agrega `AVISO`. | RF-01, RF-02, RF-03, RF-06, RF-07, RF-08, RF-10, RF-11, RF-12 |
| `src/routers/google_chat.py` | Queda delgado: verifica el token (401), atiende la bienvenida y los eventos vacíos, y delega en `answer`. Los errores antes de lanzar la tarea (properties, BD) siguen respondiéndose síncronos, como hoy. | RF-13, RF-01 |
| `main.py` | En el apagado del `lifespan`, llama a `cancel_pending()` y registra en el log cuántas solicitudes se perdieron. | (apoya la decisión D7) |
| `README.md` | Documenta `google_timeout` (nuevo significado) y `google_chat_notice_seconds`. | RF-06 |
| `pyproject.toml` | 3.1.5 → 3.2.0 (funcionalidad nueva), `uv sync`. | Constitución 9 |

## Modelo de datos
- **Tablas:** sin cambios en `src/models/` ni migraciones (fuera de alcance; constitución 5). `uv run alembic check` sin diferencias.
- **Historial:** sigue en el checkpointer de LangGraph con el mismo `thread_id = conversation_key(event)` del mensaje
  original, también en la vía diferida (RF-10). El mensaje diferido abre un hilo nuevo que no se vincula con la
  conversación (fuera de alcance).
- **Configuración (tabla `property`, valores cargados a mano como el resto):**

| Key | Significado | Si falta |
|---|---|---|
| `google_chat_notice_seconds` (nueva) | Umbral de aviso en segundos (RF-02, RF-06) | Se usa 10 |
| `google_timeout` (existente) | Pasa a ser el tiempo máximo total (RF-07). Hay que subir su valor (p. ej. 120) al desplegar | `NO_DISPONIBLE`, como hoy |

  Los dos tiempos se cuentan desde que empieza la tarea "procesar", después de verificar el token. Un valor no numérico
  se trata como error de configuración (`NO_DISPONIBLE`, igual que hoy). Si el aviso es ≥ al máximo, nunca se avisa
  y el comportamiento es el actual.
- **Esquema del evento (Pydantic, no BD):** `ChatMessage.sender: ChatUser | None` (`name = "users/…"`).
- **Estado en memoria:** un conjunto de tareas pendientes por proceso, que mantiene la referencia para que el recolector no las
  elimine y permite cancelarlas al apagar. No se persiste (D7).

## Decisiones
| # | Decisión | Por qué | Alternativa descartada |
|---|---|---|---|
| D1 | `asyncio.create_task` + `asyncio.wait(timeout=aviso)` en el manejador | La tarea ya está en curso cuando vence el umbral y la misma tarea termina en segundo plano. No hay trabajo duplicado. | `BackgroundTasks` de FastAPI: solo arranca **después** de enviar la respuesta, así que no permite comparar el tiempo contra el umbral. |
| D2 | La tarea abre su propia sesión (`SessionLocal`) | La `SessionDep` de la petición se cierra al devolver el aviso. | Reusar la sesión de la petición: quedaría cerrada a mitad del proceso. |
| D3 | Publicar con la API REST de Chat (`spaces.messages.create`) y el token `chat.bot` existente | Ya se usa esa cuenta y ese flujo para los adjuntos. Usa `httpx`, sin dependencias nuevas. Sin `thread`, el mensaje sale fuera del hilo (RF-04). | Cliente oficial `google-apps-chat`: es una dependencia nueva (requiere aprobación) y es síncrono en parte. |
| D4 | Umbrales en la tabla `property` (aviso nuevo; `google_timeout` reutilizado como máximo) | Toda la configuración de Google Chat ya vive ahí y la spec pide cambios sin redeploy. Reutilizar `google_timeout` evita dejar una property huérfana. | Variables en `Settings`: exigen redeploy. Una property nueva para el máximo dejaría `google_timeout` sin uso. **Se desvía de la constitución 6** (parámetros solo por `Settings`); requiere aprobación explícita, igual que la práctica actual. **Aprobada el 2026-10-15.** |
| D5 | Aviso con valor por defecto en código (10 s) | Desplegar sin cargar la property no rompe el endpoint. | Property obligatoria: si se olvida cargarla, todo respondería `NO_DISPONIBLE`. |
| D6 | `process` devuelve siempre un texto (respuesta o mensaje de error) | El mismo mapeo de errores sirve para la vía síncrona y la diferida (RF-07, RF-08). Al cancelar por el máximo, `ask` no llega a guardar la respuesta tardía en el historial. | Mapear errores por separado en el router y en la entrega: se duplica la lógica y es fácil que diverjan. |
| D7 | Tareas solo en memoria; al apagar se cancelan y se registran en el log | Es la decisión de la spec (mejor esfuerzo) y deja rastro de lo perdido. | Esperar a que terminen antes de apagar o usar una cola persistente: lo excluye la spec (durabilidad). |
| D8 | La mención se aplica a todo mensaje diferido (respuesta, demora, error) y se omite si no hay remitente | El usuario siempre sabe que el mensaje es para él, y no se falla por un dato ausente. | Mencionar solo en la respuesta: un error suelto en el space no dice a quién va dirigido. |
| D9 | Mover la orquestación a `services` | Constitución 2 (la lógica va en services). Además se puede probar sin HTTP. | Dejarla en el router: mezcla HTTP con tareas en segundo plano y es más difícil de probar. |
| D10 | Mantener el texto de `DEMORA` | La spec solo exige un mensaje de demora en español; el actual sigue siendo válido tras el máximo. | Texto nuevo configurable: alcance extra sin requisito. |

## Estrategia de tests
Todos los tests corren con `uv run pytest`, sin BD real, sin LLM y sin red (constitución 4). Se usan `monkeypatch` sobre `get_property`,
`ask`, `read_attachments`, `chat_token` y `create_message`, y `pytest.mark.anyio`, como en `tests/google_chat_test.py`.
Los tiempos se controlan con umbrales de milisegundos y con `asyncio.Event`, que deciden cuándo termina el `ask` falso.
Así ningún test espera tiempos reales.

| Test | Archivo | RF |
|---|---|---|
| Respuesta antes del umbral → `chat_reply` con la respuesta; no se llama `create_message` | `tests/google_chat_reply_test.py` | RF-01, RF-12 |
| `ask` bloqueado → la respuesta síncrona es `AVISO`; al liberar el evento, `create_message` recibe la respuesta | idem | RF-02, RF-03, RF-04 |
| `create_message` se llama con el `space` del evento y sin hilo | `tests/google_chat_test.py` (cliente `httpx` falso) | RF-04 |
| Mención al inicio en `SPACE`; sin mención en `DIRECT_MESSAGE` ni sin remitente | `tests/google_chat_test.py` | RF-05 |
| Valores leídos de `get_property`; si falta el aviso se usa 10; con aviso ≥ máximo nunca se avisa | `tests/google_chat_reply_test.py` | RF-06 |
| Tras el aviso, superar el máximo → se publica `DEMORA` y `ask` se cancela (no se publica su respuesta) | idem | RF-07, RF-12 |
| Tras el aviso, `ask` lanza `AgentNotFoundError` / `DatabaseUnavailableError` → se publica `NO_DISPONIBLE`; el log no tiene trazas hacia el usuario | idem | RF-08 |
| `create_message` lanza `httpx.HTTPError` → se registra en el log y se llama una sola vez | idem | RF-09 |
| La vía diferida llama a `ask` con el `thread_id` del mensaje original | idem | RF-10 |
| Dos eventos de la misma conversación con `ask` bloqueado → dos avisos y dos publicaciones | idem | RF-11 |
| `cancel_pending()` cancela las tareas en curso y vacía el registro | idem | (D7) |
| Sin token → 401 sin leer configuración (ya existe: `test_endpoint_sin_token_responde_401_antes_de_leer_la_configuracion`) | `tests/google_chat_test.py` | RF-13 |

Verificación manual (criterio de la spec): en un space y en un DM, con `google_chat_notice_seconds` bajo y `ask` real.
Hay que ver la respuesta rápida en el hilo, la respuesta lenta con aviso y mensaje nuevo con mención (en el space), y
la demora máxima con `DEMORA`.

## Cobertura de RF
| RF | Módulo(s) | Test |
|---|---|---|
| RF-01 | `google_chat_reply.answer`, router | ✔ |
| RF-02 | `google_chat_reply.answer` | ✔ |
| RF-03 | `google_chat_reply` (D1) | ✔ |
| RF-04 | `google_chat.create_message`, `deliver` | ✔ |
| RF-05 | interfaces `sender`, `google_chat.mention_of` | ✔ |
| RF-06 | `google_chat_reply` + `property` (D4, D5) | ✔ |
| RF-07 | `process` (timeout) + `deliver` | ✔ |
| RF-08 | `process` (mapeo de errores, D6) + `deliver` | ✔ |
| RF-09 | `deliver` | ✔ |
| RF-10 | `process` con `thread_id` original | ✔ |
| RF-11 | tarea por evento + registro de pendientes | ✔ |
| RF-12 | decisión única en `answer` | ✔ |
| RF-13 | router (sin cambios) | ✔ (existente) |

## Riesgos abiertos (no resueltos por este plan)
- Si falta o es inválida `google_chat_service_account_json`, el aviso se envía pero la respuesta no se puede publicar:
  solo queda el log (RF-09).
- Si Google reentrega un evento, se procesa dos veces; no hay deduplicación.
- Las ejecuciones simultáneas sobre el mismo `thread_id` pueden mezclar el historial (la spec solo excluye el orden).
- Una respuesta que supere el tamaño máximo de mensaje de Google Chat fallaría al publicarse.
- El pool del checkpointer tiene `max_size = 2`; con muchas solicitudes diferidas a la vez, las tareas esperan conexión.

## Cierre
`uv run pytest`, `uv run pyright` (0 errores), `uv run alembic check`, versión 3.2.0 y `uv sync`.

