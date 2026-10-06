from pydantic import BaseModel


class DepartmentsResponse(BaseModel):
    departments: list[str]


class MunicipalitiesResponse(BaseModel):
    department: str
    municipalities: list[str]
