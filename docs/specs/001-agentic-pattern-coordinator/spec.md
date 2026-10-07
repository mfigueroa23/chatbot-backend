# Spec 001 — Asistente virtual con patrón agéntico coordinador

## Contexto y objetivo
Hoy, las consultas de los clientes (canal web) y de los colaboradores internos (Google Chat) las responde una persona,
aunque la mayoría son preguntas frecuentes de un área de negocio concreta. Queremos un asistente virtual que responda
esas preguntas con la información oficial de cada área, que no invente respuestas y que, cuando no sepa responder,
derive la consulta a una persona: en el canal web, a un ejecutivo por chat en vivo, y en el canal interno, al
responsable del área por correo. Así se reduce la carga de atención sin degradar la calidad de la respuesta. La
información interna nunca debe llegar al canal público.

## Usuarios / actores
- **Cliente:** usuario externo y anónimo que escribe por el chat web.
- **Colaborador:** usuario interno que escribe al bot por Google Chat, en un mensaje directo o en un space de grupo.
- **Ejecutivo:** persona interna con usuario y contraseña que toma chats de la cola web y conversa en vivo con el cliente.
- **Responsable de área interna:** persona que recibe por correo las consultas internas que el asistente no pudo responder.
- **Responsable de contenidos:** carga directamente en la base de datos las áreas, categorías, FAQ, system prompts, el horario, los festivos, los canales oficiales, los responsables de cada área y el correo general.

## Historias de usuario
- H1: Como cliente quiero hacer preguntas en el chat web para resolver mis dudas sin esperar a una persona.
- H2: Como colaborador quiero consultar al asistente desde Google Chat para obtener respuestas de las áreas internas.
- H3: Como cliente quiero hablar en vivo con un ejecutivo cuando el asistente no sabe responder, para no quedarme sin solución.
- H4: Como ejecutivo quiero iniciar sesión, ver los chats en espera y tomar uno para atender al cliente en vivo.
- H5: Como responsable de área interna quiero recibir por correo las consultas que el asistente no supo responder, para contactar al colaborador.
- H6: Como responsable de contenidos quiero que los cambios en FAQ y prompts se apliquen sin redesplegar, para mantener las respuestas al día.

## Requisitos funcionales (criterios de aceptación en EARS)

### Coordinación y agentes
- RF-1: CUANDO llegue un mensaje por el canal interno (Google Chat), EL SISTEMA lo procesará con el agente interno.
- RF-2: CUANDO llegue un mensaje por el canal web, EL SISTEMA lo procesará con el agente externo.
- RF-3: EL SISTEMA dará al agente interno acceso solo a las áreas internas.
- RF-4: EL SISTEMA dará al agente externo acceso solo a las áreas externas.
- RF-5: CUANDO el agente interno o el externo reciba una pregunta, EL SISTEMA la delegará en el sub-agente o los sub-agentes de las áreas a las que corresponda.
- RF-6: CUANDO una pregunta corresponda a varias áreas del mismo agente, EL SISTEMA combinará las respuestas de esos sub-agentes en una sola respuesta.
- RF-7: SI en una pregunta combinada alguna de las áreas no puede responder, ENTONCES EL SISTEMA responderá con lo disponible e indicará qué parte no pudo responder.
- RF-8: SI una pregunta mezcla temas de áreas internas y externas, ENTONCES EL SISTEMA pedirá al usuario que reformule su pregunta.
- RF-9: EL SISTEMA construirá cada respuesta de un sub-agente únicamente a partir de las FAQ recuperadas de su área.
- RF-10: EL SISTEMA usará como instrucciones de cada agente y sub-agente el system prompt vigente almacenado en la base de datos.
- RF-11: CUANDO se modifique un system prompt o una FAQ en la base de datos, EL SISTEMA aplicará el cambio a partir del siguiente mensaje recibido.
- RF-12: EL SISTEMA obtendrá el modelo de lenguaje y su API key de la configuración en `property`.
- RF-13: SI falta el modelo o la API key en la configuración, ENTONCES EL SISTEMA responderá con un mensaje de servicio no disponible.
- RF-14: SI falta el modelo o la API key en la configuración, ENTONCES EL SISTEMA registrará un error en el log sin incluir el valor de la API key.
- RF-15: SI un mensaje está vacío o formado solo por espacios, ENTONCES EL SISTEMA pedirá al usuario que escriba su consulta sin enviarla al modelo.
- RF-16: SI un mensaje supera los 5000 caracteres, ENTONCES EL SISTEMA lo rechazará sin enviarlo al modelo.
- RF-17: CUANDO el sistema rechace un mensaje por superar los 5000 caracteres, EL SISTEMA avisará al usuario del límite.
- RF-18: SI el proveedor del modelo falla o supera el tiempo de espera, ENTONCES EL SISTEMA responderá con un mensaje de servicio no disponible, sin detalles técnicos.

