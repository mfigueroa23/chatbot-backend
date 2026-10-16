# Plan 002 — CORS administrado desde base de datos

Spec: [spec.md](spec.md) · Constitución: [docs/constitution.md](../../constitution.md)

## Contexto
Hoy la API no tiene CORS: `main.py` no registra ningún middleware y en `src/` no hay referencias a `Origin`. FastAPI
0.143 / Starlette 1.7 traen `CORSMiddleware`, pero solo acepta una lista fija de orígenes y su `is_allowed_origin` es
síncrono, así que no puede consultar la BD (async) en cada petición. El plan agrega un middleware ASGI propio que
resuelve el origen contra la tabla nueva y, si está permitido, delega la generación de cabeceras en el
`CORSMiddleware` de Starlette configurado solo con ese origen. Sin dependencias nuevas.

## Flujo
```
petición ─► DatabaseCORSMiddleware
              │
              ├─ sin cabecera Origin ─► app, sin consultar la BD ni emitir cabeceras CORS          (RF-08)
              │
              ▼
          abrir sesión (SessionLocal) ─► services.cors.is_origin_allowed(session, origin)
              │   comparación exacta del texto: origin = :origin AND enabled                       (RF-06, RF-07)
              │   error de BD / inesperado ─► log, se trata como no permitido                      (RF-09)
              │
              ├─ permitido ─► CORSMiddleware(app, allow_origins=[origin], métodos y cabeceras "*",
              │               sin credenciales) ─► preflight 200 o respuesta con
              │               Access-Control-Allow-Origin: <origin> + Vary: Origin                 (RF-02, RF-03, RF-10, RF-11)
              │
              └─ no permitido ─┬─ preflight ─► 400 en español, sin cabeceras CORS, sin endpoint    (RF-05)
                               └─ simple    ─► app, respuesta sin cabeceras CORS                   (RF-04)
```
El middleware se registra en la app, por delante de todos los routers, así que cubre todas las rutas (RF-12).

## Módulos
| Módulo | Cambio | RF |
|---|---|---|
| `src/models/cors_origins.py` (nuevo) | Modelo `CorsOrigin`, tabla `cors_origins` (ver Modelo de datos). | RF-01 |
| `alembic/env.py` | Importar `CorsOrigin` para que el autogenerate lo detecte, como el resto de modelos. | RF-01 |
| `alembic/versions/<rev>_cors_origins.py` (nuevo) | Migración generada con `alembic revision --autogenerate`; crea la tabla y su restricción única. Sin datos semilla. La aplica `entrypoint.sh` al arrancar. | RF-01 |
| `src/services/cors.py` (nuevo) | `is_origin_allowed(session, origin) -> bool`: una consulta `SELECT` por origen exacto y `enabled = true`. Envuelve `SQLAlchemyError`/`OSError` en `DatabaseUnavailableError`, igual que `get_property`. | RF-06, RF-07, RF-09 |
| `src/middlewares/cors.py` (nuevo) | `DatabaseCORSMiddleware` (ASGI puro): lee `Origin`, abre su propia sesión, llama al servicio, captura errores (fail-closed + log), responde el preflight rechazado y delega en `CORSMiddleware` cuando el origen está permitido. Constante `ORIGEN_NO_PERMITIDO` con el texto en español del 400. | RF-02, RF-03, RF-04, RF-05, RF-08, RF-09, RF-10, RF-11, RF-12 |
| `main.py` | `app.add_middleware(DatabaseCORSMiddleware)`. | RF-12 |
| `README.md` | Tabla `cors_origins` en "Base de datos" (formato del origen y ejemplo de `INSERT`/`UPDATE`) y `middlewares/` en "Estructura". | RF-01, RF-06 |
| `pyproject.toml` | 3.2.0 → 3.3.0 (funcionalidad nueva), `uv sync`. | Constitución 9 |

## Modelo de datos
**Tabla `cors_origins`** (cambio de esquema aprobado en la spec; constitución 5):

| Columna | Tipo | Restricciones | Motivo |
|---|---|---|---|
| `id` | `Integer` | PK | Igual que el resto de tablas. |
| `origin` | `String(255)` | `NOT NULL`, `UNIQUE` (`uq_cors_origins_origin`) | Un origen aparece una sola vez (RF-01). El índice de la restricción única sirve a la consulta por petición (RF-07). |
| `enabled` | `Boolean` | `NOT NULL`, `server_default true` | Indicador de habilitado (RF-01). Ver D6. |

- **Formato del origen:** el mismo texto que envía el navegador en `Origin`: `esquema://host[:puerto]`, en minúsculas,
  sin barra final ni ruta, y sin el puerto por defecto (`https://app.ejemplo.com`, `http://localhost:5173`). El código
  no normaliza (D5); el formato se documenta en el README.
- **Administración:** directa en la BD (decisión de la spec), p. ej.
  `INSERT INTO cors_origins (origin) VALUES ('https://app.ejemplo.com');` y `UPDATE … SET enabled = false`.
