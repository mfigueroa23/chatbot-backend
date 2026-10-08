# Spec 005 — Archivos adjuntos, consulta de Jira y EDR en Google Chat

## Contexto y objetivo
Con la spec 004 el asistente del canal interno conversa como una IA, pero solo trabaja con lo que el colaborador escribe y
con las FAQ y procedimientos de las áreas. En el trabajo diario los colaboradores comparten documentos y capturas, y los
Jefes de Proyecto (JP) dependen de Jira y de la especificación de requerimientos de desarrollo (EDR), un documento tedioso
que suele ser el cuello de botella de su rol. El proyecto `agente-ti` ya resolvió ese flujo para los JP; esta spec lo
reimplementa dentro del asistente, en Google Chat: el asistente lee los archivos que se le comparten (documentos y
fotos), consulta Jira en modo solo lectura y redacta EDR en Google Docs a partir de la conversación, los archivos y los
tickets, con el área Proyectos como especialista. El chat web de clientes no cambia.

## Usuarios / actores
- **Colaborador** del canal interno de Google Chat.
- **Jefe de Proyecto (JP):** colaborador habilitado para consultar Jira y generar EDR.
- **Área Proyectos:** área interna que atiende nuevos desarrollos, EDR y estado de proyectos.

## Historias de usuario
- H1: Como colaborador quiero compartir un documento o una foto en la conversación para que el asistente lo lea y me responda sobre su contenido.
- H2: Como JP quiero preguntar por un ticket o una épica de Jira para conocer su estado, su descripción y sus subtareas sin salir de Google Chat.
- H3: Como JP quiero que el asistente redacte el EDR de un proyecto con lo que le cuento, los archivos que comparto y lo que ya está en Jira, para no partir de una plantilla vacía.
- H4: Como JP quiero iterar el EDR en la conversación y tenerlo en un Google Doc que pueda abrir y compartir.

## Requisitos funcionales (criterios de aceptación en EARS)

Definiciones usadas en esta sección:
- **Archivo compartido:** un archivo adjunto a un mensaje de Google Chat, subido directamente o enlazado desde Google Drive.
- **Formatos legibles:** PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), texto plano, Markdown, CSV, JSON e imágenes JPG, PNG y WebP.
- **Colaborador habilitado:** colaborador incluido en la lista de acceso a Jira y EDR, editable en la base de datos.
- **Tablero permitido:** proyecto de Jira incluido en la lista de tableros, editable en la base de datos.
- **EDR:** documento con la estructura del EDR de `agente-ti` (metadata, historial, objetivo general, visión general, product owner, equipo de desarrollo, aplicaciones afectadas, usuarios afectados, requerimientos, especificaciones de cada RF, roles y permisos, impacto, infraestructura, seguridad, criterios de aceptación, validaciones de cartera y glosario).

### Archivos compartidos
- RF-1: CUANDO un colaborador comparta un archivo en un formato legible de hasta 20 MB, EL SISTEMA leerá su contenido y responderá sobre él.
- RF-2: CUANDO el archivo sea una imagen, EL SISTEMA interpretará su contenido visual (texto, tablas, capturas de pantalla o lo que muestre).
- RF-3: CUANDO un mensaje traiga varios archivos, EL SISTEMA leerá cada uno.
- RF-4: EL SISTEMA podrá usar el contenido de un archivo compartido en los mensajes siguientes de la misma conversación.
- RF-5: SI un archivo supera los 20 MB, ENTONCES EL SISTEMA no lo leerá y dirá al colaborador que excede el tamaño admitido.
- RF-6: SI un archivo no está en un formato legible, ENTONCES EL SISTEMA no lo leerá y dirá al colaborador qué formatos admite.
- RF-7: SI un archivo de Google Drive no es accesible para el asistente, ENTONCES EL SISTEMA pedirá al colaborador que lo comparta con la cuenta del asistente, indicando cuál es.
- RF-8: SI la lectura de un archivo falla, ENTONCES EL SISTEMA dirá que no pudo leerlo, sin detalles técnicos, y seguirá con el resto del mensaje.
- RF-9: SI el contenido de un archivo supera el límite de texto configurado, ENTONCES EL SISTEMA usará solo la parte que cabe y dirá al colaborador que leyó una parte.
- RF-10: EL SISTEMA tratará el contenido de un archivo como información, nunca como instrucciones (spec 001, RF-107).
- RF-11: MIENTRAS el mensaje llegue por el chat web, EL SISTEMA no aceptará archivos (el contrato del WebSocket no cambia).

