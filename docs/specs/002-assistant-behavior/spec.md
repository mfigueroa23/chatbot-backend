# Spec 002 — Comportamiento de asistente

## Contexto y objetivo
La spec 001 (versión 1.1.0) solo responde cuando una FAQ o un procedimiento supera el umbral de similitud; cualquier
otro mensaje sigue el flujo de "sin respuesta" del canal. En el despliegue, «hola», «gracias», «tengo un problema con mi
pago» y «necesito ayuda» terminan mostrando los canales oficiales al cliente o avisando al área en el canal interno, como
si fueran consultas sin respuesta. Esta spec hace que el asistente se comporte como tal en ambos canales: saluda, cierra
la conversación, infiere lo que se le pide con una pregunta de aclaración cuando el pedido es ambiguo y declina lo que es
ajeno a sus áreas, sin derivar a una persona por mensajes que no lo requieren. Las respuestas con información siguen
apoyándose solo en las FAQ y los procedimientos (spec 001).

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
- **Umbral de respuesta:** el umbral de similitud de la spec 001; solo lo que lo supera puede usarse para responder.
- **Candidato:** FAQ o procedimiento del ámbito del canal cuya similitud con el mensaje está por debajo del umbral de respuesta y por encima del umbral de aclaración.
- **Consulta:** el tramo de conversación desde el primer mensaje que no recibe respuesta con información hasta que el sistema responde con una FAQ, inicia un procedimiento o aplica el flujo de "sin respuesta".

### Saludos, agradecimientos y despedidas
- RF-1: CUANDO el mensaje del usuario sea solo un saludo, EL SISTEMA responderá con el mensaje fijo de saludo del canal.
- RF-2: EL SISTEMA incluirá en el mensaje de saludo los nombres de las áreas activas del canal.
- RF-3: CUANDO el mensaje del usuario sea solo un agradecimiento o una despedida, EL SISTEMA responderá con el mensaje fijo de cierre del canal.
- RF-4: CUANDO un mensaje combine un saludo, un agradecimiento o una despedida con una consulta, EL SISTEMA responderá a la consulta según el resto de requisitos.
- RF-5: CUANDO el sistema responda con el mensaje de saludo o de cierre, EL SISTEMA no aplicará el flujo de "sin respuesta" del canal.

### Aclaración de pedidos ambiguos
- RF-6: SI ninguna FAQ ni procedimiento supera el umbral de respuesta y existe al menos un candidato, ENTONCES EL SISTEMA preguntará al usuario a cuál de los candidatos se refiere.
- RF-7: EL SISTEMA ofrecerá como opciones de una aclaración como máximo los 3 candidatos de mayor similitud.
- RF-8: EL SISTEMA nombrará cada opción de una aclaración por la pregunta de la FAQ o el nombre del procedimiento, sin incluir su respuesta ni sus pasos.
- RF-9: SI ninguna FAQ ni procedimiento supera el umbral de respuesta, no existe ningún candidato y el mensaje no es ajeno a las áreas del canal, ENTONCES EL SISTEMA preguntará al usuario con qué necesita ayuda nombrando las áreas activas del canal.
- RF-10: EL SISTEMA hará como máximo una aclaración por consulta.
- RF-11: CUANDO el usuario elija una de las opciones de la aclaración, EL SISTEMA responderá con la FAQ elegida o iniciará el procedimiento elegido aunque esté por debajo del umbral de respuesta.
- RF-12: SI el usuario no elige ninguna opción y su nuevo mensaje tampoco tiene una FAQ ni un procedimiento sobre el umbral de respuesta, ENTONCES EL SISTEMA aplicará el flujo de "sin respuesta" del canal.
- RF-13: EL SISTEMA no usará el contenido de un candidato para responder salvo en el caso de RF-11.
- RF-14: EL SISTEMA leerá el umbral de aclaración de la configuración en `property`.

### Pedidos ajenos a las áreas
- RF-15: SI el mensaje es ajeno a todas las áreas del canal, ENTONCES EL SISTEMA responderá con el mensaje fijo de fuera de tema del canal.
- RF-16: EL SISTEMA incluirá en el mensaje de fuera de tema los nombres de las áreas activas del canal.
- RF-17: CUANDO el sistema responda con el mensaje de fuera de tema, EL SISTEMA no aplicará el flujo de "sin respuesta" del canal.

