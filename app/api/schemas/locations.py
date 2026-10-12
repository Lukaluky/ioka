from pydantic import BaseModel


class LocationResponse(BaseModel):
    iata_code: str
    name: str
    city: str
    country_code: str
    type: str
