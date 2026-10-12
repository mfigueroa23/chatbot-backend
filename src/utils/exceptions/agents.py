class AgentNotFoundError(Exception):
  def __init__(self, name: str):
    super().__init__(f"El agente '{name}' no se encuentra configurado en la base de datos")
    self.name = name
