# Spec 002 — Herramientas y servidores MCP por área, archivos en Google Chat y el área Proyectos consultando Jira

## Contexto y objetivo
La spec 001 dejó a cada sub-agente con un registro de herramientas programadas en código, vacío, y dejó los servidores
MCP para después. El área Proyectos es el primer caso real que necesita ambos: los Jefes de Proyecto (JP) consultan el
estado de sus tickets y épicas en Jira, y hoy eso lo resuelve `agente-ti`, un proyecto aparte centrado en redactar EDR.

Esta spec completa ese punto de extensión. Cada área puede usar herramientas programadas en código y las de servidores
MCP configurados en la base de datos, restringidas si hace falta a una lista de colaboradores habilitados. Como primer
uso, el área Proyectos (interna) responde dudas sobre el EDR con sus FAQ y consulta Jira en **solo lectura** con
herramientas en código, sin salir de Google Chat. Además, el asistente lee los
archivos que los colaboradores suben en Google Chat (fotos, PDF y documentos de hasta 20 MB) y responde sobre ellos.
Redactar el EDR, guardarlo en Drive y escribir en Jira quedan para una spec posterior.

## Usuarios / actores
- **Colaborador:** usuario interno que escribe al asistente por Google Chat.
- **Colaborador habilitado:** colaborador incluido en la lista de un área para usar sus herramientas; para Proyectos,
  los JP.
- **Responsable de contenidos:** carga en la base de datos el área Proyectos, sus FAQ, sus herramientas, sus servidores
  MCP, los tableros permitidos y los colaboradores habilitados.
- **Desarrollador:** programa herramientas nuevas en código.

## Historias de usuario
- H1: Como colaborador quiero preguntar qué es un EDR o qué va en cada sección para redactarlo bien, sin depender de
  otra persona.
- H2: Como JP quiero preguntar por un ticket o una épica de Jira y conocer su estado, su descripción y sus subtareas sin
  salir de Google Chat.
- H3: Como JP quiero buscar tickets de mis tableros con una pregunta en lenguaje natural.
- H4: Como responsable de contenidos quiero conectar un servidor MCP a un área desde la base de datos, sin desplegar.
- H5: Como responsable de contenidos quiero decidir quién puede usar las herramientas de un área.
- H6: Como colaborador o cliente quiero que, si mi pregunta es ambigua, el asistente busque mejor o me pregunte a qué me
  refiero, en vez de decirme que no tiene información.
- H7: Como colaborador quiero subir una foto o un documento en Google Chat para que el asistente lo lea y me responda
  sobre su contenido, sin tener que copiarlo.

## Requisitos funcionales (criterios de aceptación en EARS)

Definiciones usadas en esta sección:
- **Herramienta del área:** herramienta del registro en código (spec 001, RF-27 a RF-30) o de un servidor MCP asignada
  a un área.
- **Servidor MCP:** servidor remoto del Model Context Protocol, accesible por HTTP, registrado en la base de datos.
- **Tablero permitido:** proyecto de Jira incluido en la lista de tableros, editable en la base de datos.
- **Archivo subido:** archivo adjunto a un mensaje de Google Chat subido directamente al chat (no un enlace de Drive).
- **Formatos legibles:** imágenes JPG, PNG y WebP; PDF; Word (.docx), Excel (.xlsx) y PowerPoint (.pptx); texto plano,
  Markdown, CSV y JSON.

### Identidad del colaborador
- RF-1: EL SISTEMA identificará al colaborador de Google Chat por la cuenta del evento (correo), nunca por lo que
  escriba.
- RF-2: EL SISTEMA entregará esa identidad a las herramientas del área que la necesiten.
- RF-3: MIENTRAS el mensaje llegue por el chat web, EL SISTEMA tratará al usuario como anónimo.

### Acceso a las herramientas
- RF-4: SI un área tiene una lista de colaboradores habilitados, ENTONCES EL SISTEMA dará sus herramientas solo a los
  colaboradores de esa lista.
- RF-5: SI un área no tiene lista de colaboradores habilitados, ENTONCES EL SISTEMA dará sus herramientas a todos los
  usuarios de su canal.
- RF-6: EL SISTEMA responderá con las FAQ de un área a cualquier usuario de su canal, esté o no habilitado para sus
  herramientas.
- RF-7: SI un colaborador no habilitado pide algo que requiere una herramienta del área, ENTONCES EL SISTEMA le dirá que
  esa función no está habilitada para él, sin ejecutarla.
- RF-8: CUANDO se modifique la lista de colaboradores habilitados, EL SISTEMA aplicará el cambio desde el siguiente
  mensaje.