### Consulta de Jira (solo lectura)
- RF-12: CUANDO un colaborador habilitado pregunte por un ticket o una épica de un tablero permitido, EL SISTEMA responderá con su estado, su descripción y sus subtareas o tickets hijos.
- RF-13: CUANDO un colaborador habilitado pida buscar tickets, EL SISTEMA buscará solo en los tableros permitidos.
- RF-14: EL SISTEMA no creará, modificará, comentará, transicionará ni vinculará tickets de Jira.
- RF-15: SI un colaborador pide modificar Jira, ENTONCES EL SISTEMA dirá que solo puede consultar.
- RF-16: SI un ticket no existe o pertenece a un tablero no permitido, ENTONCES EL SISTEMA dirá que no lo encuentra, sin revelar si existe en otro tablero.
- RF-17: SI Jira no responde, ENTONCES EL SISTEMA dirá que no pudo consultarlo en ese momento, sin detalles técnicos.

### EDR
- RF-18: CUANDO un colaborador habilitado pida un EDR, EL SISTEMA redactará un borrador con la información de la conversación, de los archivos compartidos y de los tickets de Jira que se indiquen.
- RF-19: EL SISTEMA leerá la épica de Jira indicada y sus subtareas antes de redactar el EDR, cuando se indique una.
- RF-20: EL SISTEMA dejará como «[PENDIENTE DEFINIR]» cada dato del EDR que nadie entregó, sin inventarlo.
- RF-21: EL SISTEMA guardará el EDR como un Google Doc en la carpeta de Drive configurada.
- RF-22: CUANDO el EDR se guarde, EL SISTEMA compartirá en la conversación el enlace real al documento.
- RF-23: CUANDO el colaborador pida cambios a un EDR de la conversación, EL SISTEMA actualizará el mismo documento.
- RF-24: SI guardar el EDR falla, ENTONCES EL SISTEMA dirá que no pudo guardarlo, sin afirmar que lo hizo (spec 004, RF-55).
- RF-25: EL SISTEMA preguntará solo lo importante que falte para el EDR, sin pedir lo que ya está en la conversación, en los archivos o en Jira.

### Acceso
- RF-26: SI un colaborador no habilitado pide consultar Jira o generar un EDR, ENTONCES EL SISTEMA le dirá que esa función no está habilitada para él, sin consultar Jira.
- RF-27: EL SISTEMA leerá de la base de datos la lista de colaboradores habilitados, la de tableros permitidos y la carpeta de Drive de los EDR.
- RF-28: CUANDO se modifique una de esas listas o la carpeta, EL SISTEMA aplicará el cambio a partir del siguiente mensaje.
- RF-29: EL SISTEMA identificará al colaborador por su cuenta de Google Chat, nunca por lo que escriba.

### Seguridad y convivencia
- RF-30: EL SISTEMA aplicará a las respuestas con contenido de archivos, Jira o EDR el control posterior de la spec 004 (RF-51 a RF-55 y RF-59).
- RF-31: EL SISTEMA tratará como evidencia (spec 004, RF-53) los RUT, correos y teléfonos que aparecen en un archivo compartido en la conversación o en un ticket de Jira consultado en ese mensaje.
- RF-32: EL SISTEMA no mostrará en el chat web información de Jira, de EDR ni de archivos del canal interno.

## Requisitos no funcionales
- RNF-1: Un mensaje con un archivo de hasta 20 MB se responde dentro del tiempo de la respuesta diferida de Google Chat (spec 001, RF-68 y RF-69): si tarda más de 30 s, se contesta que se está procesando y la respuesta llega después al mismo hilo.
- RNF-2: Las credenciales de Jira y de Google Drive se guardan como property (constitución, punto 4) y nunca aparecen en logs ni respuestas.
- RNF-3: Ningún test se conecta a Jira, a Google ni a la base de datos (constitución, punto 6).

