# Política de seguridad

## Versiones soportadas

| Versión | Soportada |
|---|---|
| 1.0.x | Sí |

## Reportar una vulnerabilidad

No abras un issue público para reportar una vulnerabilidad.

Escribe al equipo de mantenimiento a **[correo de seguridad]** e incluye:

- Descripción del problema y su impacto.
- Pasos para reproducirlo.
- Versión o commit afectado.

Confirmaremos la recepción y te mantendremos informado mientras se corrige.

## Consideraciones de seguridad del proyecto

### Configuración en la tabla `property`

Toda la configuración de la aplicación, salvo la conexión a la base de datos y `LOG_LEVEL`, se guarda en la tabla `property` **en texto plano**. Cualquier persona con acceso de lectura a la base de datos, a sus backups o a sus logs de consultas puede ver esos valores, incluidos los secretos que se guarden ahí (por ejemplo, API keys).

Para reducir el riesgo:

- Limita el acceso de lectura a la tabla `property` a los usuarios que lo necesiten.
- Usa un usuario de base de datos propio para la aplicación, con los permisos mínimos.
- Protege y cifra los backups de la base de datos.
- Rota cualquier secreto que se haya expuesto.

### Archivo `.env`

- El `.env` contiene las credenciales de la base de datos y **no debe subirse al repositorio** (ya está en `.gitignore`).
- Usa `.env.example` como plantilla, sin valores reales.

### Logs

- No registres secretos ni valores de properties sensibles en los logs.
- En producción usa `LOG_LEVEL=INFO` o superior; el nivel `DEBUG` puede mostrar información interna.
