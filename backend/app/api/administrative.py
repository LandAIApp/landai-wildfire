from fastapi import APIRouter, Query

from ..schemas.administrative import DepartmentsResponse, MunicipalitiesResponse
from ..services import administrative

router = APIRouter(prefix='/api/v1/administrative', tags=['administrative'])


@router.get('/departments', response_model=DepartmentsResponse)
def departments() -> DepartmentsResponse:
    return DepartmentsResponse(departments=administrative.list_departments())


@router.get('/municipalities', response_model=MunicipalitiesResponse)
def municipalities(department: str = Query(..., min_length=1)) -> MunicipalitiesResponse:
    return MunicipalitiesResponse(department=department,
                                  municipalities=administrative.list_municipalities(department))