- **Sin estado en memoria:** no hay caché; cada petición con `Origin` hace una consulta (RF-07).

## Decisiones
| # | Decisión | Por qué | Alternativa descartada |
|---|---|---|---|
| D1 | Middleware ASGI propio que consulta la BD y delega en `CORSMiddleware` de Starlette, instanciado por petición con `allow_origins=[origin]` | La consulta es async y el `CORSMiddleware` no lo permite; delegando se reutiliza la lógica probada de Starlette (preflight, `Vary`, eco de cabeceras) en lugar de reimplementarla. Instanciarlo solo asigna atributos, el costo es despreciable. | Subclase de `CORSMiddleware` que sobrescriba `is_allowed_origin`: es síncrono y se llama desde `preflight_response` (síncrono), así que no puede esperar la consulta. Reimplementar CORS completo: más código y más riesgo de errores en las cabeceras. |
| D2 | Responder el preflight rechazado en nuestro middleware (400, texto en español, sin cabeceras) en lugar de dejarlo a Starlette | Starlette responde el preflight rechazado con `Vary` y `Access-Control-Allow-Methods` y un texto en inglés; RF-05 pide **sin** cabeceras CORS y la constitución 7 pide mensajes en español. | Delegar todo en `CORSMiddleware` con `allow_origins=[]`: incumple RF-05 y la constitución 7. |
| D3 | ASGI puro (`__call__(scope, receive, send)`) | No envuelve la respuesta ni rompe el streaming; `BaseHTTPMiddleware` tiene problemas conocidos con respuestas en streaming y tareas en segundo plano. | `@app.middleware("http")` / `BaseHTTPMiddleware`: más simple, pero con esas limitaciones. |
| D4 | El middleware abre su propia sesión (`SessionLocal`) y la consulta vive en `services/cors.py` | Los middlewares no tienen `Depends`; la regla de capas (constitución 2) pide que la capa HTTP no ejecute SQL. Mismo criterio que D2 de la spec 001. | SQL dentro del middleware: viola la constitución 2 y no se puede probar el servicio por separado. |
| D5 | Comparación exacta del texto, sin normalizar (mayúsculas, puerto por defecto, barra final) | Es lo que pide la spec (RF-06) y los navegadores ya envían `Origin` en forma canónica. Un registro mal escrito simplemente no coincide (falla cerrado). | Normalizar en código (`urllib.parse`): agrega casos borde (IDN, puertos) sin requisito y hace menos predecible qué coincide. |
| D6 | `enabled` con `server_default true` | Insertar una fila ya expresa la intención de permitir el origen; basta con `INSERT … (origin)`. Deshabilitar es un `UPDATE` explícito. | Por defecto `false`: obliga a dos pasos y es fácil olvidar el segundo, sin ganar seguridad real (la fila la crea un administrador). |
| D7 | Fail-closed ante cualquier error al consultar: `DatabaseUnavailableError` → `logger.error`; excepción inesperada → `logger.exception`; en ambos casos la petición sigue sin cabeceras CORS | Decisión de la spec (RF-09): un fallo nunca abre el acceso y la petición no se corta (el endpoint decide su propio error, p. ej. `/health` → 503). | Responder 503 desde el middleware: lo descartó la spec. |
| D8 | Métodos y cabeceras `"*"` para orígenes permitidos, `allow_credentials=False`, `max_age` por defecto (600 s) | RF-03 pide permitir lo solicitado y RF-10 prohíbe credenciales. Con `allow_credentials=False` Starlette nunca emite `Access-Control-Allow-Credentials`, y con un origen explícito nunca emite `*`. | Lista fija de métodos/cabeceras: fuera de alcance (no hay configuración por origen) y rompería clientes al agregar cabeceras. |
| D9 | Nuevo paquete `src/middlewares/` | El middleware es capa HTTP pero no es un router; separarlo deja `main.py` solo con el registro. | Definirlo en `main.py`: mezcla arranque con lógica y dificulta probarlo aislado. |
| D10 | Sin caché | Decisión de la spec (RF-07). La consulta usa el índice único y solo ocurre con `Origin` (las probes de Kubernetes no lo envían). | Caché con TTL: descartada en la spec. |

## Estrategia de tests
Todos corren con `uv run pytest`, sin BD real ni LLM (constitución 4). Archivo nuevo `tests/cors_test.py`.

- **Middleware:** `TestClient(app)` real (incluye el middleware registrado en `main.py`). Con `monkeypatch` se reemplaza
  `is_origin_allowed` en `src.middlewares.cors` por un falso async que responde según una lista de orígenes, cuenta
  sus llamadas o lanza una excepción. Crear la sesión con `SessionLocal()` no abre conexión mientras no se ejecute una
  consulta, así que los tests no tocan la BD. Para las peticiones simples se usa `GET /` (liveness, sin BD); para los
  preflight, rutas reales (`/chat`, `/api/v1/google-chat/events`, `/health`), que no llegan al endpoint.