### Horario de atención
- RF-19: EL SISTEMA leerá de la base de datos la franja de apertura y cierre de cada día de la semana.
- RF-20: EL SISTEMA leerá de la base de datos la lista de fechas festivas sin atención.
- RF-21: EL SISTEMA evaluará el horario de atención en la zona horaria America/Santiago.
- RF-22: SI la fecha actual es festiva, ENTONCES EL SISTEMA considerará que está fuera de horario.
- RF-23: SI el día actual no tiene franja configurada, ENTONCES EL SISTEMA considerará que está fuera de horario.
- RF-24: EL SISTEMA leerá de la base de datos los canales oficiales que muestra al cliente.

### Canal web: derivación a un ejecutivo
- RF-25: SI en el canal web ningún sub-agente puede responder y la hora actual está dentro del horario de atención, ENTONCES EL SISTEMA ofrecerá al cliente hablar con un ejecutivo.
- RF-26: CUANDO el cliente pida explícitamente hablar con un humano, EL SISTEMA aplicará el mismo flujo que RF-25 y RF-32.
- RF-27: CUANDO el cliente acepte hablar con un ejecutivo, EL SISTEMA le pedirá su nombre y al menos un dato de contacto (correo o teléfono).
- RF-28: SI el cliente entrega un nombre vacío o un dato de contacto con formato inválido, ENTONCES EL SISTEMA se lo volverá a pedir.
- RF-29: SI el cliente no entrega datos válidos tras 3 intentos, ENTONCES EL SISTEMA le mostrará los canales oficiales sin poner su chat en la cola.
- RF-30: CUANDO el cliente entregue datos válidos, EL SISTEMA pondrá su chat en la cola de espera web.
- RF-31: CUANDO un chat entre en la cola de espera, EL SISTEMA informará al cliente de que está en espera de un ejecutivo.
- RF-32: SI en el canal web ningún sub-agente puede responder y la hora actual está fuera del horario de atención, ENTONCES EL SISTEMA pedirá al cliente que reformule su consulta o que contacte con los canales oficiales.
- RF-33: SI el cliente rechaza hablar con un ejecutivo, ENTONCES EL SISTEMA le pedirá que reformule su consulta o que contacte con los canales oficiales.

### Canal web: cola de espera
- RF-34: MIENTRAS sea horario de atención, EL SISTEMA mantendrá en la cola los chats en espera sin límite de tiempo.
- RF-35: SI el cliente se desconecta mientras su chat está en la cola de espera, ENTONCES EL SISTEMA retirará su chat de la cola.
- RF-36: CUANDO termine el horario de atención, EL SISTEMA cerrará los chats que sigan en la cola de espera.
- RF-37: CUANDO el sistema cierre un chat en espera por fin de horario, EL SISTEMA pedirá al cliente que vuelva dentro del horario o que use los canales oficiales.
- RF-38: CUANDO termine el horario de atención, EL SISTEMA mantendrá abiertos los chats ya asignados a un ejecutivo.

