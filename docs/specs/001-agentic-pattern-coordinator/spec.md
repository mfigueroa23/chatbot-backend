# Spec 001 — Asistente virtual con patrón agéntico coordinador

## Contexto y objetivo
Hoy, las consultas de los clientes (canal web) y de los colaboradores internos (Google Chat) las responde una persona,
aunque la mayoría son preguntas frecuentes de un área de negocio concreta o solicitudes que un área debe ejecutar (una
copia del contrato, cargar algo en un sistema). Queremos un asistente virtual que, con una sola llamada al modelo por
mensaje, use el conocimiento de cada área (sus FAQ y sus procedimientos) y pueda avisar al área. El asistente
responde con la información oficial, no inventa respuestas y, si existe un procedimiento, explica qué se hará, pide los
datos necesarios y avisa al área en su space de Google Chat para que una persona lo ejecute. Cuando no sabe responder,
deriva: en el canal web, a un ejecutivo por chat en vivo, y en el canal interno, al space del área. Así se reduce la
carga de atención sin degradar la calidad. La información interna y el funcionamiento interno del asistente nunca deben
llegar al usuario.

## Usuarios / actores
- **Cliente:** usuario externo y anónimo que escribe por el chat web.
- **Colaborador:** usuario interno que escribe al bot por Google Chat, en un mensaje directo o en un space de grupo.
- **Ejecutivo:** persona interna con usuario y contraseña que toma chats de la cola web y conversa en vivo con el cliente.
- **Equipo del área:** personas del área (interna o externa) que reciben en el space de Google Chat del área las solicitudes y las consultas que el asistente no pudo responder, y delegan su ejecución.
- **Responsable de contenidos:** carga directamente en la base de datos las áreas, categorías, FAQ, procedimientos y los datos que exige cada uno, system prompts, el horario, los festivos, los canales oficiales, el space de Google Chat de cada área y el space general.

## Historias de usuario
- H1: Como cliente quiero hacer preguntas en el chat web para resolver mis dudas sin esperar a una persona.
- H2: Como colaborador quiero consultar al asistente desde Google Chat para obtener respuestas de las áreas internas.
- H3: Como cliente quiero hablar en vivo con un ejecutivo cuando el asistente no sabe responder, para no quedarme sin solución.
- H4: Como ejecutivo quiero iniciar sesión, ver los chats en espera y tomar uno para atender al cliente en vivo.
- H5: Como equipo del área quiero recibir en el space de mi área las consultas que el asistente no supo responder, para contactar al colaborador.
- H6: Como responsable de contenidos quiero que los cambios en FAQ, procedimientos y prompts se apliquen sin redesplegar, para mantener las respuestas al día.
- H7: Como cliente quiero pedir un trámite (p. ej. una copia de mi contrato) en el chat web para que el área lo gestione sin tener que llamar.
- H8: Como colaborador quiero pedir a otra área un trámite interno desde Google Chat para que se ejecute sin buscar a quién escribir.
- H9: Como equipo del área quiero recibir en el space de mi área cada solicitud con los datos necesarios para delegarla a un colaborador.
- H10: Como colaborador quiero que el asistente recuerde lo que ya dije en el mismo hilo de Google Chat para no repetir datos.

## Requisitos funcionales (criterios de aceptación en EARS)

