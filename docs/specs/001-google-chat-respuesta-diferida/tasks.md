# Tareas 001 — Respuesta diferida en Google Chat

Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md)

Ordenadas por dependencia: una tarea solo empieza cuando sus dependencias están marcadas.
Cada tarea que cambia comportamiento incluye su test (constitución 4) y deja `uv run pyright` en 0 errores (constitución 3).

## Grafo

```
T00 ─► T01 ─► T02 ─┐
       T03 ────────┤
       T04 ─► T05 ─┼─► T07 ─► T08 ─┐
       T06 ────────┘       └─► T09 ─┼─► T11 ─► T12
                           T10 ─────┘
```

## Bloqueante

- [x] **T00 — Aprobar la desviación de la constitución 6 (D4)**
  - RF: RF-06
  - Depende de: —
  - Qué: confirmar que el umbral de aviso y el tiempo máximo se leen de la tabla `property` y no de `Settings`.
    Confirmar también que `google_timeout` pasa a ser el tiempo máximo total.
  - Hecho cuando: en `plan.md` la decisión D4 queda marcada como aprobada, con fecha.

## Piezas base

- [x] **T01 — Remitente en el esquema del evento**
  - RF: RF-05
  - Depende de: T00
  - Qué: `ChatUser` (`name`, `type`) y `ChatMessage.sender` en `src/interfaces/google_chat.py`.
  - Hecho cuando: un test valida un evento con `sender.name = "users/123"` y lee ese valor. El mismo evento sin
    `sender` da `None`, y los tests existentes de `tests/google_chat_test.py` siguen pasando.

- [x] **T02 — Mención al remitente**
  - RF: RF-05
  - Depende de: T01
  - Qué: `mention_of(event)` en `src/services/google_chat.py`.
  - Hecho cuando: los tests de `tests/google_chat_test.py` comprueban que da `"<users/123>"` en un `SPACE`, y
    `""` en un `DIRECT_MESSAGE` y en un evento sin remitente.

- [x] **T03 — Publicar un mensaje nuevo en el space**
  - RF: RF-04, RF-09
  - Depende de: T00
  - Qué: `create_message(space, texto, token, http)` en `src/services/google_chat.py`.
  - Hecho cuando: un test con `httpx.MockTransport` comprueba un `POST` a `https://chat.googleapis.com/v1/spaces/AAA/messages`
    con `Authorization: Bearer <token>` y un cuerpo sin la clave `thread`. Una respuesta 403 lanza `httpx.HTTPStatusError`.

- [x] **T04 — Token de la cuenta de servicio reutilizable**
  - RF: — (soporte de RF-04 y RF-09)
  - Depende de: T00
  - Qué: extraer `chat_token(session, http)` de `read_files`. Devuelve `None` y registra el error en el log cuando falta la
    property o no es válida.
  - Hecho cuando: un test sin `google_chat_service_account_json` da `None` y deja un registro de nivel `ERROR`, y los
    tests de adjuntos existentes pasan sin cambios.

- [x] **T05 — Procesar la solicitud**
  - RF: RF-07, RF-08, RF-10
  - Depende de: T04
  - Qué: nuevo `src/services/google_chat_reply.py` con `process(...)`. Se mueven ahí `read_files` y las constantes
    (`DEMORA`, `NO_DISPONIBLE`, `SIN_TEXTO`) y se agrega `AVISO`. `process` abre su propia sesión, aplica el tiempo máximo
    y devuelve siempre un texto.
  - Hecho cuando: los tests de `tests/google_chat_reply_test.py` comprueban tres casos:
    - Con un `ask` falso que responde `"ok"`, se obtiene `"ok"` y `ask` recibe el `thread_id` del mensaje original.
    - Si `ask` lanza `AgentNotFoundError` o `DatabaseUnavailableError`, se obtiene `NO_DISPONIBLE`.
    - Con un `ask` bloqueado y un máximo de 0.01 s, se obtiene `DEMORA` y la tarea de `ask` queda cancelada.

- [x] **T06 — Lectura de umbrales**
  - RF: RF-06
  - Depende de: T00
  - Qué: leer `google_chat_notice_seconds` (10 si falta) y `google_timeout` (máximo; si falta, `PropertyNotFoundError` como hoy).
  - Hecho cuando: tests con `get_property` falso cubren tres casos: ambas presentes da sus valores, sin el aviso da 10,
    y sin `google_timeout` lanza `PropertyNotFoundError`.