### Canal web: chat en vivo
- RF-39: CUANDO un ejecutivo tome un chat en espera, EL SISTEMA lo asignará en exclusiva a ese ejecutivo.
- RF-40: SI un chat ya está asignado, ENTONCES EL SISTEMA impedirá que otro ejecutivo lo tome.
- RF-41: SI el ejecutivo ya tiene asignado el máximo de chats simultáneos configurado en `property`, ENTONCES EL SISTEMA le impedirá tomar otro.
- RF-42: CUANDO un ejecutivo tome un chat, EL SISTEMA le mostrará un resumen con el nombre del cliente, su dato de contacto y la última pregunta que el agente no pudo responder.
- RF-43: CUANDO un ejecutivo tome un chat, EL SISTEMA informará al cliente de que un ejecutivo lo está atendiendo.
- RF-44: MIENTRAS un chat esté asignado a un ejecutivo, EL SISTEMA entregará al ejecutivo cada mensaje del cliente.
- RF-45: MIENTRAS un chat esté asignado a un ejecutivo, EL SISTEMA entregará al cliente cada mensaje del ejecutivo.
- RF-46: MIENTRAS un chat esté asignado a un ejecutivo, EL SISTEMA no generará respuestas del agente externo.
- RF-47: SI el ejecutivo se desconecta de un chat asignado, ENTONCES EL SISTEMA mantendrá el chat asignado a ese ejecutivo durante 1 hora.
- RF-48: SI el ejecutivo se desconecta de un chat asignado, ENTONCES EL SISTEMA avisará al cliente de que el ejecutivo puede volver en un plazo máximo de 1 hora.
- RF-49: SI la sesión del ejecutivo caduca durante un chat asignado, ENTONCES EL SISTEMA lo tratará como una desconexión del ejecutivo.
- RF-50: CUANDO el ejecutivo se reconecte dentro de esa hora, EL SISTEMA le permitirá retomar el chat.
- RF-51: SI el ejecutivo no retoma el chat dentro de 1 hora, ENTONCES EL SISTEMA cerrará el chat.
- RF-52: CUANDO el sistema cierre un chat porque el ejecutivo no lo retomó, EL SISTEMA informará al cliente de que puede volver a escribir o usar los canales oficiales.
- RF-53: SI el cliente se desconecta durante un chat asignado, ENTONCES EL SISTEMA cerrará el chat.
- RF-54: CUANDO un chat se cierre porque el cliente se desconectó, EL SISTEMA avisará al ejecutivo.
- RF-55: CUANDO el ejecutivo cierre un chat, EL SISTEMA dará por terminada la conversación en vivo.
- RF-56: CUANDO el ejecutivo cierre un chat, EL SISTEMA informará al cliente de que la atención terminó.

### Canal interno: derivación a humano
- RF-57: SI en el canal interno ningún sub-agente puede responder, ENTONCES EL SISTEMA indicará al colaborador que el responsable del área lo contactará a la brevedad.
- RF-58: SI en el canal interno ningún sub-agente puede responder, ENTONCES EL SISTEMA enviará un correo al responsable del área con la pregunta y la identidad del colaborador en Google Chat.
- RF-59: SI la pregunta interna no corresponde a ninguna área, ENTONCES EL SISTEMA enviará el correo a la dirección general configurada en la base de datos.
- RF-60: SI falla el envío del correo, ENTONCES EL SISTEMA registrará el fallo en el log.
- RF-61: SI falla el envío del correo, ENTONCES EL SISTEMA pedirá al colaborador que contacte directamente con el área.
- RF-62: EL SISTEMA leerá de la base de datos el correo del responsable de cada área interna.

### Google Chat
- RF-63: SI una petición de Google Chat no trae un token de Google válido para esta aplicación, ENTONCES EL SISTEMA la rechazará con 401.
- RF-64: EL SISTEMA atenderá a cualquier usuario de Google Chat que envíe una petición con un token válido.
- RF-65: CUANDO un colaborador escriba al bot por mensaje directo, EL SISTEMA responderá al mensaje.
- RF-66: CUANDO un colaborador mencione al bot en un space de grupo, EL SISTEMA responderá usando solo el texto que acompaña a la mención.
- RF-67: CUANDO se añada el bot a un mensaje directo o a un space, EL SISTEMA enviará un saludo que describa qué dudas puede resolver.
- RF-68: SI la respuesta no puede generarse antes de 30 s, ENTONCES EL SISTEMA contestará de inmediato que está procesando la consulta.
- RF-69: CUANDO termine de generarse una respuesta que excedió los 30 s, EL SISTEMA la publicará en el mismo space y en el mismo hilo de la consulta original.

### Ejecutivos
- RF-70: CUANDO un ejecutivo envíe un usuario y una contraseña válidos, EL SISTEMA le otorgará una sesión autenticada de 8 horas (configurable en `property`).
- RF-71: SI las credenciales no son válidas, ENTONCES EL SISTEMA rechazará el acceso con un mensaje que no indique qué dato es incorrecto.
- RF-72: SI una cuenta acumula 5 intentos de login fallidos seguidos, ENTONCES EL SISTEMA la bloqueará durante 15 minutos (ambos valores configurables en `property`).
- RF-73: MIENTRAS una cuenta esté bloqueada, EL SISTEMA rechazará el login aunque las credenciales sean válidas.
- RF-74: MIENTRAS un ejecutivo tenga una sesión autenticada, EL SISTEMA le permitirá listar los chats en espera de la cola web.
- RF-75: SI una petición a la cola o a un chat en vivo no trae una sesión válida de ejecutivo, ENTONCES EL SISTEMA la rechazará con 401.