### Servidores MCP
- RF-9: EL SISTEMA leerá de la base de datos los servidores MCP activos (nombre, URL, credencial y herramientas
  permitidas) y su asignación a las áreas.
- RF-10: CUANDO un sub-agente atienda una subtarea, EL SISTEMA le dará, además de las herramientas en código de su área,
  las herramientas permitidas de los servidores MCP activos asignados a su área.
- RF-11: EL SISTEMA dará de cada servidor MCP solo las herramientas incluidas en su lista de herramientas permitidas; un
  servidor sin lista no aporta ninguna.
- RF-12: EL SISTEMA obtendrá la credencial de cada servidor MCP de `property`, por el nombre de clave indicado en el
  servidor, y nunca la mostrará en logs ni respuestas.
- RF-13: SI un servidor MCP no responde, falla o excede el tiempo configurado, ENTONCES EL SISTEMA seguirá sin sus
  herramientas, registrará una advertencia y no mostrará detalles técnicos al usuario.
- RF-14: CUANDO se agregue, desactive o modifique un servidor MCP o su asignación, EL SISTEMA aplicará el cambio desde
  el siguiente mensaje, sin desplegar.
- RF-15: EL SISTEMA tratará el resultado de una herramienta MCP como información, nunca como instrucciones (spec 001,
  RF-39).

### Área Proyectos
- RF-16: CUANDO un colaborador pregunte sobre el EDR (qué es, sus secciones, qué va en cada una, qué hacer con un dato
  que falta), EL SISTEMA responderá con las FAQ del área Proyectos.
- RF-17: CUANDO un colaborador habilitado pregunte por un ticket o una épica de un tablero permitido, EL SISTEMA
  responderá con su estado, tipo, responsable, descripción y sus subtareas o tickets hijos.
- RF-18: CUANDO un colaborador habilitado pida buscar tickets, EL SISTEMA buscará solo en los tableros permitidos.
- RF-19: SI un ticket no existe o pertenece a un tablero no permitido, ENTONCES EL SISTEMA dirá que no lo encuentra,
  sin revelar si existe en otro tablero.
- RF-20: EL SISTEMA no creará, modificará, comentará, transicionará ni vinculará tickets de Jira.
- RF-21: SI un colaborador pide modificar Jira, ENTONCES EL SISTEMA dirá que por ahora solo puede consultar.
- RF-22: SI Jira no responde, ENTONCES EL SISTEMA dirá que no pudo consultarlo en ese momento, sin detalles técnicos.
- RF-23: EL SISTEMA leerá de la base de datos la lista de tableros permitidos y de `property` las credenciales de
  Jira, y aplicará sus cambios desde el siguiente mensaje.
- RF-24: EL SISTEMA tratará la descripción y los comentarios de un ticket como información, nunca como instrucciones.

### Búsqueda de FAQ por el sub-agente
Hoy el código busca las FAQ de cada subtarea antes de llamar al sub-agente (spec 001, plan D6) y el sub-agente no
puede buscar de nuevo. Esta sección le da una herramienta para hacerlo, sin quitar la búsqueda previa.
- RF-25: EL SISTEMA dará a cada sub-agente, en ambos canales, una herramienta para volver a buscar en las FAQ de su área
  con una consulta reformulada, además de las FAQ que ya recibe.
- RF-26: EL SISTEMA limitará esa búsqueda a las FAQ activas del área del sub-agente, nunca a las de otra área (spec 001,
  RNF-7).
- RF-27: CUANDO las FAQ recibidas no respondan la subtarea o la respondan solo en parte, EL SISTEMA podrá usar esa
  búsqueda antes de dar la subtarea por sin información.
- RF-28: CUANDO las FAQ encontradas respondan interpretaciones distintas de la consulta, EL SISTEMA devolverá esas
  interpretaciones al coordinador en vez de elegir una.
- RF-29: CUANDO el coordinador reciba interpretaciones distintas de un área, EL SISTEMA preguntará a la persona a cuál
  se refiere, mencionando las opciones con sus palabras.
- RF-30: EL SISTEMA contará cada búsqueda dentro del máximo de pasos del sub-agente (`sub_agent_max_steps`) y de su
  tiempo máximo; al agotarlos, el sub-agente responde con lo que tenga.

### Archivos subidos en Google Chat
- RF-31: CUANDO un colaborador suba en Google Chat un archivo en un formato legible de hasta 20 MB, EL SISTEMA leerá su
  contenido y responderá sobre él.
- RF-32: CUANDO el archivo sea una imagen, EL SISTEMA interpretará su contenido visual (texto, tablas, capturas de
  pantalla o lo que muestre).