### Coordinación y agentes
- RF-1: CUANDO llegue un mensaje por el canal interno (Google Chat), EL SISTEMA lo procesará con el agente interno.
- RF-2: CUANDO llegue un mensaje por el canal web, EL SISTEMA lo procesará con el agente externo.
- RF-3: EL SISTEMA dará al agente interno acceso solo a las áreas internas.
- RF-4: EL SISTEMA dará al agente externo acceso solo a las áreas externas.
- RF-5: CUANDO el agente interno o el externo reciba un mensaje, EL SISTEMA lo responderá con el conocimiento (FAQ y procedimientos) de las áreas de su canal a las que corresponda.
- RF-6: CUANDO una pregunta corresponda a varias áreas del mismo agente, EL SISTEMA combinará la información de esas áreas en una sola respuesta.
- RF-7: SI en una pregunta combinada alguna de las áreas no puede responder, ENTONCES EL SISTEMA responderá con lo disponible e indicará qué parte no pudo responder.
- RF-8: SI una pregunta mezcla temas de áreas internas y externas, ENTONCES EL SISTEMA pedirá al usuario que reformule su pregunta.
- RF-9: EL SISTEMA construirá cada respuesta únicamente a partir de las FAQ o los procedimientos recuperados de las áreas de su canal.
- RF-10: EL SISTEMA usará como instrucciones del agente y de cada área el system prompt vigente almacenado en la base de datos.
- RF-11: CUANDO se modifique un system prompt, una FAQ o un procedimiento en la base de datos, EL SISTEMA aplicará el cambio a partir del siguiente mensaje recibido.
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
- RF-25: SI en el canal web no se encuentra una FAQ ni un procedimiento que responda y la hora actual está dentro del horario de atención, ENTONCES EL SISTEMA ofrecerá al cliente hablar con un ejecutivo.
- RF-26: CUANDO el cliente pida explícitamente hablar con un humano, EL SISTEMA aplicará el mismo flujo que RF-25 y RF-32.
- RF-27: CUANDO el cliente acepte hablar con un ejecutivo, EL SISTEMA le pedirá su nombre y al menos un dato de contacto (correo o teléfono).
- RF-28: SI el cliente entrega un nombre vacío o un dato de contacto con formato inválido, ENTONCES EL SISTEMA se lo volverá a pedir.
- RF-29: SI el cliente no entrega datos válidos tras 3 intentos, ENTONCES EL SISTEMA le mostrará los canales oficiales sin poner su chat en la cola.
- RF-30: CUANDO el cliente entregue datos válidos, EL SISTEMA pondrá su chat en la cola de espera web.
- RF-31: CUANDO un chat entre en la cola de espera, EL SISTEMA informará al cliente de que está en espera de un ejecutivo.
- RF-32: SI en el canal web no se encuentra una FAQ ni un procedimiento que responda y la hora actual está fuera del horario de atención, ENTONCES EL SISTEMA pedirá al cliente que reformule su consulta o que contacte con los canales oficiales.
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

### Canal interno: derivación al área
- RF-57: SI en el canal interno no se encuentra una FAQ ni un procedimiento que responda, ENTONCES EL SISTEMA indicará al colaborador que el área lo contactará a la brevedad.
- RF-58: SI en el canal interno no se encuentra una FAQ ni un procedimiento que responda, ENTONCES EL SISTEMA notificará la consulta al space de Google Chat del área, con la pregunta y la identidad del colaborador en Google Chat.
- RF-59: SI la consulta interna no corresponde a ninguna área, ENTONCES EL SISTEMA la notificará al space general configurado en la base de datos.
- RF-60: SI falla la entrega de una notificación al space, ENTONCES EL SISTEMA registrará el fallo en el log.
- RF-61: SI falla la entrega de una notificación de una solicitud o consulta interna, ENTONCES EL SISTEMA pedirá al colaborador que contacte directamente con el área.
- RF-62: EL SISTEMA leerá de la base de datos el space de Google Chat de cada área y el space general.

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

### Conocimiento por área
- RF-84: CUANDO llegue un mensaje, EL SISTEMA buscará las FAQ de las áreas de su canal relacionadas con el mensaje antes de generar la respuesta.
- RF-85: CUANDO llegue un mensaje, EL SISTEMA buscará los procedimientos de las áreas de su canal relacionados con el mensaje antes de generar la respuesta.
- RF-86: EL SISTEMA no entregará al modelo FAQ ni procedimientos de áreas de otro canal.
- RF-87: EL SISTEMA tratará las FAQ y los procedimientos como contenidos distintos, cada uno con su propia búsqueda.
- RF-88: EL SISTEMA aplicará las búsquedas de FAQ y de procedimientos tanto en el canal web como en el interno.
- RF-89: SI una respuesta generada no se apoya en ninguna FAQ ni en ningún procedimiento recuperados por encima del umbral de similitud, ENTONCES EL SISTEMA descartará esa respuesta.
- RF-90: CUANDO el sistema descarte una respuesta, EL SISTEMA tratará la consulta como "no puede responder".