## Orquestación

- [ ] **T07 — Decidir entre respuesta síncrona y diferida, y entregar**
  - RF: RF-01, RF-02, RF-03, RF-04, RF-05, RF-09, RF-11, RF-12
  - Depende de: T02, T03, T05, T06
  - Qué: `answer(...)`, `deliver(...)`, el registro de tareas pendientes y `cancel_pending()` en `google_chat_reply.py`.
  - Hecho cuando: pasan los tests de `tests/google_chat_reply_test.py`, con umbrales de milisegundos y `asyncio.Event`:
    - Respuesta antes del umbral: `chat_reply("ok")` y `create_message` no se llama.
    - `ask` bloqueado: la respuesta es `chat_reply(AVISO)`. Al liberarlo, `create_message` se llama una sola vez, con
      `"<users/123> ok"` en un space y con `"ok"` en un DM.
    - Si `create_message` lanza `httpx.HTTPError`, queda un `ERROR` en el log y no hay segunda llamada.
    - Con el aviso ≥ al máximo nunca se devuelve `AVISO`.
    - Dos eventos de la misma conversación con `ask` bloqueado producen dos `AVISO` y dos `create_message`.
    - Al terminar cada caso el registro de pendientes queda vacío.

## Integración

- [ ] **T08 — Router delgado**
  - RF: RF-01, RF-13
  - Depende de: T07
  - Qué: `src/routers/google_chat.py` solo verifica el token, atiende la bienvenida y los eventos vacíos, y delega en `answer`.
  - Hecho cuando: `test_endpoint_sin_token_responde_401_antes_de_leer_la_configuracion` sigue pasando. Un test del
    endpoint con `answer` falso devuelve exactamente lo que da `answer`. El router ya no importa `ask` ni `read_attachments`.

- [ ] **T09 — Cancelar las solicitudes en curso al apagar**
  - RF: — (decisión D7)
  - Depende de: T07
  - Qué: el `lifespan` de `main.py` llama a `cancel_pending()` y registra cuántas solicitudes se cancelaron.
  - Hecho cuando: un test con dos tareas bloqueadas comprueba que `cancel_pending()` devuelve 2, que las tareas quedan
    `cancelled()` y que el registro queda vacío.

- [ ] **T10 — Documentar las properties**
  - RF: RF-06
  - Depende de: T00
  - Qué: la tabla de properties del `README.md`.
  - Hecho cuando: el README lista `google_chat_notice_seconds` (umbral de aviso, 10 por defecto) y `google_timeout`
    (tiempo máximo total, valor sugerido 120).

## Cierre

- [ ] **T11 — Verificación y versión**
  - RF: todos (criterios de finalización)
  - Depende de: T08, T09, T10
  - Qué: verificación completa y subida de versión (constitución 9).
  - Hecho cuando: `uv run pytest` y `uv run pyright` terminan sin errores y `uv run alembic check` no reporta diferencias.
    Además, `pyproject.toml` dice `version = "3.2.0"` y `uv.lock` quedó actualizado por `uv sync`.

- [ ] **T12 — Prueba manual en Google Chat**
  - RF: RF-01, RF-02, RF-04, RF-05, RF-07
  - Depende de: T11
  - Qué: en el entorno de prueba, cargar `google_chat_notice_seconds` y subir `google_timeout`; luego probar en un space y en un DM.
  - Hecho cuando: hay evidencia (capturas o logs) de cuatro casos:
    - Respuesta rápida dentro del hilo.
    - Respuesta lenta con aviso y luego un mensaje nuevo fuera del hilo, con mención en el space y sin mención en el DM.
    - Demora mayor que el máximo, con mensaje de demora.
    - Ningún mensaje muestra trazas internas.

## Cobertura de RF

| RF    | Tareas             |
| ----- | ------------------ |
| RF-01 | T07, T08, T12      |
| RF-02 | T07, T12           |
| RF-03 | T07                |
| RF-04 | T03, T07, T12      |
| RF-05 | T01, T02, T07, T12 |
| RF-06 | T00, T06, T10      |
| RF-07 | T05, T12           |
| RF-08 | T05                |
| RF-09 | T03, T07           |
| RF-10 | T05                |
| RF-11 | T07                |
| RF-12 | T07                |
| RF-13 | T08                |