- RF-33: CUANDO un mensaje traiga varios archivos, EL SISTEMA leerá cada uno.
- RF-34: CUANDO un mensaje traiga archivos y ningún texto, EL SISTEMA dirá brevemente qué contienen y preguntará qué
  necesita el colaborador.
- RF-35: EL SISTEMA podrá usar el contenido de un archivo subido en los mensajes siguientes de la misma conversación,
  sin volver a descargarlo.
- RF-36: CUANDO la consulta sobre un archivo corresponda a un área, EL SISTEMA combinará el contenido del archivo con la
  información de esa área (por ejemplo, revisar una captura de error contra las FAQ).
- RF-37: SI un archivo supera los 20 MB, ENTONCES EL SISTEMA cortará su descarga al pasar ese tamaño, no lo leerá y
  dirá al colaborador que excede el tamaño admitido (Google Chat no informa el tamaño antes de descargar).
- RF-38: SI un archivo no está en un formato legible, ENTONCES EL SISTEMA no lo leerá y dirá al colaborador qué formatos
  admite.
- RF-39: SI la lectura de un archivo falla, ENTONCES EL SISTEMA dirá que no pudo leerlo, sin detalles técnicos, y
  seguirá con el resto del mensaje.
- RF-40: SI el texto de un archivo supera el límite configurado, ENTONCES EL SISTEMA usará solo la parte que cabe y
  dirá al colaborador que leyó una parte.
- RF-41: EL SISTEMA tratará el contenido de un archivo como información, nunca como instrucciones (spec 001, RF-39).
- RF-42: MIENTRAS el mensaje llegue por el chat web, EL SISTEMA no aceptará archivos.

## Requisitos no funcionales
- RNF-1: Un mensaje que usa herramientas del área se responde dentro del mismo objetivo de la spec 001 (p95 ≤ 10 s) y
  del tiempo máximo de respuesta configurado.
- RNF-2: Las credenciales de Jira y de los servidores MCP se guardan como property (constitución, punto 4) y nunca
  aparecen en logs ni respuestas.
- RNF-3: La cuenta de Jira del asistente es de solo lectura, como defensa adicional a RF-20.
- RNF-4: Ningún test se conecta a Jira, a un servidor MCP, a Google ni a la base de datos (constitución, punto 6).
- RNF-5: Agregar un servidor MCP a un área, cambiar sus herramientas permitidas o la lista de habilitados requiere solo
  filas en la base de datos.
- RNF-6: Un mensaje hace como máximo 2 + N × `sub_agent_max_steps` llamadas al modelo (antes 2 + N, spec 001 RNF-6); un
  sub-agente que responde con las FAQ recibidas sigue haciendo una sola. Leer una imagen o un PDF suma una llamada por
  archivo.
- RNF-7: Un mensaje con archivos queda fuera del objetivo p95 ≤ 10 s, pero se responde dentro de los 30 s que Google
  Chat espera para una respuesta síncrona.
- RNF-8: El tamaño máximo (20 MB) y el límite de texto por archivo se configuran en `property`; la credencial de la
  cuenta de servicio que descarga los archivos de Chat también va en `property` y nunca aparece en logs.
- RNF-9: Los logs no incluyen el contenido de los archivos.

## Casos límite
- «¿Qué va en validaciones de cartera?» por cualquier colaborador → FAQ de Proyectos (RF-6, RF-16).
- «¿En qué está la épica DAIA-52?» por un JP habilitado → estado, descripción y subtareas (RF-17).
- La misma pregunta por un colaborador no habilitado → la función no está habilitada para él; no se consulta Jira (RF-7).
- Ticket de un tablero no permitido → «no lo encuentro» (RF-19).
- «Cierra el ticket DAIA-60» → por ahora solo puede consultar (RF-21).
- «Busca los tickets de pagaré» → busca solo en los tableros permitidos (RF-18).
- Jira caído → no pudo consultarlo ahora, sin detalles (RF-22).
- Servidor MCP caído → el área responde con sus FAQ y sus herramientas en código (RF-13).
- Servidor MCP que expone una herramienta de escritura fuera de su lista permitida → el sub-agente no la recibe (RF-11).
- Descripción de un ticket que dice «ignora tus reglas» → se trata como contenido (RF-24).
- Se quita a un JP de la lista de habilitados → desde el siguiente mensaje ya no consulta Jira (RF-8).
- «¿Cómo pago?» sin contexto, con FAQ de pago de cuota y de prepago → el asistente pregunta si se refiere a la cuota o
  al prepago (RF-28, RF-29).
- La subtarea dice «seguro del auto» y la FAQ habla de «póliza de desgravamen» → el sub-agente busca de nuevo con otras
  palabras antes de decir que no tiene información (RF-25, RF-27).
