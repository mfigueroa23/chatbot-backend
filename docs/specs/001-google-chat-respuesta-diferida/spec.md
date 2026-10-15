# Spec 001 — Respuesta diferida en Google Chat

## Problema (por qué)
Cuando el asistente tarda más que el límite de Google Chat en responder (habitual al leer archivos adjuntos), el
usuario recibe "Me tomó demasiado tiempo revisar tu mensaje…" y la respuesta se descarta, aunque el LLM la habría
terminado. El usuario no sabe si su solicitud se está atendiendo y tiene que reintentar, muchas veces sin éxito.

## Objetivo (qué)
Si la respuesta tarda, avisar pronto al usuario que su solicitud se está revisando y, cuando esté lista, entregarla
como un mensaje nuevo en el chat, sin que el límite de la respuesta síncrona de Google Chat la descarte.

## Decisiones tomadas
- Umbral de aviso (10 s por defecto) y tiempo máximo total son configurables sin redeploy.
- En un space, la respuesta diferida menciona al usuario que preguntó.
- El historial sigue asociado a la conversación original (hilo original en space, space en mensaje directo).
- Fallo del LLM/BD → mensaje de error al usuario; fallo al publicar en Chat → solo log, sin reintentos.
- Una solicitud en curso se pierde si el pod se reinicia (mejor esfuerzo).
- Mensajes concurrentes en la misma conversación se procesan de forma independiente.

## Requisitos funcionales (EARS)
- **RF-01** Cuando el asistente obtenga la respuesta antes del umbral de aviso, el sistema debe responder de forma
  síncrona en el hilo del mensaje, como hoy, sin enviar aviso ni mensaje diferido.
- **RF-02** Cuando el procesamiento de un mensaje supere el umbral de aviso, el sistema debe responder al evento de
  Google Chat con un aviso en español indicando que está revisando la solicitud.
- **RF-03** Mientras una solicitud siga en proceso después del aviso, el sistema debe continuar procesándola sin
  retener la respuesta al evento de Google Chat.
- **RF-04** Cuando la respuesta de una solicitud avisada esté lista, el sistema debe publicarla como mensaje nuevo en
  el space de origen, fuera del hilo del mensaje original.
- **RF-05** Donde el space no sea un mensaje directo, el sistema debe incluir al inicio del mensaje diferido una
  mención al usuario que hizo la solicitud.
- **RF-06** El sistema debe obtener el umbral de aviso y el tiempo máximo total desde la configuración en base de
  datos, de modo que un cambio aplique desde el siguiente evento.
- **RF-07** Si el procesamiento supera el tiempo máximo total, entonces el sistema debe publicar como mensaje nuevo
  un mensaje de demora en español y descartar cualquier respuesta posterior de esa solicitud.
- **RF-08** Si el LLM, la base de datos o la configuración del agente fallan después del aviso, entonces el sistema
  debe publicar como mensaje nuevo el mensaje de servicio no disponible y registrar el error, sin exponer detalles
  internos al usuario.
- **RF-09** Si falla la publicación del mensaje diferido en Google Chat, entonces el sistema debe registrar el error
  sin reintentar.
- **RF-10** El sistema debe registrar la pregunta y la respuesta diferida en el historial de la conversación
  original del mensaje.
- **RF-11** Cuando lleguen varios mensajes de una misma conversación mientras otro sigue en proceso, el sistema debe
  procesar cada uno de forma independiente y entregar una respuesta por cada mensaje.
- **RF-12** El sistema debe entregar por cada solicitud como máximo un aviso y un único mensaje final (respuesta,
  demora o error).
- **RF-13** Si el token del evento no es válido, entonces el sistema debe rechazarlo con 401 sin iniciar ningún
  procesamiento (comportamiento actual sin cambios).

## Fuera de alcance
- Durabilidad: retomar solicitudes perdidas por reinicio o reemplazo del pod; colas o tablas nuevas.
- Reintentos al publicar en Google Chat.
- Garantizar el orden del historial ante mensajes concurrentes.
- Que el hilo del mensaje diferido herede el contexto de la conversación original.
- Editar o borrar el aviso al llegar la respuesta; respuestas parciales o en streaming.
- Cancelar una solicitud en curso por parte del usuario.
- El endpoint de chat genérico (`/chat`) y otros canales.
- Cambios en la lectura de adjuntos o en su tamaño máximo.
- Cambios en `src/models/` y nuevas dependencias.

## Criterios de finalización
- Cada RF tiene al menos un test en `tests/` que pasa con `uv run pytest`, sin BD real, sin LLM y sin llamadas
  reales a Google.
- `uv run pyright` termina con 0 errores y `uv run alembic check` no reporta diferencias.
- Verificación manual en un space y en un mensaje directo: respuesta rápida en el hilo; respuesta lenta con aviso y
  mensaje nuevo (con mención en el space); demora máxima con mensaje de demora.
- Los mensajes al usuario están en español y no exponen trazas.
- Versión semver subida en `pyproject.toml` y `uv sync` ejecutado.