### Sesión del chat web
- RF-76: MIENTRAS una sesión de chat web esté activa, EL SISTEMA mantendrá el contexto de los mensajes anteriores de esa sesión.
- RF-77: EL SISTEMA aislará el contexto de cada sesión, de modo que ninguna respuesta use mensajes de otra sesión.
- RF-78: CUANDO un cliente se reconecte con el identificador de una sesión existente, EL SISTEMA recuperará el contexto de esa sesión con el agente.
- RF-79: EL SISTEMA conservará el contexto de una sesión durante el número de días configurado en `property` (30 por defecto), contados desde su último mensaje.
- RF-80: SI un cliente se reconecta con un identificador de sesión caducado o inexistente, ENTONCES EL SISTEMA iniciará una sesión nueva sin contexto.
- RF-81: SI ya hay 50 sesiones web activas, contando las que están en un chat en vivo, ENTONCES EL SISTEMA informará al nuevo cliente de que hay alta demanda y le mostrará los canales oficiales.
- RF-82: SI la base de datos deja de estar disponible durante una conversación del chat web, ENTONCES EL SISTEMA enviará al cliente un mensaje de servicio no disponible.
- RF-83: SI la base de datos deja de estar disponible durante una conversación del chat web, ENTONCES EL SISTEMA registrará el error en el log.

## Requisitos no funcionales
- RNF-1: El chat web atenderá al menos 50 sesiones simultáneas sin errores atribuibles a la concurrencia.
- RNF-2: Con 50 sesiones simultáneas, el p95 del tiempo hasta la respuesta completa del agente en el canal web será menor de 5000 ms.
- RNF-3: Ninguna respuesta del canal web contendrá información de áreas internas.
- RNF-4: Las contraseñas de los ejecutivos nunca se almacenan en texto plano.
- RNF-5: La API key del modelo, la credencial de Google y la del correo no aparecen en logs, respuestas ni en el repositorio (ver SECURITY.md).
- RNF-6: Todos los mensajes al usuario y los logs están en español.
- RNF-7: Si la base de datos no está disponible, los endpoints HTTP responden 503 y registran el error en log (constitución, punto 9).

## Casos límite
- Un área sin FAQ cargadas o sin system prompt se trata como "no puede responder".
- Cuando dos ejecutivos toman el mismo chat a la vez, solo uno lo obtiene (RF-40).
- Si el cliente se desconecta mientras el agente genera una respuesta, la respuesta se descarta y no afecta a otras sesiones.
- Si una solicitud llega justo en el minuto de cierre, cuenta como fuera de horario (la franja incluye la apertura y excluye el cierre).
- Si el horario cierra con chats en vivo en curso, esos chats continúan (RF-38).
- Si un cliente intenta que el agente externo revele su system prompt o información interna, el sistema no lo hace (RNF-3).

## Fuera de alcance
- Endpoints de administración (CRUD) de áreas, categorías, FAQ, system prompts, horario, festivos, canales oficiales, responsables y correo general: se cargan directamente en la base de datos.
- Notificaciones activas a los ejecutivos: revisan la cola después de iniciar sesión.
- Transferir un chat en vivo de un ejecutivo a otro.
- Que el cliente retome un chat en vivo después de desconectarse: el chat se cierra.
- Que el ejecutivo vea la conversación completa con el bot: solo ve el resumen (RF-42).
- Historial de chats cerrados consultable por los ejecutivos o con fines de analítica.
- Cola de solicitudes del canal interno y reintentos del correo: solo se envía un correo.
- Inicio de sesión o registro de clientes: el cliente web es anónimo.
- Tarjetas, comandos, diálogos y página principal de Google Chat: solo se atienden mensajes de texto y el alta del bot en un space.
- Restringir el acceso a Google Chat por dominio o por lista de spaces: la visibilidad del bot se controla desde la consola de Google Workspace.
- Frontend del chat web y del panel de ejecutivos (solo backend).
- Idiomas distintos del español y zonas horarias distintas de America/Santiago.
- Alta, baja, desbloqueo manual y gestión de ejecutivos por API.
- Métricas, dashboards y valoración de respuestas.

