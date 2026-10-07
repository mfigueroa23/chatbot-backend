from typing import Literal
from pydantic import BaseModel, Field

class HealthResponse(BaseModel):
    servicio: str | None = Field(serialization_alias="Servicio")
    estado: Literal["DISPONIBLE", "NO DISPONIBLE"] = Field(serialization_alias="Estado")
