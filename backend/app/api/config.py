from fastapi import APIRouter

from ..core.config import get_settings
from ..core.rate_limit import describe_limits
from ..schemas.config import PublicConfig
from ..wildfire.config import THRESHOLD_SPECS

router = APIRouter(prefix='/api/v1', tags=['config'])


@router.get('/config', response_model=PublicConfig)
def public_config() -> PublicConfig:
    """Authoritative limits for the frontend (never hard-coded there). Contains no secrets."""
    s = get_settings()
    return PublicConfig(
        version='2.0.0',
        aoi={
            'municipality': {'max_hectares': s.max_aoi_hectares, 'warn_hectares': s.warn_aoi_hectares},
            'custom': {'max_hectares': s.max_custom_aoi_hectares, 'warn_hectares': s.warn_custom_aoi_hectares,
                       'min_hectares': s.min_custom_aoi_hectares, 'max_vertices': s.max_polygon_vertices},
            'min_fire_date': s.min_fire_date,
        },
        exposure={
            'max_aoi_hectares': s.max_exposure_aoi_hectares, 'default_buffer_m': s.exposure_default_buffer_m,
            'max_buffer_m': s.exposure_max_buffer_m, 'max_layer_features': s.exposure_max_layer_features,
            'thresholds': [t[0] for t in THRESHOLD_SPECS], 'default_threshold': 0.72,
            'population_year': s.worldpop_year, 'population_resolution': s.worldpop_resolution,
        },
        rate_limits={'analyze': describe_limits(s.rate_limit_analyze),
                     'exposure': describe_limits(s.rate_limit_exposure), 'enabled': s.rate_limit_enabled},
        sources={'openstreetmap': 'Overpass API (ODbL)', 'worldpop': f'WorldPop {s.worldpop_api_version}',
                 'earth_observation': 'Sentinel-2 / VIIRS via Google Earth Engine'},
    )
