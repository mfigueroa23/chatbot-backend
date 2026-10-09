"""Acota lo que se consulta en Jira a los tableros permitidos (spec 002, RF-18, RF-19). Funciones puras."""
import re

ISSUE_KEY = re.compile(r"^([A-Z][A-Z0-9_]+)-\d+$")
ORDER_BY = re.compile(r"\s+order\s+by\s+.*$", re.IGNORECASE | re.DOTALL)

def board_of(key: str) -> str | None:
    match = ISSUE_KEY.match(key.strip().upper())
    return match.group(1) if match else None

def balanced(jql: str) -> bool:
    depth = 0
    for char in jql:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0

def scoped_jql(jql: str, boards: list[str]) -> str | None:
    """El JQL del modelo queda dentro de un paréntesis acotado a los tableros; uno que intente salir se rechaza."""
    if not boards:
        return None
    order = ORDER_BY.search(jql)
    core = jql[:order.start()].strip() if order else jql.strip()
    if not balanced(core):
        return None
    scope = "project in (" + ", ".join(f'"{board}"' for board in boards) + ")"
    scoped = f"{scope} AND ({core})" if core else scope
    return f"{scoped} {order.group(0).strip()}" if order else scoped
