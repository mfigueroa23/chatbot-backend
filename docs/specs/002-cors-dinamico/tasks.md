# Tareas 002 — CORS administrado desde base de datos

Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md)

Ordenadas por dependencia: una tarea solo empieza cuando sus dependencias están marcadas.
Cada tarea que cambia comportamiento incluye su test (constitución 4) y deja `uv run pyright` en 0 errores (constitución 3).
El cambio de esquema (tabla `cors_origins`) quedó aprobado en la spec (constitución 5).

## Grafo

```
T01 ─┬─► T02 ─► T08 ──────────────────┐
     └─► T03 ─► T04 ─┬─► T05 ─┐        ├─► T09 ─► T10
                     └─► T06 ─┴─► T07 ─┘
```

## Datos

- [x] **T01 — Modelo `CorsOrigin`**
  - RF: RF-01
  - Depende de: —
  - Qué: `src/models/cors_origins.py` con la tabla `cors_origins` (`id`, `origin` `String(255)` único y no nulo,
    `enabled` `Boolean` no nulo con `server_default true`) e import del modelo en `alembic/env.py`.
  - Hecho cuando: un test en `tests/cors_test.py` comprueba sobre `CorsOrigin.__table__` que `origin` es no nulo y
    tiene la restricción única `uq_cors_origins_origin`, y que `enabled` es no nulo con default de servidor `true`.

- [x] **T02 — Migración de la tabla**
  - RF: RF-01
  - Depende de: T01
  - Qué: `uv run alembic revision --autogenerate -m "cors_origins"`, revisar el archivo generado (solo crea la tabla
    y su restricción; sin datos semilla) y aplicarlo.
  - Hecho cuando: `uv run alembic upgrade head` aplica la migración, `uv run alembic check` no reporta diferencias y
    `uv run alembic downgrade -1` seguido de `uv run alembic upgrade head` termina sin errores.

## Servicio

- [x] **T03 — Consulta de origen permitido**
  - RF: RF-06, RF-07, RF-09
  - Depende de: T01
  - Qué: `is_origin_allowed(session, origin) -> bool` en `src/services/cors.py`: un `SELECT` por `origin` exacto y
    `enabled = true`; `SQLAlchemyError`/`OSError` se envuelven en `DatabaseUnavailableError`, como en `get_property`.
  - Hecho cuando: los tests con sesiones falsas (estilo `DownSession`) comprueban que:
    - con una fila da `True` y sin fila da `False`;
    - la sentencia recibida filtra por `cors_origins.origin` con el texto tal cual y por `cors_origins.enabled`;
    - con una sesión que lanza `ConnectionRefusedError` se lanza `DatabaseUnavailableError`.

## Middleware

- [ ] **T04 — Middleware base, fail-closed y registro**
  - RF: RF-04, RF-08, RF-09
  - Depende de: T03
  - Qué: `DatabaseCORSMiddleware` ASGI puro en `src/middlewares/cors.py`: sin `Origin` pasa directo a la app; con
    `Origin` abre `SessionLocal`, llama a `is_origin_allowed` y, si no está permitido o falla, pasa a la app sin
    cabeceras CORS y registra el error. Registro con `app.add_middleware` en `main.py`.
  - Hecho cuando: con `TestClient(app)` y `is_origin_allowed` reemplazado por un falso:
    - `GET /` sin `Origin` → 200, el falso no se llama y no hay cabeceras `Access-Control-*`;
    - `GET /` con un origen no permitido → 200 con el cuerpo normal y sin cabeceras `Access-Control-*`;
    - si el falso lanza `DatabaseUnavailableError` o `RuntimeError` → 200 sin cabeceras CORS, un registro de nivel
      `ERROR` en `caplog` y el cuerpo sin detalles del error.