- **Servicio:** sesiones falsas con `execute` async, al estilo de `DownSession` en `tests/health_test.py`: una
  devuelve un resultado con `scalar_one_or_none()`, otra lanza `ConnectionRefusedError`.
- **Modelo:** se comprueba con `uv run alembic check` y un test sobre `CorsOrigin.__table__` (columnas, unicidad, default).

| Test | RF |
|---|---|
| `CorsOrigin.__table__` tiene `origin` único y no nulo y `enabled` no nulo con default `true` | RF-01 |
| `GET /` con `Origin` permitido → 200, `Access-Control-Allow-Origin` igual al origen y `Vary` incluye `Origin` | RF-02, RF-11 |
| Preflight permitido con `Access-Control-Request-Method: POST` y `Access-Control-Request-Headers: content-type, x-algo` → 200, eco del método y las cabeceras; el endpoint no se ejecuta (`/chat` con un `ask` falso que falla si se llama) | RF-03 |
| `GET /` con `Origin` no registrado o deshabilitado (falso devuelve `False`) → 200 con el cuerpo normal y sin ninguna cabecera `Access-Control-*` | RF-04 |
| Preflight no permitido → 400, texto en español, sin cabeceras `Access-Control-*` ni `Vary` del preflight; el endpoint no se ejecuta | RF-05 |
| Variantes del origen registrado (`http://` en lugar de `https://`, otro puerto, subdominio, barra final, mayúsculas) no reciben cabeceras; el servicio recibe el texto tal cual | RF-06 |
| Servicio: la consulta filtra por `origin` exacto y `enabled`; devuelve `True` con fila y `False` sin fila | RF-06, RF-07 |
| Dos peticiones seguidas con el falso cambiando de `True` a `False` → la primera con cabeceras, la segunda sin; el falso se llama una vez por petición (sin caché) | RF-07 |
| Petición sin `Origin` → el falso no se llama y no hay cabeceras CORS | RF-08 |
| El falso lanza `DatabaseUnavailableError` / `RuntimeError` → respuesta normal sin cabeceras CORS, error en `caplog`, sin detalles en el cuerpo | RF-09 |
| Servicio con sesión caída → lanza `DatabaseUnavailableError` | RF-09 |
| Respuestas a origen permitido (simple y preflight) no traen `Access-Control-Allow-Credentials` ni `Access-Control-Allow-Origin: *` | RF-10 |
| Preflight permitido sobre `/chat`, `/api/v1/google-chat/events` y `/health` recibe cabeceras | RF-12 |

Verificación manual (criterio de la spec): con la BD local, insertar `http://localhost:5173`, lanzar con `curl` un
preflight y un `GET /` con ese `Origin` (cabeceras presentes), hacer `UPDATE … SET enabled = false` y repetir sin
reiniciar (cabeceras ausentes); `curl /health` sin `Origin` responde igual que hoy.

## Cobertura de RF
| RF | Módulo(s) | Test |
|---|---|---|
| RF-01 | `models/cors_origins.py`, migración, `alembic/env.py` | ✔ + `alembic check` |
| RF-02 | `middlewares/cors.py` (delegación en `CORSMiddleware`, D1) | ✔ |
| RF-03 | `middlewares/cors.py` (D1, D8) | ✔ |
| RF-04 | `middlewares/cors.py` | ✔ |
| RF-05 | `middlewares/cors.py` (D2) | ✔ |
| RF-06 | `services/cors.py` (D5) | ✔ |
| RF-07 | `services/cors.py` + middleware sin caché (D10) | ✔ |
| RF-08 | `middlewares/cors.py` | ✔ |
| RF-09 | `services/cors.py` + `middlewares/cors.py` (D7) | ✔ |
| RF-10 | `middlewares/cors.py` (D8) | ✔ |
| RF-11 | `middlewares/cors.py` (`Vary` de Starlette) | ✔ |
| RF-12 | `main.py` (registro global) | ✔ |

## Riesgos abiertos (no resueltos por este plan)
- **Errores 500 no controlados:** `ServerErrorMiddleware` de Starlette queda por fuera de los middlewares de usuario,
  así que una excepción no capturada responde 500 sin cabeceras CORS y el navegador lo verá como error de CORS. Los
  routers actuales capturan sus errores, por lo que hoy no ocurre en la práctica.
- **Caché del preflight en el navegador:** con `max_age` de 600 s, un navegador puede reutilizar un preflight
  aprobado hasta 10 minutos después de deshabilitar el origen; la petición real sí se queda sin cabeceras y se
  bloquea, así que RF-07 se cumple en la respuesta.
- **`Origin: null`** (iframes con sandbox, `file://`): solo pasaría si alguien registra literalmente `null`; queda
  documentado en el README que no debe registrarse.
- **Carga de BD:** cada petición con `Origin` (incluidos los preflight) usa una conexión del pool del engine; con
  mucho tráfico de navegador aumenta la presión sobre el pool.

## Cierre
`uv run pytest`, `uv run pyright` (0 errores), `uv run alembic upgrade head` y `uv run alembic check` sin diferencias,
versión 3.3.0 y `uv sync`.
