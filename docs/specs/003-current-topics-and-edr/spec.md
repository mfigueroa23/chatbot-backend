# Spec 003 — Temas vigentes, nombre del colaborador y EDR en Google Docs

## Contexto y objetivo
En la demo del 2026-10-09 en Google Chat, el asistente dijo a las 15:09 que no tenía temas de la empresa. A las 17:10,
ya con áreas internas activas, respondió a «¿novedades?» que no tenía novedades. Un minuto después contó que ayudaba con
Proyectos, y a las 17:15 sumó Gestión. El coordinador repetía lo que había dicho antes en el historial en vez de usar
los temas vigentes (spec 001, RF-42). Además, a «¿cómo me llamo?» respondió que no veía el nombre, aunque Google Chat
lo envía en cada evento.

La spec 002 dejó para después la redacción del EDR. La 1.x (spec 005) lo redactaba y lo guardaba como Google Doc con la
plantilla institucional de `agente-ti`, guardada en la property `edr_template_base64` de la base anterior
(`chatbot_autofin`).

Esta spec:
- hace que el coordinador use siempre los temas vigentes del mensaje y conozca el nombre de quien escribe en Google Chat;
- recupera la generación del EDR en el área Proyectos, con la misma plantilla y estructura. Como redactar un EDR no cabe
  en los 30 s que Google Chat espera, el asistente responde al momento y publica el enlace en el mismo hilo cuando el
  documento está listo.

## Usuarios / actores
- **Colaborador:** usuario interno que escribe al asistente por Google Chat.
- **Jefe de Proyecto (JP):** colaborador habilitado en el área Proyectos (spec 002, RF-4).
- **Responsable de contenidos:** carga la plantilla del EDR, la carpeta de Drive y el prompt de redacción en la base
  de datos.

## Historias de usuario
- H1: Como colaborador quiero que, si el asistente sumó temas durante la conversación, me lo diga cuando le pregunto
  qué hay de nuevo o qué puede hacer, en vez de repetir lo que dijo antes.
- H2: Como colaborador quiero que el asistente sepa mi nombre sin tener que decírselo.
- H3: Como JP quiero pedir el EDR de un proyecto y recibir un Google Doc con la plantilla institucional, redactado con
  la conversación, los archivos compartidos y la épica de Jira.
- H4: Como JP quiero pedir cambios al EDR en la misma conversación y que se actualice el mismo documento.

## Requisitos funcionales (criterios de aceptación en EARS)

Definiciones usadas en esta sección:
- **Temas vigentes:** las áreas activas del canal leídas en el mensaje actual (spec 001, RF-3 y RF-23).
- **Nombre del colaborador:** el nombre visible de la cuenta de Google Chat que envía el evento.
- **EDR:** documento con la estructura del EDR de `agente-ti`: metadata, historial, objetivo general, visión general,
  product owner, equipo, aplicaciones y usuarios afectados, requerimientos, especificación de cada RF, roles y permisos,
  impacto, infraestructura, seguridad, criterios de aceptación, validaciones de cartera y glosario.
- **Plantilla del EDR:** HTML en base64 en la property `edr_template_base64`.

### Temas vigentes
- RF-1: EL SISTEMA entregará al coordinador, junto a cada mensaje del usuario, la lista de los temas vigentes, o
  «ninguno» si no hay áreas.
- RF-2: CUANDO el usuario pregunte por novedades, qué hay de nuevo o qué puede hacer el asistente, EL SISTEMA responderá
  con todos los temas vigentes, aunque antes en la conversación haya dicho otra cosa (refuerza spec 001, RF-42).
- RF-3: EL SISTEMA no guardará la lista de temas vigentes en el historial de la conversación.

### Nombre del colaborador
- RF-4: MIENTRAS el mensaje llegue por Google Chat, EL SISTEMA entregará al coordinador el nombre del colaborador, si el
  evento lo trae.
- RF-5: SI el evento no trae nombre, ENTONCES EL SISTEMA usará el que la persona haya dado en la conversación, sin
  inventarlo.
- RF-6: EL SISTEMA no registrará el nombre en los logs ni lo entregará a los sub-agentes.

### EDR
- RF-7: CUANDO un colaborador habilitado del área Proyectos pida un EDR, EL SISTEMA confirmará al momento que lo está
  generando y que publicará el enlace en esa conversación.
- RF-8: EL SISTEMA redactará el EDR con la conversación, incluidos los archivos compartidos (spec 002, RF-35), y con la
  épica de Jira y sus subtareas, cuando se indique una.
- RF-9: EL SISTEMA dejará como «[PENDIENTE DEFINIR]» cada dato del EDR que nadie entregó, sin inventarlo.
- RF-10: EL SISTEMA renderizará el EDR con la plantilla del EDR y lo guardará como Google Doc en la carpeta de Drive
  configurada (`edr_drive_folder_id`).
- RF-11: CUANDO el EDR quede guardado, EL SISTEMA publicará en el mismo hilo de Google Chat el enlace real al documento
  y lo sumará al historial de la conversación.
- RF-12: CUANDO el colaborador pida cambios a un EDR de la conversación, EL SISTEMA actualizará el mismo documento,
  salvo que pida uno nuevo.