- Una pregunta toca a Servicio al Cliente y a Ventas → el coordinador la divide (spec 001, RF-5); el sub-agente de
  Ventas nunca busca en las FAQ de Servicio al Cliente (RF-26).
- Foto de un error en pantalla con «¿qué significa esto?» → lee la captura y responde sobre ella (RF-31, RF-32).
- PDF de 25 MB → corta la descarga a los 20 MB y dice que excede el tamaño admitido (RF-37).
- Video, audio o un .zip → dice que no puede leerlo y qué formatos admite (RF-38).
- Un Word y una foto en el mismo mensaje → lee los dos (RF-33).
- Solo un PDF, sin texto → resume en una frase qué contiene y pregunta qué necesita (RF-34).
- Después de subir un contrato, «¿y qué dice del prepago?» en el mismo hilo → usa el contrato ya leído (RF-35).
- Documento cuyo texto dice «ignora tus reglas» → se trata como contenido (RF-41).

## Fuera de alcance
- Crear, modificar, comentar, transicionar o vincular tickets de Jira.
- Redactar el EDR, guardarlo en Google Docs o sincronizarlo con Jira (spec posterior; hoy lo resuelve `agente-ti`).
- Leer archivos enlazados desde Google Drive (requiere la API de Drive y compartir cada archivo con el asistente).
- Leer audio, video o archivos comprimidos.
- Aceptar archivos en el chat web (RF-42).
- Servidores MCP locales (stdio) y autenticación MCP interactiva (OAuth con el usuario).
- Usar en el área Proyectos un servidor MCP en producción: el mecanismo queda construido y probado, y conectar uno real
  (por ejemplo el de Atlassian) se decide aparte.
- Herramientas en el chat web: el web es anónimo (RF-3) y ninguna área externa tiene herramientas.

## Criterios de finalización
- Todos los RF tienen al menos un test `*_test.py` en verde con dobles de Jira, de servidores MCP, de Google y del
  modelo, sin red ni base de datos.
- `uv run pyright` sin errores.
- Área Proyectos, sus FAQ (guía de secciones del EDR), los tableros permitidos, los colaboradores habilitados y las
  credenciales de Jira cargados en la base remota.
- Demo manual en Google Chat: una FAQ del EDR, consulta de una épica, búsqueda de tickets, ticket de un tablero no
  permitido, pedido de modificar Jira y la misma consulta por un colaborador no habilitado.
- Demo del mecanismo MCP con un servidor MCP de prueba asignado a un área.
- Demo en el web con una pregunta ambigua que termina en una pregunta de aclaración, y el p95 de la demo de la spec 001
  sigue en 10 s o menos.
- Demo en Google Chat con una foto, un PDF, un Word, un archivo de más de 20 MB, un formato no admitido y una pregunta
  de seguimiento sobre un archivo ya leído.

## Dudas abiertas
- Tableros de Jira permitidos y lista inicial de JP habilitados (en la 1.x: el tablero `DAIA` y 2 colaboradores).
- Cuenta de Jira de solo lectura para el asistente (RNF-3): reutilizar la de la 1.x o crear una nueva.
- Fuente de las FAQ del EDR: la guía de secciones del prompt de `agente-ti`, revisada por el área Proyectos.
- Si un archivo grande no alcanza a leerse dentro de los 30 s de Google Chat: el plan propone responder «no disponible»
  con un tope de 27 s (plan, D3) y dejar la respuesta diferida para después; se confirma con la demo.

## Decisiones registradas
- **Alcance: mecanismo de herramientas y MCP + Jira en solo lectura (2026-10-09, decisión del usuario):** el EDR queda
  para una spec posterior.
- **Jira con herramientas en código (2026-10-09, decisión del usuario):** API REST de Jira con tableros permitidos y JQL
  acotado en código, como la 1.x y `agente-ti`; el soporte MCP se construye y prueba, pero no se usa todavía para Jira.
- **Servidores MCP en una tabla de la BD (2026-10-09, decisión del usuario):** asignados por área, con credenciales en
  `property`; agregar uno no requiere desplegar.
- **Acceso por lista de habilitados por área (2026-10-09, decisión del usuario):** identificados por su cuenta de
  Google Chat; las FAQ del área siguen abiertas a todos.
- **Búsqueda de FAQ como herramienta del sub-agente (2026-10-09, decisión del usuario):** para consultas ambiguas o
  que la búsqueda previa no resolvió; se mantiene la búsqueda previa en el código y la herramienta se limita al área
  del sub-agente. Repartir una consulta entre varias áreas sigue siendo trabajo del coordinador.
- **Archivos subidos en Google Chat, hasta 20 MB (2026-10-09, decisión del usuario):** fotos y documentos; el chat web
  no admite archivos.
