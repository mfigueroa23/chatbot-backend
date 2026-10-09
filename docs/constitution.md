# Constitución — chatbot-backend

1. Stack fijo: Python 3.14, FastAPI, SQLAlchemy 2 async + asyncpg, PostgreSQL, Alembic, uv. Otra librería requiere aprobación.
2. Arquitectura: router → service → model; los routers no ejecutan SQL directamente.
3. Agentes: un coordinador orquesta; cada agente especializado tiene una única responsabilidad y una interfaz tipada.
4. Configuración: `.env` solo `DB_*` y `LOG_LEVEL`; el resto en la tabla `property`.
5. Tipado: `uv run pyright` con 0 errores en main.py, src, tests y alembic.
6. Tests: toda funcionalidad nueva incluye tests `*_test.py`; ninguno toca la BD (`dependency_overrides`).
7. CI verde (pyright + pytest) es requisito para fusionar a `main`.
8. Esquema: cada cambio va en una migración Alembic nueva y revisada; nunca se edita una aplicada.
9. Errores: excepciones propias en `src/utils/exceptions/`; fallos de BD responden 503, nunca 500 sin log.
10. Idioma: código en inglés; logs, errores y respuestas al usuario en español.
11. Specs: toda funcionalidad parte de `docs/specs/<feature>/spec.md` antes de implementarse.
12. Seguridad: sin secretos en el repo; ver SECURITY.md antes de guardar valores sensibles en `property`.