### Procedimientos
- RF-91: CUANDO se recupere un procedimiento que corresponde a la solicitud, EL SISTEMA explicará al usuario los pasos que seguirá el área.
- RF-92: CUANDO se recupere un procedimiento que exige datos, EL SISTEMA pedirá al usuario cada dato exigido que aún no haya entregado en la conversación.
- RF-93: SI el usuario entrega un dato con formato inválido para el procedimiento, ENTONCES EL SISTEMA se lo volverá a pedir.
- RF-94: SI el usuario no entrega datos válidos tras 3 intentos, ENTONCES EL SISTEMA dejará de pedirlos y aplicará el flujo de "sin respuesta" del canal.
- RF-95: CUANDO el usuario haya entregado todos los datos que exige el procedimiento, EL SISTEMA notificará la solicitud al space de Google Chat del área.
- RF-96: CUANDO el sistema notifique una solicitud, EL SISTEMA incluirá en la notificación el procedimiento, los datos entregados y la identidad del solicitante.
- RF-97: CUANDO el sistema notifique una solicitud del canal interno, EL SISTEMA identificará al solicitante con su nombre y correo de Google Chat.
- RF-98: CUANDO un procedimiento se inicie desde el canal web, EL SISTEMA pedirá al cliente su nombre y al menos un dato de contacto (correo o teléfono), aunque el procedimiento no los exija.
- RF-99: CUANDO la notificación de una solicitud se entregue, EL SISTEMA confirmará al usuario que el área gestionará su solicitud.
- RF-100: EL SISTEMA no entregará al usuario datos personales ni documentos como resultado de un procedimiento: la ejecución y la verificación de identidad las hace una persona del área.
- RF-101: SI falla la entrega de una notificación de una solicitud del canal web, ENTONCES EL SISTEMA mostrará al cliente los canales oficiales.
- RF-102: SI el área a la que corresponde una notificación no tiene space configurado, ENTONCES EL SISTEMA tratará la notificación como fallida (RF-60, RF-61 y RF-101).

### Memoria del canal interno
- RF-103: MIENTRAS una conversación de Google Chat siga en el mismo hilo, EL SISTEMA mantendrá el contexto de los mensajes anteriores de ese hilo.
- RF-104: EL SISTEMA aislará el contexto de cada hilo de Google Chat, de modo que ninguna respuesta use mensajes de otro hilo, aunque sea del mismo space.
- RF-105: EL SISTEMA conservará el contexto de un hilo de Google Chat durante el número de días configurado en `property` para Google Chat (30 por defecto), contados desde el último mensaje del hilo.

### Protección frente a manipulación (jailbreak)
- RF-106: SI un usuario pide al asistente que revele sus instrucciones, sus prompts, sus herramientas, las áreas que no corresponden a su canal o cualquier detalle de su funcionamiento interno, ENTONCES EL SISTEMA no los revelará.
- RF-107: SI un usuario intenta que el asistente ignore, cambie o amplíe sus instrucciones (p. ej. "ignora lo anterior", juegos de rol, instrucciones dentro de los datos que entrega), ENTONCES EL SISTEMA mantendrá su comportamiento.
- RF-108: CUANDO el sistema rechace una petición de RF-106 o RF-107, EL SISTEMA responderá que solo puede ayudar con consultas de las áreas de su canal, sin explicar el motivo técnico.
- RF-109: SI una respuesta generada contiene un fragmento de las instrucciones o prompts, nombres internos del asistente o código, ENTONCES EL SISTEMA la sustituirá por la respuesta de RF-108 antes de enviarla.

## Requisitos no funcionales
- RNF-1: El chat web atenderá al menos 50 sesiones simultáneas sin errores atribuibles a la concurrencia.
- RNF-2: Con 50 sesiones simultáneas, el p95 del tiempo hasta la respuesta completa del agente en el canal web será menor de 5000 ms.
- RNF-3: Ninguna respuesta del canal web contendrá información, FAQ ni procedimientos de áreas internas.
- RNF-4: Las contraseñas de los ejecutivos nunca se almacenan en texto plano.
- RNF-5: La API key del modelo y la credencial de Google no aparecen en logs, respuestas ni en el repositorio (ver SECURITY.md).
- RNF-6: Todos los mensajes al usuario y los logs están en español.
- RNF-7: Si la base de datos no está disponible, los endpoints HTTP responden 503 y registran el error en log (constitución, punto 9).
- RNF-8: Los datos que el usuario entrega para un procedimiento solo se envían al space del área que lo gestiona y no aparecen en los logs.
- RNF-10: EL SISTEMA hará como máximo una llamada de generación al modelo por mensaje del usuario; las búsquedas por embeddings no cuentan como llamada de generación.
- RNF-9: Ninguna respuesta contendrá el texto de los prompts, los nombres de las herramientas internas ni la estructura del asistente, comprobado con un conjunto de al menos 20 intentos de manipulación conocidos.