- [ ] **T05 — Origen permitido: delegar en `CORSMiddleware`**
  - RF: RF-02, RF-03, RF-06, RF-07, RF-10, RF-11
  - Depende de: T04
  - Qué: cuando el origen está permitido, delegar en `CORSMiddleware(app, allow_origins=[origin],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=False)`.
  - Hecho cuando: con el falso del servicio:
    - `GET /` con origen permitido → `Access-Control-Allow-Origin` igual al origen y `Vary` incluye `Origin`;
    - preflight a `/chat` con `Access-Control-Request-Method: POST` y `Access-Control-Request-Headers: content-type, x-algo`
      → 200 con el método permitido y el eco de esas cabeceras, sin ejecutar el endpoint (`ask` falso que falla si se llama);
    - ninguna respuesta trae `Access-Control-Allow-Credentials` ni `Access-Control-Allow-Origin: *`;
    - variantes del origen registrado (`http://`, otro puerto, subdominio, barra final, mayúsculas) no reciben cabeceras;
    - dos peticiones seguidas con el falso cambiando de `True` a `False` → la primera con cabeceras, la segunda sin, y
      el falso se llamó dos veces.

- [ ] **T06 — Preflight rechazado**
  - RF: RF-05
  - Depende de: T04
  - Qué: si la petición es preflight (`OPTIONS` + `Access-Control-Request-Method`) y el origen no está permitido o la
    consulta falla, responder 400 con la constante `ORIGEN_NO_PERMITIDO` en español.
  - Hecho cuando: un preflight a `/chat` desde un origen no permitido → 400, cuerpo igual a `ORIGEN_NO_PERMITIDO`, sin
    ninguna cabecera `Access-Control-*` ni `Vary`, y el endpoint no se ejecuta.

- [ ] **T07 — Cobertura de todas las rutas**
  - RF: RF-12
  - Depende de: T05, T06
  - Qué: comprobar que el middleware global alcanza todos los routers registrados en `main.py`.
  - Hecho cuando: un test parametrizado lanza un preflight desde un origen permitido a `/chat`,
    `/api/v1/google-chat/events` y `/health`, y las tres respuestas traen `Access-Control-Allow-Origin` con ese origen.

## Documentación

- [ ] **T08 — README**
  - RF: RF-01, RF-06
  - Depende de: T02
  - Qué: fila `cors_origins` en "Base de datos" con el formato del origen y ejemplos de `INSERT`/`UPDATE`; advertencia
    de no registrar `null`; `middlewares/` en "Estructura".
  - Hecho cuando: el README describe la tabla, el formato `esquema://host[:puerto]` (minúsculas, sin barra final, sin
    puerto por defecto), un ejemplo para habilitar y otro para deshabilitar, y lista `src/middlewares/`.

## Cierre

- [ ] **T09 — Verificación y versión**
  - RF: todos (criterios de finalización)
  - Depende de: T07, T08
  - Qué: verificación completa y subida de versión (constitución 9).
  - Hecho cuando: `uv run pytest` y `uv run pyright` terminan sin errores, `uv run alembic check` no reporta
    diferencias, `pyproject.toml` dice `version = "3.3.0"` y `uv.lock` quedó actualizado por `uv sync`.

- [ ] **T10 — Prueba manual con la BD local**
  - RF: RF-02, RF-03, RF-04, RF-05, RF-07, RF-08
  - Depende de: T09
  - Qué: con `uv run fastapi dev`, insertar `http://localhost:5173` en `cors_origins` y probar con `curl`.
  - Hecho cuando: hay evidencia (salida de `curl -i`) de cinco casos:
    - preflight y `GET /` con `Origin: http://localhost:5173` traen `Access-Control-Allow-Origin`;
    - tras `UPDATE cors_origins SET enabled = false`, el siguiente `GET /` no trae cabeceras CORS, sin reiniciar la app;
    - un preflight desde ese origen deshabilitado responde 400 sin cabeceras CORS;
    - `GET /health` sin `Origin` responde igual que antes del cambio;
    - ninguna respuesta muestra trazas internas.

## Cobertura de RF

| RF    | Tareas                  |
| ----- | ----------------------- |
| RF-01 | T01, T02, T08           |
| RF-02 | T05, T10                |
| RF-03 | T05, T10                |
| RF-04 | T04, T10                |
| RF-05 | T06, T10                |
| RF-06 | T03, T05, T08           |
| RF-07 | T03, T05, T10           |
| RF-08 | T04, T10                |
| RF-09 | T03, T04                |
| RF-10 | T05                     |
| RF-11 | T05                     |
| RF-12 | T07                     |
