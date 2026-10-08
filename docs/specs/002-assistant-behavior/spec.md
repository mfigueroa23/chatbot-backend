# Spec 002 — Comportamiento de asistente

## Contexto y objetivo
La spec 001 (versión 1.1.0) solo responde cuando una FAQ o un procedimiento supera el umbral de similitud; cualquier
otro mensaje sigue el flujo de "sin respuesta" del canal. En el despliegue, «hola», «gracias», «tengo un problema con mi
pago» y «necesito ayuda» terminan mostrando los canales oficiales al cliente o avisando al área en el canal interno, como
si fueran consultas sin respuesta. Esta spec hace que el asistente se comporte como tal en ambos canales: saluda, cierra
la conversación, infiere lo que se le pide con una pregunta de aclaración cuando el pedido es ambiguo y declina lo que es
ajeno a sus áreas, sin derivar a una persona por mensajes que no lo requieren. Las respuestas con información siguen
apoyándose solo en las FAQ y los procedimientos (spec 001). Además, el asistente vuelve a organizarse como un agente
coordinador por canal que resuelve o delega en un agente especializado por área (constitución, punto 3), en lugar de la
llamada única de la spec 001.

Esta spec no es la «spec 002 — agentes con tools» que cita la spec 001: aquella se eliminó y su contenido se absorbió en
la spec 001.

## Usuarios / actores
- **Cliente** del canal web (áreas externas).
- **Colaborador** del canal interno de Google Chat (áreas internas).
- **Área** que recibe los avisos de consultas sin respuesta del canal interno (spec 001).

## Historias de usuario
- H1: Como cliente quiero que el asistente responda a mi saludo diciéndome en qué puede ayudarme para saber qué preguntarle.
- H2: Como colaborador quiero que el asistente me pregunte qué necesito cuando mi mensaje es vago para no tener que adivinar cómo formularlo.
- H3: Como cliente quiero que el asistente me proponga los temas que se parecen a lo que escribí para elegir el correcto con una respuesta corta.
- H4: Como área quiero recibir avisos solo de consultas reales sin respuesta para no atender saludos, agradecimientos ni pedidos ajenos.

## Requisitos funcionales (criterios de aceptación en EARS)

Definiciones usadas en esta sección:
- **Umbral de respuesta:** el umbral de similitud de la spec 001, el mismo para FAQ y procedimientos; solo lo que lo supera puede usarse para responder.
- **Umbral de aclaración:** umbral de similitud configurable, menor que el umbral de respuesta.
- **Candidato:** FAQ o procedimiento activo, de un área activa del ámbito del canal, cuya similitud con el mensaje es menor que el umbral de respuesta y mayor o igual que el umbral de aclaración.
- **Saludo:** mensaje formado solo por un saludo («hola», «buenas tardes», «hola, ¿cómo estás?», «👋»).
- **Cierre:** mensaje formado solo por un agradecimiento, una despedida o una confirmación sin contenido («gracias», «chao», «ok», «👍»), solos o acompañados de un saludo.
- **Ajeno:** mensaje que no corresponde a ninguna de las áreas del canal.
- **Mensaje sin respuesta:** mensaje que no es un saludo, un cierre ni ajeno, y para el que ninguna FAQ ni procedimiento supera el umbral de respuesta.
- **Mensaje fijo:** el mensaje de saludo, de cierre o de fuera de tema de un canal.
- **Aclaración:** pregunta con opciones (RF-10) o pregunta de áreas (RF-16).
- **Aclaración pendiente:** la última aclaración enviada a un usuario, mientras ese usuario no haya enviado otro mensaje que reciba respuesta.
- **Oferta de ejecutivo pendiente:** la oferta de hablar con un ejecutivo (RF-25 de la spec 001) mientras el cliente no la haya respondido.
- **Agente del canal:** el agente coordinador de cada canal (interno o externo), con su propio prompt.
- **Agente de área:** el agente especializado de un área activa, con su propio prompt y sus propias acciones.

### Mensajes fijos
- RF-1: EL SISTEMA leerá de la base de datos el texto de cada mensaje fijo de cada canal.
- RF-2: CUANDO se modifique el texto de un mensaje fijo en la base de datos, EL SISTEMA aplicará el cambio a partir del siguiente mensaje recibido.
- RF-3: SI falta en la base de datos el texto de un mensaje fijo de un canal, ENTONCES EL SISTEMA registrará un error en el log.
- RF-4: SI falta en la base de datos el texto del mensaje fijo que correspondería enviar, ENTONCES EL SISTEMA tratará el mensaje del usuario según los niveles 7 a 11 de RF-39.