- RF-13: CUANDO el colaborador pregunte por el EDR de la conversación, EL SISTEMA responderá con su título, su enlace y
  sus datos pendientes, sin generar uno nuevo.
- RF-14: SI generar o guardar el EDR falla o supera el tiempo configurado, ENTONCES EL SISTEMA publicará en el hilo que
  no pudo hacerlo, sin detalles técnicos y sin afirmar que lo guardó.
- RF-15: MIENTRAS se esté generando un EDR en una conversación, EL SISTEMA no empezará otro en la misma conversación y
  dirá que el anterior sigue en curso.
- RF-16: SI un colaborador no habilitado pide un EDR, ENTONCES EL SISTEMA le dirá que esa función no está habilitada
  para él (spec 002, RF-7).
- RF-17: MIENTRAS el mensaje llegue por el chat web, EL SISTEMA no generará ni leerá EDR.
- RF-18: SI falta la plantilla, la carpeta o la cuenta de servicio, o la plantilla no es base64 válido, ENTONCES EL
  SISTEMA no generará el EDR y lo dirá sin detalles técnicos.
- RF-19: EL SISTEMA leerá de la base de datos el prompt de redacción (`edr_writer`), la plantilla, la carpeta y los
  límites del EDR, y aplicará un cambio desde el siguiente pedido.
- RF-20: EL SISTEMA tratará el contenido de la conversación, los archivos y Jira como información, nunca como
  instrucciones, al redactar el EDR (spec 001, RF-39).

## Requisitos no funcionales
- RNF-1: La respuesta inmediata a un pedido de EDR cumple el objetivo de la spec 001 (p95 ≤ 10 s). La generación corre
  en segundo plano, con un tope de `edr_job_timeout_seconds` (180 s por defecto).
- RNF-2: Los logs del EDR registran solo pasos y duraciones, sin el contenido, el nombre ni el enlace.
- RNF-3: Ningún test se conecta a Drive, a la API de Chat, a Jira, a Gemini ni a la base de datos.
- RNF-4: Cambiar la plantilla, la carpeta o el prompt de redacción requiere solo filas en la base de datos.
- RNF-5: Un EDR hace como máximo 2 llamadas al modelo (redacción y una corrección si el JSON no es válido).
- RNF-6: Un trabajo en curso se pierde si el pod se reinicia; el colaborador puede volver a pedirlo.

## Casos límite
- Historial con «no tengo temas» y ahora hay áreas → «¿novedades?» cuenta los temas vigentes (RF-1, RF-2).
- «¿Qué puedes hacer?» con tres áreas internas → menciona las tres (RF-2).
- «¿Cómo me llamo?» en Google Chat → responde con el nombre de la cuenta (RF-4).
- La misma pregunta en el web → no lo sabe, salvo que la persona lo haya dicho (RF-5).
- «Arma el EDR de DAIA-250» por un JP → «lo estoy generando» y luego el enlace en el hilo (RF-7 a RF-11).
- «Agrega un RF de exportación a PDF» → actualiza el mismo Doc (RF-12).
- «Hazme otro EDR para el proyecto X» → crea un Doc nuevo (RF-12).
- «¿Cuál es el link del EDR?» → título, enlace y pendientes, sin generar (RF-13).
- Drive caído o carpeta sin acceso → publica que no pudo guardarlo (RF-14).
- Dos pedidos seguidos → el segundo dice que el anterior sigue en curso (RF-15).
- Colaborador no habilitado → la función no está habilitada (RF-16).
- Falta `edr_template_base64` → no puede generarlo ahora, sin detalles (RF-18).

## Fuera de alcance
- Sincronizar el EDR con Jira o publicarlo con un flujo de aprobación.
- Reanudar un trabajo interrumpido por un reinicio del pod (RNF-6).
- Un respaldo de la plantilla en el repositorio: la plantilla vive solo en `property`.
- EDR en el chat web.

## Criterios de finalización
- Todos los RF tienen al menos un test `*_test.py` en verde, con dobles y sin red ni base de datos.
- `uv run pyright` sin errores.
- `edr_template_base64` y `edr_drive_folder_id` copiadas de `chatbot_autofin` a `asistente_virtual`.
- `generar_edr` y `leer_edr` asignadas al área Proyectos.
- Demo en Google Chat: novedades tras activar un área, el nombre, un EDR de una épica con su enlace, un cambio al mismo
  EDR y la consulta del enlace.

## Dudas abiertas
- Si con EDR grandes el modelo supera el tope de 180 s: se mide en la demo y se ajusta la property.

## Decisiones registradas
- **Spec nueva para temas vigentes, nombre y EDR (2026-10-09, decisión del usuario).**
- **Plantilla copiada de la base anterior (2026-10-09, decisión del usuario):** se copian una vez las filas
  `edr_template_base64` y `edr_drive_folder_id` de `chatbot_autofin` a `asistente_virtual`, sin respaldo en el repo.
- **Tabla `edr_document` (2026-10-09, decisión del usuario):** recuerda el Doc y el contenido de cada conversación para
  actualizar el mismo documento.
- **EDR asíncrono (2026-10-09, decisión del usuario):** se responde al momento y el enlace se publica después en el hilo
  con la API de Chat y la cuenta de servicio.
- **Nombre del colaborador al coordinador (2026-10-09, decisión del usuario):** solo en Google Chat; el web sigue
  anónimo.