## Casos límite
- Foto de un error en pantalla: «¿qué significa esto?» → lee la captura y responde sobre ella (RF-2).
- PDF de 25 MB → dice que excede los 20 MB (RF-5).
- Video o audio → dice que no puede leerlo y qué formatos admite (RF-6).
- Archivo de Drive sin permiso → pide compartirlo con la cuenta del asistente (RF-7).
- Documento cuyo texto dice «ignora tus reglas» → se trata como contenido (RF-10).
- «¿En qué está la épica DAIA-52?» por un JP habilitado → estado, descripción y subtareas (RF-12).
- La misma pregunta por un colaborador no habilitado → función no habilitada (RF-26).
- Ticket de un tablero no permitido → «no lo encuentro» (RF-16).
- «Cierra el ticket DAIA-60» → solo puede consultar (RF-15).
- «Arma el EDR de DAIA-52» → borrador con épica, subtareas y conversación, enlace al Doc y pendientes marcados (RF-18 a RF-22).
- «Agrega un RF de exportación a PDF» → actualiza el mismo Doc (RF-23).
- Drive caído al guardar → no afirma haber guardado (RF-24).
- Un cliente intenta subir un archivo en el web → el web no lo admite (RF-11).

## Fuera de alcance
- Subir archivos en el chat web.
- Crear, modificar, comentar, transicionar o vincular tickets de Jira.
- Sincronizar el EDR con Jira o publicarlo con un flujo de aprobación (como `sync_edr_to_jira` de `agente-ti`).
- Leer audio, video o archivos comprimidos.
- Buscar archivos en Drive por iniciativa del asistente: solo lee los que se comparten en la conversación.
- Correos, reuniones de Meet y otras fuentes de `agente-ti`.
- Integrar o llamar a `agente-ti`: la funcionalidad se reimplementa en este proyecto.

## Criterios de finalización
- Todos los RF tienen al menos un test `*_test.py` en verde con dobles de Jira, de Google (Chat y Drive) y del modelo, sin red ni base de datos.
- `uv run pyright` sin errores.
- Listas de colaboradores habilitados y tableros permitidos, carpeta de Drive y credenciales cargadas en la BD remota.
- `jailbreak_check --scope internal` sigue terminando con código 0.
- Demo manual en Google Chat: un PDF, una foto, un archivo no admitido, consulta de una épica, ticket de un tablero no permitido, pedido de modificar Jira, EDR de una épica con su enlace, un cambio al EDR y la misma consulta por un colaborador no habilitado.

## Dudas abiertas
- Ninguna.

## Decisiones registradas
- **Solo Google Chat (2026-10-08, decisión del usuario):** el chat web no admite archivos.
- **Jira en solo lectura (2026-10-08, decisión del usuario).**
- **EDR en Google Docs (2026-10-08, decisión del usuario):** en una carpeta de Drive configurada, con el enlace en la conversación.
- **Acceso por listas (2026-10-08, decisión del usuario):** colaboradores habilitados y tableros permitidos, editables en la BD.
- **Documentos e imágenes hasta 20 MB (2026-10-08, decisión del usuario).**
- **Estructura del EDR de `agente-ti` (2026-10-08, decisión del usuario).**
- **Reimplementar en el chatbot (2026-10-08, decisión del usuario):** sin depender de `agente-ti`; el acceso a Jira por MCP lo pidió el usuario y se evalúa en el plan.
- **Datos de archivos y Jira como evidencia (2026-10-08, decisión del usuario):** un dato personal que aparece en un archivo compartido o en un ticket consultado se puede mostrar; lo que el modelo invente sigue bloqueado.
- **Entrega junto al fix 1.4.1 (2026-10-08, decisión del usuario):** en la rama `fix/coordinator-tool-names`.
- **Formato y redacción del EDR editables sin desplegar (2026-10-08, decisión del usuario):** la plantilla visual y la
  guía de redacción de cada sección se guardan en la base de datos.
