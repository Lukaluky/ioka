from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    iata_code: str
    name: str
    city: str
    country_code: str
    type: str