## Casos límite
- Un área sin FAQ ni procedimientos, o sin system prompt, se trata como "no puede responder"; con solo uno de los dos contenidos usa el que tiene.
- Una consulta que encaja a la vez con una FAQ y con un procedimiento del área: la respuesta usa ambos contenidos.
- Una solicitud que corresponde a varias áreas con procedimiento: se pide la unión de los datos exigidos y cada área recibe solo los datos de su procedimiento.
- El usuario cambia de tema mientras se le piden datos: la solicitud queda abandonada sin notificar y se atiende la nueva consulta.
- El usuario entrega en un solo mensaje varios de los datos exigidos: no se le vuelven a pedir.
- Un cliente web se desconecta a mitad de la recogida de datos: no se notifica nada; si vuelve con su sesión, sigue donde quedó (RF-78).
- Cuando dos ejecutivos toman el mismo chat a la vez, solo uno lo obtiene (RF-40).
- Si el cliente se desconecta mientras el agente genera una respuesta, la respuesta se descarta y no afecta a otras sesiones.
- Si una solicitud llega justo en el minuto de cierre, cuenta como fuera de horario (la franja incluye la apertura y excluye el cierre).
- Si el horario cierra con chats en vivo en curso, esos chats continúan (RF-38).
- Si un cliente intenta que el agente externo revele su system prompt, sus herramientas o información interna, el sistema no lo hace (RF-106, RNF-3).
- Instrucciones de manipulación escondidas en los datos que entrega el usuario (p. ej. en el nombre o en un dato de un procedimiento) no cambian el comportamiento (RF-107).
- Una solicitud de procedimiento que mezcla áreas internas y externas: se pide reformular (RF-8).

## Fuera de alcance
- Endpoints de administración (CRUD) de áreas, categorías, FAQ, procedimientos, system prompts, horario, festivos, canales oficiales y spaces: se cargan directamente en la base de datos.
- Notificaciones activas a los ejecutivos: revisan la cola después de iniciar sesión.
- Transferir un chat en vivo de un ejecutivo a otro.
- Que el cliente retome un chat en vivo después de desconectarse: el chat se cierra.
- Que el ejecutivo vea la conversación completa con el bot: solo ve el resumen (RF-42).
- Historial de chats cerrados consultable por los ejecutivos o con fines de analítica.
- Reintentos de las notificaciones al space: si falla, se aplica RF-60, RF-61 o RF-101.
- Notificaciones por correo y mensajes directos a personas concretas del área: solo se publica en el space del área.
- Integraciones con sistemas externos (APIs, servidores MCP) desde los agentes: irán en una spec posterior.
- Ejecución automática de procedimientos: siempre los ejecuta una persona del área.
- Verificación de la identidad del cliente por el asistente: la hace el área.
- Seguimiento del estado de una solicitud (número de caso, avisos de avance o cierre) y respuesta del área a través del asistente.
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
  7. Aviso en el space del área cuando el canal interno no sabe responder.
  8. Reconexión del cliente con su sesión y recuperación del contexto, incluida una pregunta de seguimiento que depende de él.
  9. Cliente web pide copia de su contrato: el asistente explica, pide los datos y el space del área recibe la solicitud.
  10. Colaborador pide desde un space un trámite a Gestión: se explica, se piden los datos y el space de Gestión recibe la solicitud.
  11. En un mismo space, dos hilos distintos no comparten contexto; dentro de un hilo, el asistente recuerda los datos ya dados.
  12. Batería de al menos 20 intentos de manipulación (revelar prompt, herramientas o áreas internas; "ignora tus instrucciones"; juego de rol): ninguno tiene éxito.
- El descarte de respuestas sin FAQ ni procedimiento recuperado (RF-89) se prueba con un doble del modelo que intenta responder sin consultar.
- README actualizado con los endpoints y las properties nuevas.

## Dudas abiertas
Ninguna.