### Saludos y cierres
- RF-5: CUANDO el mensaje del usuario sea un saludo, EL SISTEMA responderá con el mensaje de saludo del canal.
- RF-6: EL SISTEMA incluirá en el mensaje de saludo los nombres de todas las áreas activas del canal.
- RF-7: CUANDO el mensaje del usuario sea un cierre, EL SISTEMA responderá con el mensaje de cierre del canal.
- RF-8: CUANDO un mensaje combine un saludo o un cierre con una consulta, EL SISTEMA responderá a la consulta según el resto de requisitos.
- RF-9: CUANDO el sistema responda con el mensaje de saludo o de cierre, EL SISTEMA no aplicará el flujo de "sin respuesta" del canal.

### Aclaración de pedidos ambiguos
- RF-10: CUANDO llegue un mensaje sin respuesta y exista al menos un candidato, EL SISTEMA preguntará al usuario a cuál de los candidatos se refiere.
- RF-11: EL SISTEMA ofrecerá como opciones de una pregunta con opciones como máximo los 3 candidatos de mayor similitud, con las FAQ y los procedimientos en un mismo orden.
- RF-12: SI dos candidatos tienen la misma similitud, ENTONCES EL SISTEMA los ordenará alfabéticamente por su texto.
- RF-13: SI dos candidatos tienen el mismo texto, ENTONCES EL SISTEMA ofrecerá solo el de mayor similitud.
- RF-14: EL SISTEMA nombrará cada opción por la pregunta de la FAQ o el nombre del procedimiento, sin incluir su respuesta ni sus pasos.
- RF-15: EL SISTEMA numerará las opciones de una pregunta con opciones.
- RF-16: CUANDO llegue un mensaje sin respuesta y no exista ningún candidato, EL SISTEMA preguntará al usuario con qué necesita ayuda nombrando las áreas activas del canal.
- RF-17: MIENTRAS haya una pregunta con opciones pendiente, EL SISTEMA no hará otra aclaración.
- RF-18: MIENTRAS haya una pregunta de áreas pendiente, EL SISTEMA no hará otra pregunta de áreas.
- RF-19: SI hay una aclaración pendiente y el siguiente mensaje sin respuesta no puede recibir otra aclaración (RF-17 y RF-18), ENTONCES EL SISTEMA aplicará el flujo de "sin respuesta" del canal.
- RF-20: EL SISTEMA leerá el umbral de aclaración de la configuración en `property`, con el valor por defecto que fije el plan.
- RF-21: SI el umbral de aclaración falta, no es un número válido o es mayor o igual que el umbral de respuesta, ENTONCES EL SISTEMA no considerará ningún candidato.
- RF-22: CUANDO el sistema no considere candidatos por RF-21, EL SISTEMA registrará un aviso en el log.

### Elección de opciones
- RF-23: EL SISTEMA aceptará como elección de una opción su número, su ordinal, su texto completo o parcial, o una paráfrasis de su texto.
- RF-24: EL SISTEMA solo aceptará una elección del mismo usuario que recibió la pregunta con opciones.
- RF-25: CUANDO el usuario elija una FAQ de la pregunta con opciones pendiente, EL SISTEMA responderá con esa FAQ aunque esté por debajo del umbral de respuesta.
- RF-26: CUANDO el usuario elija un procedimiento de la pregunta con opciones pendiente, EL SISTEMA iniciará ese procedimiento aunque esté por debajo del umbral de respuesta.
- RF-27: CUANDO el usuario elija varias FAQ, EL SISTEMA responderá a todas en una sola respuesta.
- RF-28: CUANDO el usuario elija varios procedimientos, EL SISTEMA iniciará solo el primero que mencione.
- RF-29: CUANDO el sistema inicie solo uno de los procedimientos elegidos, EL SISTEMA mencionará en la respuesta los demás para que el usuario los pida después.
- RF-30: CUANDO un mensaje combine un saludo o un cierre con una elección, EL SISTEMA atenderá la elección.
- RF-31: CUANDO un mensaje combine una elección con otra consulta, EL SISTEMA atenderá solo la elección.
- RF-32: SI el usuario responde a la pregunta con opciones pendiente con un número que no corresponde a ninguna opción, ENTONCES EL SISTEMA aplicará el flujo de "sin respuesta" del canal.
- RF-33: SI el usuario responde a la pregunta con opciones pendiente que no le sirve ninguna opción, ENTONCES EL SISTEMA aplicará el flujo de "sin respuesta" del canal.
- RF-34: EL SISTEMA no usará el contenido de un candidato para responder salvo en los casos de RF-25 a RF-29.