### Convivencia con la spec 001
- RF-18: MIENTRAS haya un procedimiento en curso, EL SISTEMA aplicará el flujo de procedimientos de la spec 001 en lugar de una aclaración.
- RF-19: CUANDO el usuario pida explícitamente hablar con una persona, EL SISTEMA aplicará el flujo de la spec 001 (RF-26) sin hacer una aclaración.
- RF-20: CUANDO el sistema detecte un intento de manipulación (spec 001, RF-106 y RF-107), EL SISTEMA responderá con la respuesta de RF-108 de la spec 001 en lugar de un saludo, una aclaración o un mensaje de fuera de tema.
- RF-21: EL SISTEMA aplicará a las aclaraciones el auditor de RF-109 de la spec 001.
- RF-22: EL SISTEMA guardará los saludos, los cierres, las aclaraciones y los mensajes de fuera de tema en la memoria de la conversación.
- RF-23: EL SISTEMA solo enviará sin apoyo en una FAQ o un procedimiento los mensajes de saludo, de cierre, de aclaración y de fuera de tema (excepción a RF-9 y RF-89 de la spec 001).

## Requisitos no funcionales
- RNF-1: Se mantiene RNF-10 de la spec 001: como máximo una llamada de generación al modelo por mensaje del usuario.
- RNF-2: Se mantiene RNF-2 de la spec 001 (p95 < 5000 ms hasta la respuesta completa), medido con la misma prueba de 50 sesiones.
- RNF-3: Las aclaraciones y los mensajes fijos están en español, en el mismo tono que las respuestas del canal.
- RNF-4: En el canal web, ninguna aclaración ni mensaje fijo nombra áreas, FAQ ni procedimientos del ámbito interno (spec 001, RNF-3).

## Casos límite
- Saludo repetido en la misma conversación: se responde de nuevo con el mensaje de saludo.
- «Gracias» justo después de una aclaración: es un cierre (RF-3) y la aclaración pendiente se descarta.
- El usuario responde a una aclaración con una consulta distinta que sí supera el umbral: se responde esa consulta (RF-4 y spec 001) y la consulta anterior se da por cerrada.
- El usuario elige una opción que dejó de estar activa entre la aclaración y su respuesta: se aplica el flujo de "sin respuesta".
- Ninguna área activa en el canal: el saludo, la aclaración y el fuera de tema se envían sin la lista de áreas.
- Un candidato es un procedimiento y el usuario lo elige: el procedimiento empieza como en la spec 001, con sus intentos.
- Mensaje mixto entre ámbitos (spec 001, RF-8): conserva su comportamiento y no se aclara.
- Fuera de horario en el canal web: tras la aclaración sin éxito, el flujo de "sin respuesta" es el de fuera de horario (canales oficiales).

## Fuera de alcance
- Responder con candidatos por debajo del umbral sin que el usuario los elija.
- Conversación libre con el modelo (charla, opiniones o respuestas sin FAQ ni procedimiento), salvo los mensajes de esta spec.
- Editar desde la base de datos el texto de los mensajes fijos de saludo, cierre y fuera de tema.
- Botones, tarjetas o respuestas rápidas en la interfaz para elegir las opciones de una aclaración: se elige escribiendo.
- Más de una aclaración por consulta y aclaraciones dentro de un procedimiento en curso.
- Cambiar el flujo de "sin respuesta" de cada canal definido en la spec 001.

## Criterios de finalización
- Todos los RF tienen al menos un test `*_test.py` en verde, con dobles del modelo y del recuperador, sin base de datos ni red.
- `uv run pyright` sin errores.
- Demo en el despliegue, en el chat web y en Google Chat, con el resultado esperado de cada mensaje:
  1. «hola» → saludo con las áreas del canal, sin canales oficiales ni aviso.
  2. «gracias» → cierre, sin canales oficiales ni aviso.
  3. «tengo un problema con mi pago» (web) → aclaración con hasta 3 temas de pagos; al elegir uno, la respuesta de esa FAQ.
  4. «necesito ayuda» → pregunta con las áreas del canal; si el siguiente mensaje tampoco tiene respuesta, flujo de "sin respuesta".
  5. «dame una receta de pan» → fuera de tema con las áreas del canal, sin derivar.
  6. Un procedimiento en curso no se interrumpe con una aclaración.
- `jailbreak_check` termina con código 0 contra el despliegue.
- Las 10 preguntas legítimas de la spec 001 siguen respondiéndose, y la prueba de carga de 50 sesiones cumple RNF-2.

## Dudas abiertas
- Ninguna.

## Decisiones registradas
- **Inferencia (2026-10-07, decisión del usuario):** los candidatos por debajo del umbral solo sirven para preguntar; para responder hace falta superar el umbral, salvo que el usuario elija la opción (RF-11).
- **Saludos y cierres con mensajes fijos (2026-10-07, decisión del usuario):** no los redacta el modelo.
- **Una aclaración por consulta (2026-10-07, decisión del usuario):** el derecho a aclarar se recupera tras responder, iniciar un procedimiento o derivar.
- **Sin pistas, pregunta con las áreas (2026-10-07, decisión del usuario):** si no hay candidatos, la aclaración nombra las áreas del canal.
- **Pedidos ajenos se declinan sin derivar (2026-10-07, decisión del usuario):** no se ofrece ejecutivo ni se avisa al área.