## Criterios de finalización
- Todos los RF tienen al menos un test `*_test.py` en verde y ningún test se conecta a la base de datos (constitución, punto 6).
- La lógica que depende de la base de datos, de conexiones o del tiempo (asignación exclusiva, plazo de 1 hora, fin de horario, bloqueo de login, caducidad de sesiones, recuperación del contexto) se prueba con dobles y con un reloj simulado, sin esperas reales.
- `uv run pyright` sin errores.
- Demo manual en el despliegue, contra PostgreSQL real:
  1. Pregunta respondida por FAQ en el chat web, por DM de Google Chat y por mención en un space.
  2. Derivación a la cola dentro de horario y chat en vivo entre cliente y ejecutivo, hasta que el ejecutivo lo cierra.
  3. Dos ejecutivos intentan tomar el mismo chat y solo uno lo consigue.
  4. El ejecutivo se desconecta y retoma el chat dentro de la hora.
  5. El cliente se desconecta y el chat se cierra.
  6. Mensaje de reformular fuera de horario y en un día festivo.
  7. Correo al responsable de área cuando el canal interno no sabe responder.
  8. Reconexión del cliente con su sesión y recuperación del contexto.
- README actualizado con los endpoints y las properties nuevas.

## Dudas abiertas
Ninguna.

## Decisiones registradas
- **Constitución, punto 4 (enmendado el 2026-10-07):** `property` guarda la configuración técnica; los datos de negocio (áreas, FAQ, prompts, horario, festivos, canales oficiales, responsables, correo general) van en tablas propias.
- **Constitución, punto 6:** se mantiene. La verificación de lo que depende de la base de datos se hace con dobles y un reloj simulado, más la demo manual en el despliegue.
- **Constitución, punto 1:** el usuario aprobó las dependencias nuevas de orquestación de agentes, checkpointer y RAG/embeddings.
- El chat en vivo entre ejecutivo y cliente entra en el alcance de esta iteración.
- Valores por defecto aprobados por el usuario el 2026-10-07: rechazo de mensajes de más de 5000 caracteres; 30 días desde el último mensaje; p95 medido hasta la respuesta completa con 50 sesiones; datos de contacto obligatorios con 3 intentos; aviso al cliente cuando el ejecutivo se desconecta; los chats en vivo cuentan para el límite de 50; mensaje de no disponible si cae la base de datos en el chat web; respuesta parcial en las preguntas combinadas; la caducidad de la sesión del ejecutivo cuenta como desconexión.

## Notas para el plan (decisiones técnicas acordadas, no forman parte del contrato)
- Orquestación con LangGraph (patrón coordinador de Google Cloud) y checkpointer en PostgreSQL para la memoria de sesión.
- Patrón strategy para la selección del agente según el canal.
- Chat web y chat en vivo del ejecutivo por WebSocket. Google Chat por un endpoint HTTP, como app de Chat basada en eventos de interacción o como complemento de Google Workspace (por decidir en el plan).
- **Verificación de Google Chat:** token Bearer firmado por `chat@system.gserviceaccount.com`, con audiencia en la URL del endpoint o en el número de proyecto.
- **Respuesta asíncrona en Google Chat:** `spaces.messages.create` con una cuenta de servicio con permiso `chat.bot`; la credencial va en `property`.
- El envío de correo necesita configuración SMTP o de proveedor en `property`.
- **Properties nuevas previstas:** modelo, API key, días de retención de sesión, máximo de chats por ejecutivo, duración de la sesión del ejecutivo, intentos y minutos de bloqueo, credenciales de Google Chat y del correo.
- **Tablas de negocio:** áreas (con su ámbito interno o externo y el correo del responsable), categorías, preguntas frecuentes, system prompts, horario por día, festivos, canales oficiales, correo general, ejecutivos y chats de la cola web (estado, ejecutivo asignado, desconexión).
- Recuperación de FAQ mediante RAG.
- Con varias réplicas en Kubernetes, el cliente y el ejecutivo de un mismo chat pueden estar conectados a pods distintos, y el cierre por fin de horario o por el plazo de 1 hora necesita un disparador temporal.
- **RNF-2:** el p95 < 5000 ms hasta la respuesta completa, con RAG y varios sub-agentes, es exigente; conviene validarlo pronto con una prueba de carga.