### Pedidos ajenos a las áreas
- RF-35: CUANDO el mensaje del usuario sea ajeno, EL SISTEMA responderá con el mensaje de fuera de tema del canal.
- RF-36: SI el mensaje solo corresponde a áreas del otro canal, ENTONCES EL SISTEMA lo tratará como ajeno, aunque tenga candidatos del propio canal.
- RF-37: EL SISTEMA incluirá en el mensaje de fuera de tema los nombres de todas las áreas activas del canal.
- RF-38: CUANDO el sistema responda con el mensaje de fuera de tema, EL SISTEMA no aplicará el flujo de "sin respuesta" del canal.

### Prioridad y convivencia con la spec 001
- RF-39: CUANDO un mensaje cumpla las condiciones de varios requisitos, EL SISTEMA aplicará solo el de mayor prioridad según este orden:
  1. Fallo o tiempo de espera del proveedor del modelo: mensaje de servicio no disponible (RF-18 de la spec 001).
  2. Intento de manipulación: respuesta de RF-108 de la spec 001.
  3. Petición explícita de hablar con una persona: flujo de RF-26 de la spec 001.
  4. Respuesta a una oferta de ejecutivo pendiente (RF-41 y RF-42).
  5. Mensaje mixto entre ámbitos: RF-8 de la spec 001.
  6. Saludo, cierre o ajeno: su mensaje fijo (RF-5, RF-7 y RF-35).
  7. Procedimiento en curso o petición de datos para un ejecutivo: flujo de la spec 001.
  8. Elección de una opción de la pregunta con opciones pendiente (RF-25 a RF-31).
  9. FAQ o procedimiento sobre el umbral de respuesta: flujo de la spec 001.
  10. Aclaración (RF-10 y RF-16), si RF-17 y RF-18 la permiten.
  11. Flujo de "sin respuesta" del canal.
- RF-40: CUANDO el sistema responda a un usuario con algo distinto de una aclaración, EL SISTEMA descartará la aclaración pendiente de ese usuario.
- RF-41: MIENTRAS haya una oferta de ejecutivo pendiente, EL SISTEMA tratará una confirmación («ok», «sí», «👍») como la aceptación de la oferta (RF-27 de la spec 001).
- RF-42: MIENTRAS haya una oferta de ejecutivo pendiente, EL SISTEMA tratará una negativa («no», «no, gracias») como el rechazo de la oferta (RF-33 de la spec 001).
- RF-43: MIENTRAS haya un procedimiento en curso o una petición de datos para un ejecutivo, CUANDO el sistema responda con un mensaje fijo, EL SISTEMA mantendrá pendiente ese flujo sin contar un intento.
- RF-44: MIENTRAS un chat web esté en la cola de espera o asignado a un ejecutivo, EL SISTEMA no aplicará los requisitos de esta spec.
- RF-45: CUANDO el sistema responda a una opción elegida (RF-25 a RF-29), EL SISTEMA no descartará la respuesta por estar la FAQ o el procedimiento por debajo del umbral de respuesta (excepción a RF-89 de la spec 001).
- RF-46: Además de los mensajes de la spec 001 que no dependen de una FAQ ni de un procedimiento, EL SISTEMA solo enviará sin ese apoyo los mensajes fijos y las aclaraciones (excepción a RF-9 y RF-89 de la spec 001).
- RF-47: EL SISTEMA aplicará a las aclaraciones el auditor de RF-109 de la spec 001.
- RF-48: EL SISTEMA guardará los mensajes fijos y las aclaraciones en la memoria de la conversación.
- RF-49: CUANDO el mensaje del usuario esté en otro idioma, EL SISTEMA aplicará los mismos requisitos y responderá en español.

