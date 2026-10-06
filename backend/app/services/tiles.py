"""Earth Engine map tile URLs (getMapId). Pixels are never proxied via FastAPI."""
from __future__ import annotations

import ee

from ..core.earth_engine import ensure_initialized
from ..core.errors import TileGenerationError
from ..schemas.wildfire import Issue, LayerInfo, LegendInfo

PROB_PALETTE = ['000080', '00FFFF', 'FFFF00', 'FF8C00', '8B0000']
RGB_VIS = {'bands': ['B12', 'B8A', 'B4'], 'min': 0.02, 'max': 0.40}


def _solid(color: str) -> dict:
    return {'min': 0, 'max': 1, 'palette': [color]}


def _gradient(vmin: float, vmax: float, palette: list[str]) -> dict:
    return {'min': vmin, 'max': vmax, 'palette': palette}


# (id, label, group, description, result key, vis params, visible by default, legend)
LAYER_SPECS = [
    ('post', 'POST image', 'Imagery', 'Satellite image after the fire (SWIR/NIR/Red).',
     'post', RGB_VIS, True, LegendInfo(type='rgb')),
    ('pre', 'PRE image', 'Imagery', 'Reference satellite image before the fire.',
     'pre', RGB_VIS, False, LegendInfo(type='rgb')),
    ('dnbr', 'dNBR change', 'Evidence', 'Spectral change associated with vegetation loss / burning.',
     'dNBR', _gradient(-0.20, 0.70, ['2166AC', 'FFFFFF', 'FFFF00', 'FF8C00', '8B0000']), False,
     LegendInfo(type='gradient', min=-0.2, max=0.7,
                colors=['#2166AC', '#FFFFFF', '#FFFF00', '#FF8C00', '#8B0000'])),
    ('spectral_evidence', 'Spectral evidence', 'Evidence',
     'Combination of several burn indices (0-1).', 'spectralEvidence',
     _gradient(0, 1, PROB_PALETTE), False,
     LegendInfo(type='gradient', min=0, max=1, colors=['#' + c for c in PROB_PALETTE])),
    ('wildfire_likelihood', 'Wildfire likelihood', 'Results',
     'Relative burn likelihood (0-1). Not a calibrated probability.', 'wildfireLikelihood',
     _gradient(0, 1, PROB_PALETTE), False,
     LegendInfo(type='gradient', min=0, max=1, colors=['#' + c for c in PROB_PALETTE])),
    ('burn_050', 'Burn >= 0.50 (probable)', 'Results',
     'Cleaned area with likelihood of at least 0.50.', 'burn050', _solid('FF0000'), True,
     LegendInfo(type='solid', colors=['#FF0000'])),
    ('burn_072', 'Burn >= 0.72 (high confidence)', 'Results',
     'Cleaned area with likelihood of at least 0.72.', 'burn072', _solid('8B0000'), False,
     LegendInfo(type='solid', colors=['#8B0000'])),
    ('viirs', 'VIIRS active fires', 'Context', 'Thermal detections from VIIRS.', 'viirs',
     _solid('00FFFF'), False, LegendInfo(type='solid', colors=['#00FFFF'])),
    ('agriculture_score', 'Agriculture score', 'Context',
     'Agricultural evidence used to reduce false positives.', 'agricultureScore',
     _gradient(0, 1, ['FFFFFF', 'FFFF00', 'FF00FF']), False,
     LegendInfo(type='gradient', min=0, max=1, colors=['#FFFFFF', '#FFFF00', '#FF00FF'])),
    ('observation_quality', 'Observation quality', 'Context',
     'Relative availability of PRE and POST observations.', 'observationQuality',
     _gradient(0, 1, ['FF0000', 'FFFF00', '00FF00']), False,
     LegendInfo(type='gradient', min=0, max=1, colors=['#FF0000', '#FFFF00', '#00FF00'])),
    # Extra threshold layers (same masks as the reference, for threshold exploration)
    ('burn_035', 'Burn >= 0.35 (possible)', 'Thresholds', 'Cleaned area with likelihood >= 0.35.',
     'burn035', _solid('FFA500'), False, LegendInfo(type='solid', colors=['#FFA500'])),
    ('burn_060', 'Burn >= 0.60 (moderate-high)', 'Thresholds', 'Cleaned area with likelihood >= 0.60.',
     'burn060', _solid('FF4500'), False, LegendInfo(type='solid', colors=['#FF4500'])),
    ('burn_085', 'Burn >= 0.85 (very high)', 'Thresholds', 'Cleaned area with likelihood >= 0.85.',
     'burn085', _solid('4B0082'), False, LegendInfo(type='solid', colors=['#4B0082'])),
]


def build_layers(result: dict) -> tuple[list[LayerInfo], list[Issue]]:
    """Create tile URLs for every layer. Failed layers become warnings; all failing raises."""
    ensure_initialized()
    layers: list[LayerInfo] = []
    warnings: list[Issue] = []
    for lid, label, group, desc, key, vis, default, legend in LAYER_SPECS:
        try:
            map_id = result[key].getMapId(vis)
            url = map_id['tile_fetcher'].url_format
        except (ee.EEException, KeyError, AttributeError) as exc:
            warnings.append(Issue(code='layer_unavailable',
                                  message=f"Layer '{label}' could not be generated: {str(exc)[:160]}"))
            continue
        layers.append(LayerInfo(id=lid, label=label, group=group, description=desc, tile_url=url,
                                visible_by_default=default, legend=legend))
    if not layers:
        raise TileGenerationError('No map layers could be generated.',
                                  details=[w.message for w in warnings])
    return layers, warnings
