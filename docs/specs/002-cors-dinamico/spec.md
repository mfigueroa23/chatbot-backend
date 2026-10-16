# Spec 002 — CORS administrado desde base de datos

## Problema (por qué)
La API no emite cabeceras CORS, por lo que un frontend web servido desde otro dominio no puede consumirla desde el
navegador. Fijar los orígenes en código o en variables de entorno obliga a redesplegar cada vez que se autoriza o se
retira un dominio, y no deja un registro claro de qué dominios tienen acceso.

## Objetivo (qué)
Permitir peticiones cross-origin desde el navegador solo a los orígenes registrados y habilitados en una tabla de base
de datos, de forma que habilitar o deshabilitar un dominio aplique sin redeploy ni reinicio de pods.

## Decisiones tomadas
- Tabla nueva con el origen y un booleano de habilitado (aprobado el cambio de esquema; requiere migración Alembic).
- Coincidencia por origen exacto: esquema + host + puerto (p. ej. `https://app.ejemplo.com`); sin comodines.
- La tabla se consulta en cada petición con cabecera `Origin`; un cambio aplica desde la siguiente petición.
- Los dominios se administran directamente en la BD; no hay endpoints de administración ni datos semilla.
- Fallo al consultar la tabla → se trata como origen no permitido y se registra el error (fail-closed).
- Aplica a todas las rutas de la API, sin credenciales cross-origin.
- Origen no permitido → sin cabeceras CORS (el navegador bloquea la respuesta); no se devuelve 403.

## Requisitos funcionales (EARS)
- **RF-01** El sistema debe almacenar los orígenes CORS en una tabla de base de datos con el origen (único) y un
  indicador de habilitado.
- **RF-02** Cuando llegue una petición con cabecera `Origin` que coincida exactamente con un origen registrado y
  habilitado, el sistema debe incluir en la respuesta `Access-Control-Allow-Origin` con ese mismo origen.
- **RF-03** Cuando llegue una petición preflight (`OPTIONS` con `Access-Control-Request-Method`) desde un origen
  registrado y habilitado, el sistema debe responder con éxito permitiendo el método y las cabeceras solicitados, sin
  ejecutar la lógica del endpoint.
- **RF-04** Si el `Origin` de una petición no está registrado o está deshabilitado, entonces el sistema debe procesar
  la petición sin emitir cabeceras CORS.
- **RF-05** Si una petición preflight proviene de un origen no registrado o deshabilitado, entonces el sistema debe
  rechazarla con 400 sin cabeceras CORS y sin ejecutar la lógica del endpoint.
- **RF-06** El sistema debe comparar el `Origin` con los orígenes registrados por coincidencia exacta de esquema, host
  y puerto, sin aceptar subdominios, otro esquema u otro puerto.
- **RF-07** El sistema debe consultar los orígenes habilitados en la base de datos en cada petición que traiga
  `Origin`, de modo que agregar, habilitar o deshabilitar un origen aplique desde la siguiente petición en todos los
  pods.
- **RF-08** Cuando una petición no traiga cabecera `Origin`, el sistema debe procesarla como hoy, sin consultar la
  tabla de orígenes ni emitir cabeceras CORS.
- **RF-09** Si falla la consulta de orígenes en la base de datos, entonces el sistema debe tratar el origen como no
  permitido, registrar el error en el log y no exponer detalles internos al cliente.
- **RF-10** El sistema no debe emitir `Access-Control-Allow-Credentials` ni responder con `*` como origen permitido.
- **RF-11** Mientras un origen esté habilitado, el sistema debe incluir `Vary: Origin` en las respuestas a ese origen
  para que cachés intermedias no reutilicen la respuesta con otro origen.
- **RF-12** El sistema debe aplicar las reglas de CORS a todas las rutas de la API, incluidas `/chat`,
  `/google-chat` y `/health`.

## Fuera de alcance
- Endpoints, UI o CLI para administrar los orígenes; datos semilla en la migración.
- Comodines, subdominios o expresiones regulares en los orígenes.
- Caché en memoria de los orígenes.
- Credenciales cross-origin (cookies, `Authorization` con credenciales) y cabeceras expuestas personalizadas.
- Configuración de CORS por ruta, por método o por origen (métodos/cabeceras distintos por dominio).
- Responder 403 o bloquear en el servidor peticiones de orígenes no permitidos.
- Autenticación o autorización de la API; CORS no se considera un control de seguridad del servidor.
- Nuevas dependencias.

## Criterios de finalización
- Cada RF tiene al menos un test en `tests/` que pasa con `uv run pytest`, sin BD real y sin LLM.
- Existe la migración Alembic de la tabla, `uv run alembic upgrade head` la aplica y `uv run alembic check` no reporta
  diferencias.
- `uv run pyright` termina con 0 errores.
- Verificación manual: preflight y petición desde un origen habilitado reciben cabeceras CORS; al deshabilitarlo en la
  BD, la siguiente petición deja de recibirlas sin reiniciar el pod; una petición sin `Origin` (p. ej. `/health`)
  funciona igual que hoy.
- Versión semver subida en `pyproject.toml` y `uv sync` ejecutado.