### Arquitectura de agentes (constitución, punto 3)
- RF-50: CUANDO llegue un mensaje, EL SISTEMA lo procesará primero con el agente del canal.
- RF-51: EL SISTEMA hará que el agente del canal resuelva por sí mismo los niveles 1 a 6 de RF-39.
- RF-52: CUANDO el mensaje no se resuelva en los niveles 1 a 6 de RF-39, EL SISTEMA hará que el agente del canal lo delegue en los agentes de las áreas a las que corresponde.
- RF-53: MIENTRAS haya un procedimiento en curso, EL SISTEMA delegará el mensaje en el agente del área de ese procedimiento.
- RF-54: CUANDO el usuario elija una opción, EL SISTEMA delegará el mensaje en el agente del área de cada opción elegida.
- RF-55: EL SISTEMA atenderá cada área activa del canal con su propio agente de área, en ambos canales.
- RF-56: EL SISTEMA dará a cada agente de área acceso solo a las FAQ, los procedimientos y las acciones de su área.
- RF-57: EL SISTEMA no entregará a un agente de área el prompt ni el contenido de otra área.
- RF-58: CUANDO el agente del canal delegue en varias áreas, EL SISTEMA consultará sus agentes de área en paralelo.
- RF-59: CUANDO respondan varios agentes de área, EL SISTEMA combinará sus respuestas en una sola respuesta (RF-6 y RF-7 de la spec 001).
- RF-60: SI ningún agente de área consultado responde, ENTONCES EL SISTEMA aplicará los niveles 10 y 11 de RF-39.

### Oferta de ejecutivo
- RF-61: MIENTRAS haya una oferta de ejecutivo pendiente, CUANDO el sistema responda con un mensaje fijo, EL SISTEMA mantendrá pendiente la oferta.

## Requisitos no funcionales
- RNF-1: Por cada mensaje del usuario, EL SISTEMA hará como máximo 1 llamada de generación del agente del canal y 4 por cada agente de área consultado; las búsquedas por embeddings no cuentan. Sustituye a RNF-10 de la spec 001.
- RNF-2: El p95 del tiempo hasta la respuesta completa se mide con la prueba de 50 sesiones de la spec 001 en el despliegue de prueba. El objetivo es el de RNF-2 de la spec 001 (5000 ms); si no se cumple, el usuario fija el nuevo umbral con esa medición antes de fusionar, y se actualizan esta spec y la spec 001.
- RNF-3: Las aclaraciones y los mensajes fijos están en español.
- RNF-4: En el canal web, ninguna aclaración ni mensaje fijo nombra áreas, FAQ ni procedimientos del ámbito interno (spec 001, RNF-3).
- RNF-5: El sistema clasifica correctamente el 100 % de la batería de clasificación y el 100 % de la batería de elección de los criterios de finalización.

## Casos límite
- Saludo repetido en la misma conversación: se responde de nuevo con el mensaje de saludo.
- Saludo, cierre o mensaje ajeno justo después de una aclaración: se responde con su mensaje fijo, la aclaración se descarta (RF-40) y el siguiente mensaje sin respuesta puede aclararse de nuevo.
- El usuario responde a una aclaración con una consulta distinta que sí supera el umbral: se responde esa consulta y la aclaración se descarta.
- Tras la pregunta de áreas, el usuario responde «pagos» y hay candidatos: recibe una pregunta con opciones. Si no hay candidatos, se aplica el flujo de "sin respuesta" (RF-18 y RF-19).
- Tras una pregunta con opciones, el siguiente mensaje sin respuesta no recibe otra aclaración: se aplica el flujo de "sin respuesta" (RF-17 y RF-19).
- El usuario elige una opción que dejó de estar activa, o cuya área dejó de estar activa, entre la aclaración y su respuesta: se aplica el flujo de "sin respuesta".
- El usuario escribe «2» sin una pregunta con opciones pendiente: se trata como un mensaje nuevo.
- «La 1, y también ¿cómo cambio mi correo?»: se atiende la opción 1 y el usuario repite la otra consulta en un mensaje nuevo (RF-31).
- En un space de grupo, otra persona del hilo responde «la 2» a la aclaración de un colaborador: no cuenta como elección (RF-24), se trata como un mensaje nuevo de esa persona y la aclaración del colaborador sigue pendiente.
- Ninguna área activa en el canal: el saludo, la pregunta de áreas y el fuera de tema se envían sin la lista de áreas.
- Un candidato es un procedimiento y el usuario lo elige: el procedimiento empieza como en la spec 001, con sus intentos.
- «Hola», «gracias» o un mensaje ajeno durante un procedimiento o mientras se piden los datos para un ejecutivo: mensaje fijo y el flujo sigue pendiente sin gastar un intento (RF-43).
- «Ok» justo después de la oferta de ejecutivo: acepta la oferta, no es un cierre (RF-41).
- Mensaje formado solo por signos («?», «...») o por un emoji que no es saludo ni cierre: es un mensaje sin respuesta.
- El ciclo «mensaje sin respuesta → aclaración → saludo» puede repetirse sin límite.
- Fuera de horario en el canal web: tras la aclaración sin éxito, el flujo de "sin respuesta" es el de fuera de horario (canales oficiales).
- En Google Chat, la aclaración tarda más de 30 s (RF-68 de la spec 001): la elección se refiere a la última aclaración enviada.
- La sesión web o el hilo de Google Chat caducan con una aclaración pendiente: la aclaración se pierde con el resto del contexto.
- Mención al bot sin texto en un space de grupo: se aplica RF-15 de la spec 001 (pedir la consulta).