## Decisiones registradas
- **Constitución, punto 4 (enmendado el 2026-10-07):** `property` guarda la configuración técnica; los datos de negocio (áreas, FAQ, procedimientos, prompts, horario, festivos, canales oficiales, spaces) van en tablas propias.
- **Constitución, punto 6:** se mantiene. La verificación de lo que depende de la base de datos se hace con dobles y un reloj simulado, más la demo manual en el despliegue.
- **Constitución, punto 1:** el usuario aprobó las dependencias nuevas de orquestación de agentes, checkpointer y RAG/embeddings.
- El chat en vivo entre ejecutivo y cliente entra en el alcance de esta iteración.
- Valores por defecto aprobados por el usuario el 2026-10-07: rechazo de mensajes de más de 5000 caracteres; 30 días desde el último mensaje; p95 medido hasta la respuesta completa con 50 sesiones; datos de contacto obligatorios con 3 intentos; aviso al cliente cuando el ejecutivo se desconecta; los chats en vivo cuentan para el límite de 50; mensaje de no disponible si cae la base de datos en el chat web; respuesta parcial en las preguntas combinadas; la caducidad de la sesión del ejecutivo cuenta como desconexión.
- **Ampliación del 2026-10-07 (absorbe la spec 002 «agentes con tools», que se elimina; los sub-agentes con tools se sustituyeron después por una sola llamada):** cada agente delegaba en sub-agentes por área con capacidades propias (FAQ, procedimientos, avisar al área y, en el canal web, derivar a un ejecutivo); FAQ y procedimientos son contenidos distintos y conviven en ambos canales; "seguir un procedimiento" es explicar los pasos, pedir los datos exigidos (3 intentos) y notificar al área; la notificación va al space de Google Chat del área y sustituye al correo; un área sin space cuenta como notificación fallida; el asistente no verifica la identidad del cliente; los spaces donde está la app no restringen áreas; la memoria de Google Chat va por hilo con su propia property de retención (30 días por defecto); integraciones MCP/API fuera de alcance.
- **Una sola llamada al modelo por mensaje (2026-10-07, decisión del usuario por latencia):** las búsquedas se hacen antes de llamar al modelo y una única llamada genera la respuesta; los sub-agentes con llamadas propias se descartan. Los mensajes del procedimiento (datos faltantes o inválidos, solicitud enviada o fallida) son textos fijos con los nombres de los datos. Se añade un auditor determinista de fugas (RF-109).
- **Google Chat como complemento de Google Workspace (2026-10-07):** la app ya está creada en esa modalidad (eventos `chat.*`, respuesta `hostAppDataAction` y token de Google firmado para la cuenta de servicio `gcp-sa-gsuiteaddons` del proyecto). Sustituye a la app de Chat de eventos de interacción.
- **Protección frente a manipulación (2026-10-07):** se resuelve en los prompts almacenados en la base de datos (prompt del agente de cada canal y reglas comunes de las áreas), con la marca de manipulación de la respuesta estructurada y el auditor de RF-109, que prohíben revelar instrucciones, prompts, herramientas o funcionamiento interno y obedecer cambios de instrucciones del usuario.

## Notas para el plan (decisiones técnicas acordadas, no forman parte del contrato)
- Orquestación con LangGraph (patrón coordinador de Google Cloud) y checkpointer en PostgreSQL para la memoria de sesión, también para Google Chat con `thread_id` = nombre del hilo.
- **Una sola llamada:** recuperación previa por embeddings (con el mensaje anterior del usuario como contexto, para las preguntas de seguimiento) y una llamada con salida estructurada que devuelve el tipo de respuesta, el texto, las FAQ usadas y, si aplica, el procedimiento y sus datos. El código valida, notifica y aplica el guardarraíl y el auditor.
- Las instrucciones de comportamiento y de protección viven en `agent_prompt` (incluida `area_rules`); el código solo aporta estructura (FAQ recuperadas, lista de áreas).
- Patrón strategy para la selección del agente según el canal.
- Chat web y chat en vivo del ejecutivo por WebSocket. Google Chat por un endpoint HTTP, como app de Chat basada en eventos de interacción o como complemento de Google Workspace (por decidir en el plan).
- **Verificación de Google Chat:** token Bearer firmado por `chat@system.gserviceaccount.com`, con audiencia en la URL del endpoint o en el número de proyecto.
- **Respuesta asíncrona en Google Chat:** `spaces.messages.create` con una cuenta de servicio con permiso `chat.bot`; la credencial va en `property`.
- La notificación al space del área reutiliza la cuenta de servicio de Google Chat (`spaces.messages.create`); el correo SMTP desaparece.
- **Properties nuevas previstas:** modelo, API key, días de retención de sesión web y de hilos de Google Chat, máximo de chats por ejecutivo, duración de la sesión del ejecutivo, intentos y minutos de bloqueo, credenciales de Google Chat.
- **Tablas de negocio:** áreas (con su ámbito interno o externo y su space de Google Chat), categorías, preguntas frecuentes, procedimientos (con los datos que exigen), system prompts, horario por día, festivos, canales oficiales, space general, ejecutivos y chats de la cola web (estado, ejecutivo asignado, desconexión).
- Recuperación de FAQ y de procedimientos mediante RAG.
- Con varias réplicas en Kubernetes, el cliente y el ejecutivo de un mismo chat pueden estar conectados a pods distintos, y el cierre por fin de horario o por el plazo de 1 hora necesita un disparador temporal.
- **RNF-2:** el p95 < 5000 ms hasta la respuesta completa, con RAG, es exigente; por eso se limita a una llamada de generación (RNF-10); conviene validarlo pronto con una prueba de carga.