## Fuera de alcance
- Responder con candidatos por debajo del umbral sin que el usuario los elija.
- Conversación libre con el modelo (charla, opiniones o respuestas sin FAQ ni procedimiento), salvo los mensajes de esta spec.
- Pantalla o endpoint para editar los textos de los mensajes fijos: se editan en la base de datos.
- Botones, tarjetas o respuestas rápidas en la interfaz para elegir las opciones de una aclaración: se elige escribiendo.
- Más de una pregunta con opciones seguida y aclaraciones dentro de un procedimiento en curso.
- Recordar la otra consulta de un mensaje que combina una elección con otra consulta (RF-31).
- Clasificar saludos, cierres o mensajes ajenos sin el modelo (listas cerradas de expresiones).
- Cambiar el comportamiento de la cola de espera y del chat en vivo (RF-44).
- Cambiar el flujo de "sin respuesta" de cada canal definido en la spec 001.
- Cambiar el saludo que se envía al añadir el bot a un space o a un mensaje directo (RF-67 de la spec 001).
- Integraciones MCP o APIs de sistemas externos en los agentes: las acciones de un agente de área son solo las de la spec 001 (buscar FAQ y procedimientos y notificar al área).

## Criterios de finalización
- Todos los RF tienen al menos un test `*_test.py` en verde, con dobles del modelo y del recuperador, sin base de datos ni red.
- `uv run pyright` sin errores.
- Batería de clasificación contra el despliegue, en ambos canales salvo que se indique, con el 100 % de aciertos (RNF-5):

  | Mensaje | Clase esperada |
  |---|---|
  | «hola» | saludo |
  | «buenas tardes» | saludo |
  | «hola, ¿cómo estás?» | saludo |
  | «👋» | saludo |
  | «hi» | saludo |
  | «gracias» | cierre |
  | «ok» | cierre |
  | «👍» | cierre |
  | «hola, gracias» | cierre |
  | «chao, que estés bien» | cierre |
  | «hola, ¿cómo pago mi cuota?» (web) | ninguna (sigue el flujo normal) |
  | «necesito ayuda» | ninguna (mensaje sin respuesta) |
  | «?» | ninguna (mensaje sin respuesta) |
  | «dame una receta de pan» | ajeno |
  | «¿quién ganó el partido ayer?» | ajeno |
  | «¿cuántos días de vacaciones me quedan?» (web) | ajeno |

- Batería de elección contra el despliegue, con una pregunta con opciones pendiente de 3 opciones (dos FAQ y un procedimiento), con el 100 % de aciertos (RNF-5): «2», «la segunda», el texto parcial de la opción 2 y una paráfrasis suya eligen la opción 2; «hola, la 2» y «la 2, gracias» eligen la opción 2; «la 1 y la 2» eligen ambas FAQ; «4» y «ninguna» aplican el flujo de "sin respuesta"; «gracias» es un cierre y descarta la aclaración.
- Demo en el despliegue, en el chat web y en Google Chat, con el resultado esperado de cada mensaje:
  1. «hola» → saludo con las áreas del canal, sin canales oficiales ni aviso.
  2. «gracias» → cierre, sin canales oficiales ni aviso.
  3. «tengo un problema con mi pago» (web) → pregunta con hasta 3 temas de pagos numerados; al elegir uno («2»), la respuesta de esa FAQ.
  4. Misma pregunta y elección de dos FAQ («la 1 y la 3») → una sola respuesta con ambas.
  5. «necesito ayuda» → pregunta con las áreas del canal; «pagos» → pregunta con opciones si hay candidatos; si el siguiente mensaje tampoco tiene respuesta, flujo de "sin respuesta".
  6. «dame una receta de pan» → fuera de tema con las áreas del canal, sin derivar.
  7. Un procedimiento en curso no se interrumpe con una aclaración, y un «hola» en medio responde el saludo sin gastar un intento.
  8. (web) Consulta sin respuesta en horario → oferta de ejecutivo; «ok» → petición de nombre y contacto.
- `jailbreak_check` termina con código 0 contra el despliegue.
- Las 10 preguntas legítimas de la spec 001 siguen respondiéndose, y la prueba de carga de 50 sesiones cumple RNF-2.

## Dudas abiertas
- Ninguna.

## Decisiones registradas
- **Inferencia (2026-10-07, decisión del usuario):** los candidatos por debajo del umbral solo sirven para preguntar; para responder hace falta superar el umbral, salvo que el usuario elija la opción (RF-25 a RF-29).
- **Saludos y cierres con mensajes fijos (2026-10-07, decisión del usuario):** no los redacta el modelo.
- **Una pregunta con opciones seguida (2026-10-07, decisión del usuario):** el derecho a aclarar se recupera con cualquier respuesta que no sea una aclaración.
- **Sin pistas, pregunta con las áreas (2026-10-07, decisión del usuario):** si no hay candidatos, la aclaración nombra las áreas del canal.
- **Pedidos ajenos se declinan sin derivar (2026-10-07, decisión del usuario):** no se ofrece ejecutivo ni se avisa al área.
- **Mensajes fijos tras una aclaración (2026-10-07, decisión del usuario):** un saludo, un cierre, un fuera de tema, la negativa por manipulación o la petición de una persona descartan la aclaración pendiente sin aplicar "sin respuesta".
- **Mensajes fijos durante un flujo en curso (2026-10-07, decisión del usuario):** se responden y el procedimiento o la petición de datos sigue pendiente sin gastar un intento.
- **Textos fijos en la base de datos (2026-10-07, decisión del usuario):** son contenido de negocio por canal (constitución, punto 4); se editan en la base de datos sin despliegue.
- **Clasificación por el modelo (2026-10-07, decisión del usuario):** saludo, cierre y ajeno los decide el modelo en la llamada única, verificado con una batería de ejemplos al 100 %; si el modelo falla, se responde servicio no disponible.
- **Temas del otro canal son fuera de tema (2026-10-07, decisión del usuario):** se declinan con las áreas del propio canal, sin nombrar las del otro.
- **Elección de opciones (2026-10-07, decisión del usuario):** vale el número, el ordinal, el texto parcial o una paráfrasis, también con un saludo o un cierre; varias FAQ se responden juntas; un número fuera de rango o «ninguna» cuentan como no elegir; si el mensaje trae además otra consulta, solo se atiende la elección.
- **Respuesta a la oferta de ejecutivo (2026-10-07, decisión del usuario):** con la oferta pendiente, «ok» o «sí» la aceptan y «no, gracias» la rechaza; no son un cierre.
- **La pregunta de áreas no gasta la aclaración (2026-10-07, decisión del usuario):** tras ella puede venir una pregunta con opciones, pero no otra pregunta de áreas.
- **Aclaración por usuario en Google Chat (2026-10-07, decisión del usuario):** en un space de grupo solo elige quien recibió la aclaración.
- **Texto fijo ausente (2026-10-07, decisión del usuario):** se registra el error y el mensaje sigue el flujo normal de la spec 001.
- **Varios procedimientos elegidos (2026-10-07, decisión del usuario):** se responden las FAQ elegidas y se inicia solo el primer procedimiento; los demás se mencionan.
- **Coordinador con agentes de área (2026-10-07, decisión del usuario):** se vuelve a un agente del canal que resuelve o delega y a un agente con acciones propias por área, en ambos canales (constitución, punto 3). Sustituye la llamada única de la spec 001 (RNF-10 y D32 de su plan), cuyo p95 medido en local fue de 2,94 a 4,75 s; con agentes de área se midió 8,69 s.
- **Latencia: medir y decidir (2026-10-07, decisión del usuario):** RNF-2 se fija con la prueba de carga en el despliegue de prueba (RNF-2 de esta spec).
- **Mensaje fijo con la oferta pendiente (2026-10-07, decisión del usuario):** la oferta se mantiene (RF-61), igual que la petición de datos (RF-43).
- **Otro canal con candidatos propios (2026-10-07, decisión del usuario):** gana la coincidencia con el otro canal y se responde fuera de tema (RF-36).
- **Prioridad como lista ordenada (2026-10-07):** RF-39 agrupa en un solo requisito el orden de prioridad para que se lea y se pruebe de una vez; es una excepción consciente a «un requisito, una frase».
