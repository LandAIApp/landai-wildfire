// ============================================================================
// FIRE FOREST COLOMBIA - V7.6
// ============================================================================
//
// Sentinel-2 + VIIRS + Random Forest + filtro agrícola
//
// VERSIÓN FUNCIONAL DE REFERENCIA
//
// Características:
// - Modelo pseudo-supervisado.
// - PRE / POST Sentinel-2.
// - dNBR, dNBR2, MIRBI, NDVI, BAIS2.
// - Contexto histórico.
// - Dynamic World + WorldCover para agricultura.
// - VIIRS como evidencia de incendio.
// - Random Forest.
// - Probabilidad relativa de quema.
// - Limpieza espacial por conectividad.
// - Estadísticas para varios thresholds.
// - Interfaz por departamento/municipio.
// - Capas interpretables en español.
//
// ============================================================================


// ============================================================================
// 0. DATOS ADMINISTRATIVOS
// ============================================================================

var MUNICIPALITIES_ASSET =
  'users/maikolzaraza07/mpios';


var municipalities =
  ee.FeatureCollection(
    MUNICIPALITIES_ASSET
  );


var DEPARTMENT_FIELD =
  'ADM1_ES';


var MUNICIPALITY_FIELD =
  'ADM2_ES';


var MUNICIPALITY_CODE_FIELD =
  'ADM2_PCODE';


// ============================================================================
// 0.1 VALORES INICIALES
// ============================================================================

var DEFAULT_DEPARTMENT =
  'Tolima';


var DEFAULT_MUNICIPALITY =
  'San Luis';


var DEFAULT_FIRE_DATE =
  '2026-08-05';


var DEFAULT_END_DATE =
  '2026-08-15';


var DATE_START =
  '2025-01-01';


var DATE_END =
  '2026-12-31';


// ============================================================================
// 1. PARÁMETROS DEL MODELO
// ============================================================================

// Cloud Score+
var CLEAR_THRESHOLD =
  0.55;


// VIIRS
var VIIRS_SEED_BUFFER =
  700;


var VIIRS_PRIOR_BUFFER =
  3000;


// Random Forest
var N_TREES =
  150;


// Muestras
var N_POSITIVE_SAMPLES =
  3000;


var N_NEGATIVE_SAMPLES =
  5000;


// Thresholds
var LOW_THRESHOLD =
  0.35;


var MEDIUM_THRESHOLD =
  0.50;


var HIGH_THRESHOLD =
  0.72;


// Dynamic World
var DW_CROP_PROB_THRESHOLD =
  0.40;


// Agricultura
var AGRI_STRONG_THRESHOLD =
  0.55;


var AGRI_VERY_STRONG_THRESHOLD =
  0.70;


// Limpieza espacial
var MIN_CONNECTED_PIXELS =
  6;


// ============================================================================
// 2. DATASETS
// ============================================================================

var S2 =
  ee.ImageCollection(
    'COPERNICUS/S2_SR_HARMONIZED'
  );


var CLOUD_SCORE =
  ee.ImageCollection(
    'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'
  );


var S2_LINKED =
  S2.linkCollection(
    CLOUD_SCORE,
    ['cs_cdf']
  );


var WORLDCOVER =
  ee.ImageCollection(
    'ESA/WorldCover/v200'
  )
  .first()
  .select('Map');


// ============================================================================
// 3. MÁSCARA SENTINEL-2
// ============================================================================

function maskS2(image) {

  var clear =
    image
    .select('cs_cdf')
    .gte(
      CLEAR_THRESHOLD
    );


  var scl =
    image.select('SCL');


  var valid =
    scl.neq(1)
    .and(scl.neq(3))
    .and(scl.neq(7))
    .and(scl.neq(8))
    .and(scl.neq(9))
    .and(scl.neq(10))
    .and(scl.neq(11));


  return image

    .updateMask(
      clear
    )

    .updateMask(
      valid
    )

    .divide(
      10000
    )

    .copyProperties(
      image,
      ['system:time_start']
    );
}


// ============================================================================
// 4. ÍNDICES DE QUEMA
// ============================================================================

function addBurnIndices(image) {

  var B4 =
    image.select('B4');

  var B5 =
    image.select('B5');

  var B6 =
    image.select('B6');

  var B7 =
    image.select('B7');

  var B8 =
    image.select('B8');

  var B8A =
    image.select('B8A');

  var B11 =
    image.select('B11');

  var B12 =
    image.select('B12');


  // NBR
  var NBR =
    B8A
    .subtract(B12)

    .divide(
      B8A.add(B12)
    )

    .rename(
      'NBR'
    );


  // NBR invertido para qualityMosaic POST
  var BurnNBR =
    B12
    .subtract(B8A)

    .divide(
      B12.add(B8A)
    )

    .rename(
      'BurnNBR'
    );


  // NBR2
  var NBR2 =
    B12
    .subtract(B11)

    .divide(
      B12.add(B11)
    )

    .rename(
      'NBR2'
    );


  // MIRBI
  var MIRBI =
    B12
    .multiply(10)

    .subtract(
      B11.multiply(9.8)
    )

    .add(2)

    .rename(
      'MIRBI'
    );


  // NDVI
  var NDVI =
    B8
    .subtract(B4)

    .divide(
      B8.add(B4)
    )

    .rename(
      'NDVI'
    );


  // BAIS2
  var eps =
    ee.Image.constant(
      0.0001
    );


  var term1 =
    ee.Image(1)

    .subtract(

      B6
      .multiply(B7)
      .multiply(B8A)

      .divide(
        B4.max(eps)
      )

      .max(0)
      .sqrt()

    );


  var term2 =
    B12
    .subtract(B8A)

    .divide(

      B12
      .add(B8A)
      .max(eps)
      .sqrt()

    )

    .add(1);


  var BAIS2 =
    term1
    .multiply(term2)

    .rename(
      'BAIS2'
    );


  return image.addBands([

    NBR,
    BurnNBR,
    NBR2,
    MIRBI,
    NDVI,
    BAIS2

  ]);
}


// ============================================================================
// 5. ÍNDICES HISTÓRICOS
// ============================================================================

function addHistoryIndices(image) {

  var NBR =
    image
    .normalizedDifference(
      ['B8A', 'B12']
    )
    .rename(
      'NBR'
    );


  var NDVI =
    image
    .normalizedDifference(
      ['B8', 'B4']
    )
    .rename(
      'NDVI'
    );


  return ee.Image.cat([

    NBR,
    NDVI

  ])

  .copyProperties(
    image,
    ['system:time_start']
  );
}


// ============================================================================
// 6. NORMALIZACIÓN 0-1
// ============================================================================

function scale01(
  image,
  low,
  high
) {

  return image

  .subtract(
    low
  )

  .divide(

    ee.Number(high)
    .subtract(low)

  )

  .clamp(
    0,
    1
  );
}


// ============================================================================
// 7. VIIRS - NORMALIZACIÓN
// ============================================================================

function normalizeVIIRSConfidence(image) {

  return image

  .select(
    'confidence'
  )

  .unmask(0)

  .toByte()

  .rename(
    'confidence'
  )

  .copyProperties(
    image,
    ['system:time_start']
  );
}


// ============================================================================
// 8. VENTANAS TEMPORALES
// ============================================================================

function getTimeWindows(
  fireDate,
  analysisEnd
) {

  var PRE_START =
    fireDate.advance(
      -90,
      'day'
    );


  var PRE_END =
    fireDate.advance(
      -7,
      'day'
    );


  var POST_START =
    fireDate;


  var POST_END =
    analysisEnd.advance(
      1,
      'day'
    );


  var HISTORY_START =
    fireDate.advance(
      -6,
      'month'
    );


  var HISTORY_END =
    fireDate.advance(
      -15,
      'day'
    );


  return {

    PRE_START:
      PRE_START,

    PRE_END:
      PRE_END,

    POST_START:
      POST_START,

    POST_END:
      POST_END,

    HISTORY_START:
      HISTORY_START,

    HISTORY_END:
      HISTORY_END

  };
}


// ============================================================================
// 9. DISPONIBILIDAD DE DATOS
// ============================================================================

function getInputAvailability(
  aoi,
  fireDate,
  analysisEnd
) {

  var t =
    getTimeWindows(
      fireDate,
      analysisEnd
    );


  var pre =
    S2_LINKED

    .filterBounds(aoi)

    .filterDate(
      t.PRE_START,
      t.PRE_END
    )

    .filter(
      ee.Filter.lt(
        'CLOUDY_PIXEL_PERCENTAGE',
        85
      )
    );


  var post =
    S2_LINKED

    .filterBounds(aoi)

    .filterDate(
      t.POST_START,
      t.POST_END
    )

    .filter(
      ee.Filter.lt(
        'CLOUDY_PIXEL_PERCENTAGE',
        90
      )
    );


  var history =
    S2_LINKED

    .filterBounds(aoi)

    .filterDate(
      t.HISTORY_START,
      t.HISTORY_END
    )

    .filter(
      ee.Filter.lt(
        'CLOUDY_PIXEL_PERCENTAGE',
        85
      )
    );


  return ee.Dictionary({

    preScenes:
      pre.size(),

    postScenes:
      post.size(),

    historyScenes:
      history.size(),

    preStart:
      t.PRE_START
      .format(
        'YYYY-MM-dd'
      ),

    preEnd:
      t.PRE_END
      .advance(
        -1,
        'day'
      )
      .format(
        'YYYY-MM-dd'
      ),

    postStart:
      t.POST_START
      .format(
        'YYYY-MM-dd'
      ),

    postEnd:
      analysisEnd
      .format(
        'YYYY-MM-dd'
      ),

    historyStart:
      t.HISTORY_START
      .format(
        'YYYY-MM-dd'
      ),

    historyEnd:
      t.HISTORY_END
      .advance(
        -1,
        'day'
      )
      .format(
        'YYYY-MM-dd'
      )

  });
}


// ============================================================================
// 10. LIMPIEZA ESPACIAL
// ============================================================================

function cleanProbabilityMask(
  probabilityImage,
  threshold,
  minPixels
) {

  var binary =
    probabilityImage

    .gte(
      threshold
    )

    .selfMask();


  var connected =
    binary

    .connectedPixelCount(
      100,
      true
    );


  return binary

  .updateMask(

    connected.gte(
      minPixels
    )

  );
}


// ============================================================================
// 11. MODELO PRINCIPAL
// ============================================================================

function runBurnModel(
  aoi,
  fireDate,
  analysisEnd
) {

  var t =
    getTimeWindows(
      fireDate,
      analysisEnd
    );


  // ==========================================================================
  // PRE
  // ==========================================================================

  var preCollection =
    S2_LINKED

    .filterBounds(aoi)

    .filterDate(
      t.PRE_START,
      t.PRE_END
    )

    .filter(
      ee.Filter.lt(
        'CLOUDY_PIXEL_PERCENTAGE',
        85
      )
    )

    .map(
      maskS2
    )

    .map(
      addBurnIndices
    );


  // ==========================================================================
  // POST
  // ==========================================================================

  var postCollection =
    S2_LINKED

    .filterBounds(aoi)

    .filterDate(
      t.POST_START,
      t.POST_END
    )

    .filter(
      ee.Filter.lt(
        'CLOUDY_PIXEL_PERCENTAGE',
        90
      )
    )

    .map(
      maskS2
    )

    .map(
      addBurnIndices
    );


  // ==========================================================================
  // OBSERVACIONES
  // ==========================================================================

  var preCount =
    preCollection

    .select(
      'B8A'
    )

    .count()

    .rename(
      'preCount'
    );


  var postCount =
    postCollection

    .select(
      'B8A'
    )

    .count()

    .rename(
      'postCount'
    );


  var observed =
    preCount.gt(0)

    .and(
      postCount.gt(0)
    );


  // ==========================================================================
  // MOSAICOS
  // ==========================================================================

  var pre =
    preCollection

    .median()

    .clip(
      aoi
    );


  var post =
    postCollection

    .qualityMosaic(
      'BurnNBR'
    )

    .clip(
      aoi
    );


  // ==========================================================================
  // CAMBIOS
  // ==========================================================================

  var dNBR =
    pre
    .select('NBR')

    .subtract(
      post.select('NBR')
    )

    .rename(
      'dNBR'
    );


  var dNBR2 =
    post
    .select('NBR2')

    .subtract(
      pre.select('NBR2')
    )

    .rename(
      'dNBR2'
    );


  var dMIRBI =
    post
    .select('MIRBI')

    .subtract(
      pre.select('MIRBI')
    )

    .rename(
      'dMIRBI'
    );


  var dNDVI =
    pre
    .select('NDVI')

    .subtract(
      post.select('NDVI')
    )

    .rename(
      'dNDVI'
    );


  var dBAIS2 =
    post
    .select('BAIS2')

    .subtract(
      pre.select('BAIS2')
    )

    .rename(
      'dBAIS2'
    );


  var dB4 =
    post
    .select('B4')

    .subtract(
      pre.select('B4')
    )

    .rename(
      'dB4'
    );


  var dB5 =
    post
    .select('B5')

    .subtract(
      pre.select('B5')
    )

    .rename(
      'dB5'
    );


  var dB8A =
    post
    .select('B8A')

    .subtract(
      pre.select('B8A')
    )

    .rename(
      'dB8A'
    );


  var dB11 =
    post
    .select('B11')

    .subtract(
      pre.select('B11')
    )

    .rename(
      'dB11'
    );


  var dB12 =
    post
    .select('B12')

    .subtract(
      pre.select('B12')
    )

    .rename(
      'dB12'
    );


  // ==========================================================================
  // HISTÓRICO
  // ==========================================================================

  var historyCollection =
    S2_LINKED

    .filterBounds(aoi)

    .filterDate(
      t.HISTORY_START,
      t.HISTORY_END
    )

    .filter(
      ee.Filter.lt(
        'CLOUDY_PIXEL_PERCENTAGE',
        85
      )
    )

    .map(
      maskS2
    )

    .map(
      addHistoryIndices
    );


  var nbrStd =
    historyCollection

    .select(
      'NBR'
    )

    .reduce(
      ee.Reducer.stdDev()
    )

    .rename(
      'NBR_std'
    )

    .unmask(0);


  var ndviStd =
    historyCollection

    .select(
      'NDVI'
    )

    .reduce(
      ee.Reducer.stdDev()
    )

    .rename(
      'NDVI_std'
    )

    .unmask(0);


  var nbrChangeZ =
    dNBR

    .divide(
      nbrStd.add(0.03)
    )

    .clamp(
      -10,
      10
    )

    .rename(
      'NBR_change_z'
    );


  // ==========================================================================
  // DYNAMIC WORLD
  // ==========================================================================

  var dynamicWorld =
    ee.ImageCollection(
      'GOOGLE/DYNAMICWORLD/V1'
    )

    .filterBounds(aoi)

    .filterDate(
      t.HISTORY_START,
      t.HISTORY_END
    );


  var cropCollection =
    dynamicWorld
    .select(
      'crops'
    );


  var cropProbability =
    cropCollection

    .median()

    .unmask(0)

    .clip(aoi)

    .rename(
      'cropProbability'
    );


  var cropFrequency =
    cropCollection

    .map(

      function(image) {

        return image

        .gte(
          DW_CROP_PROB_THRESHOLD
        )

        .rename(
          'cropFlag'
        );

      }

    )

    .mean()

    .unmask(0)

    .clip(aoi)

    .rename(
      'cropFrequency'
    );


  // ==========================================================================
  // WORLDCOVER
  // ==========================================================================

  var worldCover =
    WORLDCOVER
    .clip(aoi);


  var wcCrop =
    worldCover

    .eq(40)

    .rename(
      'wcCrop'
    );


  var wcBuilt =
    worldCover
    .eq(50);


  var wcWater =
    worldCover
    .eq(80);


  // ==========================================================================
  // AGRICULTURA
  // ==========================================================================

  var agricultureScore =
    wcCrop

    .multiply(
      0.50
    )

    .add(

      cropProbability
      .multiply(
        0.20
      )

    )

    .add(

      cropFrequency
      .multiply(
        0.30
      )

    )

    .clamp(
      0,
      1
    )

    .rename(
      'AgricultureScore'
    );


  var agricultureStrong =
    agricultureScore

    .gte(
      AGRI_STRONG_THRESHOLD
    );


  var agricultureVeryStrong =
    agricultureScore

    .gte(
      AGRI_VERY_STRONG_THRESHOLD
    );


  // ==========================================================================
  // VIIRS
  // ==========================================================================

  var viirsSNPP =
    ee.ImageCollection(
      'NASA/LANCE/SNPP_VIIRS/C2'
    )

    .filterBounds(aoi)

    .filterDate(

      fireDate.advance(
        -10,
        'day'
      ),

      t.POST_END

    )

    .map(
      normalizeVIIRSConfidence
    );


  var viirsNOAA20 =
    ee.ImageCollection(
      'NASA/LANCE/NOAA20_VIIRS/C2'
    )

    .filterBounds(aoi)

    .filterDate(

      fireDate.advance(
        -10,
        'day'
      ),

      t.POST_END

    )

    .map(
      normalizeVIIRSConfidence
    );


  var viirsCollection =
    viirsSNPP

    .merge(
      viirsNOAA20
    );


  var viirsFallback =
    ee.Image.constant(0)

    .toByte()

    .rename(
      'confidence'
    )

    .clip(aoi);


  var viirsConfidence =
    ee.ImageCollection([

      viirsFallback

    ])

    .merge(
      viirsCollection
    )

    .max()

    .toByte()

    .rename(
      'confidence'
    );


  var viirsFire =
    viirsConfidence

    .gte(1)

    .selfMask()

    .toByte()

    .rename(
      'VIIRS'
    );


  // ==========================================================================
  // VIIRS A VECTORES
  // ==========================================================================

  var viirsPoints =
    viirsFire

    .reduceToVectors({

      geometry:
        aoi,

      scale:
        375,

      geometryType:
        'centroid',

      eightConnected:
        true,

      maxPixels:
        1e7,

      tileScale:
        4

    });


  var viirsSeedFC =
    viirsPoints

    .map(

      function(feature) {

        return feature.buffer(
          VIIRS_SEED_BUFFER
        );

      }

    );


  var viirsSeedZone =
    ee.Image(0)

    .byte()

    .paint(
      viirsSeedFC,
      1
    )

    .clip(aoi);


  var viirsPriorFC =
    viirsPoints

    .map(

      function(feature) {

        return feature.buffer(
          VIIRS_PRIOR_BUFFER
        );

      }

    );


  var viirsPriorZone =
    ee.Image(0)

    .byte()

    .paint(
      viirsPriorFC,
      1
    )

    .clip(aoi);


  // ==========================================================================
  // EVIDENCIA ESPECTRAL
  // ==========================================================================

  var evidenceDNBR =
    scale01(
      dNBR,
      0.08,
      0.50
    );


  var evidenceMIRBI =
    scale01(
      dMIRBI,
      0.03,
      0.45
    );


  var evidenceNBR2 =
    scale01(
      dNBR2,
      0.01,
      0.20
    );


  var evidenceNDVI =
    scale01(
      dNDVI,
      0.03,
      0.35
    );


  var evidenceBAIS2 =
    scale01(
      dBAIS2,
      0.05,
      1.50
    );


  var spectralEvidence =
    evidenceDNBR
    .multiply(0.32)

    .add(
      evidenceMIRBI
      .multiply(0.22)
    )

    .add(
      evidenceNBR2
      .multiply(0.14)
    )

    .add(
      evidenceNDVI
      .multiply(0.14)
    )

    .add(
      evidenceBAIS2
      .multiply(0.18)
    )

    .rename(
      'SpectralEvidence'
    );


  // ==========================================================================
  // ANOMALÍA
  // ==========================================================================

  var anomalyEvidence =
    scale01(
      nbrChangeZ,
      1,
      5
    )

    .rename(
      'AnomalyEvidence'
    );


  var enhancedEvidence =
    spectralEvidence

    .multiply(
      0.75
    )

    .add(

      anomalyEvidence
      .multiply(
        0.25
      )

    )

    .rename(
      'EnhancedEvidence'
    );


  // ==========================================================================
  // SEMILLAS POSITIVAS
  // ==========================================================================

  var fireSeed =
    viirsSeedZone

    .eq(1)

    .and(
      enhancedEvidence.gt(0.40)
    )

    .and(
      dNBR.gt(0.08)
    )

    .and(
      observed
    );


  var spectralSeed =
    enhancedEvidence

    .gt(0.72)

    .and(
      nbrChangeZ.gt(2.3)
    )

    .and(
      dNBR.gt(0.22)
    )

    .and(
      dMIRBI.gt(0.06)
    )

    .and(
      agricultureVeryStrong.not()
    )

    .and(
      wcWater.not()
    )

    .and(
      wcBuilt.not()
    )

    .and(
      observed
    );


  var agriculturalFireSeed =
    agricultureStrong

    .and(
      viirsPriorZone.eq(1)
    )

    .and(
      enhancedEvidence.gt(0.80)
    )

    .and(
      nbrChangeZ.gt(3.0)
    )

    .and(
      dNBR.gt(0.30)
    )

    .and(
      dMIRBI.gt(0.10)
    )

    .and(
      observed
    );


  var positiveSeed =
    fireSeed

    .or(
      spectralSeed
    )

    .or(
      agriculturalFireSeed
    )

    .selfMask()

    .rename(
      'PositiveSeed'
    );


  // ==========================================================================
  // SEMILLAS NEGATIVAS
  // ==========================================================================

  var stableNegative =
    dNBR

    .lt(0.03)

    .and(
      dMIRBI.lt(0.03)
    )

    .and(
      observed
    );


  var cropHardNegative =
    agricultureStrong

    .and(
      cropFrequency.gt(0.30)
    )

    .and(
      nbrChangeZ.lt(2.0)
    )

    .and(
      viirsPriorZone.eq(0)
    )

    .and(
      observed
    );


  var veryStrongCropNegative =
    agricultureVeryStrong

    .and(
      enhancedEvidence.lt(0.72)
    )

    .and(
      viirsSeedZone.eq(0)
    )

    .and(
      observed
    );


  var seasonalCropNegative =
    agricultureStrong

    .and(
      nbrStd.gt(0.14)
    )

    .and(
      ndviStd.gt(0.14)
    )

    .and(
      enhancedEvidence.lt(0.65)
    )

    .and(
      viirsPriorZone.eq(0)
    )

    .and(
      observed
    );


  var surfaceNegative =
    wcWater

    .or(
      wcBuilt
    )

    .and(
      observed
    );


  var negativeSeed =
    stableNegative

    .or(
      cropHardNegative
    )

    .or(
      veryStrongCropNegative
    )

    .or(
      seasonalCropNegative
    )

    .or(
      surfaceNegative
    )

    .selfMask()

    .rename(
      'NegativeSeed'
    );


  // ==========================================================================
  // VARIABLES RF
  // ==========================================================================

  var features =
    ee.Image.cat([

      // PRE
      pre.select('B4')
      .rename('pre_B4'),

      pre.select('B5')
      .rename('pre_B5'),

      pre.select('B8A')
      .rename('pre_B8A'),

      pre.select('B11')
      .rename('pre_B11'),

      pre.select('B12')
      .rename('pre_B12'),

      pre.select('NBR')
      .rename('pre_NBR'),


      // POST
      post.select('B4')
      .rename('post_B4'),

      post.select('B5')
      .rename('post_B5'),

      post.select('B8A')
      .rename('post_B8A'),

      post.select('B11')
      .rename('post_B11'),

      post.select('B12')
      .rename('post_B12'),

      post.select('NBR')
      .rename('post_NBR'),


      // CAMBIO
      dB4,
      dB5,
      dB8A,
      dB11,
      dB12,

      dNBR,
      dNBR2,
      dMIRBI,
      dNDVI,
      dBAIS2,


      // HISTÓRICO
      nbrStd,
      ndviStd,
      nbrChangeZ,


      // AGRICULTURA
      cropProbability,
      cropFrequency,
      wcCrop,
      agricultureScore,


      // EVIDENCIA
      enhancedEvidence

    ])

    .updateMask(
      observed
    )

    .clip(aoi);


  var predictors =
    features.bandNames();


  // ==========================================================================
  // ETIQUETAS
  // ==========================================================================

  var positiveLabel =
    positiveSeed

    .multiply(0)

    .add(1)

    .rename(
      'class'
    );


  var negativeLabel =
    negativeSeed

    .multiply(0)

    .rename(
      'class'
    );


  // ==========================================================================
  // MUESTREO
  // ==========================================================================

  var positiveSamples =
    features

    .addBands(
      positiveLabel
    )

    .updateMask(
      positiveSeed
    )

    .sample({

      region:
        aoi,

      scale:
        20,

      numPixels:
        N_POSITIVE_SAMPLES,

      seed:
        2026,

      geometries:
        false,

      tileScale:
        4

    });


  var negativeSamples =
    features

    .addBands(
      negativeLabel
    )

    .updateMask(
      negativeSeed
    )

    .sample({

      region:
        aoi,

      scale:
        20,

      numPixels:
        N_NEGATIVE_SAMPLES,

      seed:
        2027,

      geometries:
        false,

      tileScale:
        4

    });


  var training =
    positiveSamples

    .merge(
      negativeSamples
    );


  // ==========================================================================
  // RANDOM FOREST
  // ==========================================================================

  var RF =
    ee.Classifier

    .smileRandomForest({

      numberOfTrees:
        N_TREES,

      variablesPerSplit:
        null,

      minLeafPopulation:
        3,

      bagFraction:
        0.65,

      seed:
        2026

    })

    .setOutputMode(
      'PROBABILITY'
    )

    .train({

      features:
        training,

      classProperty:
        'class',

      inputProperties:
        predictors

    });


  var rfLikelihood =
    features

    .classify(
      RF
    )

    .rename(
      'RFLikelihood'
    );


  // ==========================================================================
  // CALIDAD DE OBSERVACIÓN
  // ==========================================================================

  var observationQuality =
    preCount

    .min(3)

    .divide(3)

    .multiply(

      postCount
      .min(3)
      .divide(3)

    )

    .sqrt()

    .rename(
      'ObservationQuality'
    );


  // ==========================================================================
  // PROBABILIDAD BASE
  // ==========================================================================

  var viirsBonus =
    viirsPriorZone

    .eq(1)

    .multiply(
      0.08
    );


  var surfacePenalty =
    wcWater

    .or(
      wcBuilt
    )

    .multiply(
      0.40
    );


  var baseLikelihood =
    rfLikelihood

    .multiply(
      0.72
    )

    .add(

      enhancedEvidence
      .multiply(
        0.28
      )

    )

    .add(
      viirsBonus
    )

    .subtract(
      surfacePenalty
    )

    .multiply(

      observationQuality
      .multiply(0.15)
      .add(0.85)

    )

    .clamp(
      0,
      1
    )

    .rename(
      'BaseLikelihood'
    );


  // ==========================================================================
  // PENALIZACIÓN AGRÍCOLA
  // ==========================================================================

  var agriculturePenalty =
    agricultureScore

    .multiply(
      0.45
    )

    .multiply(

      ee.Image(1)

      .subtract(
        enhancedEvidence
      )

    );


  var cropFrequencyPenalty =
    cropFrequency

    .multiply(
      0.20
    )

    .multiply(

      ee.Image(1)

      .subtract(
        anomalyEvidence
      )

    );


  var temporalVariability =
    nbrStd

    .add(
      ndviStd
    )

    .divide(2)

    .clamp(
      0,
      0.30
    )

    .divide(
      0.30
    );


  var variabilityPenalty =
    temporalVariability

    .multiply(
      agricultureScore
    )

    .multiply(
      0.15
    );


  var cleanedLikelihood =
    baseLikelihood

    .subtract(
      agriculturePenalty
    )

    .subtract(
      cropFrequencyPenalty
    )

    .subtract(
      variabilityPenalty
    )

    .clamp(
      0,
      1
    )

    .rename(
      'CleanedBurnLikelihood'
    );


  // ==========================================================================
  // EXCEPCIÓN QUEMA AGRÍCOLA
  // ==========================================================================

  var agriculturalBurnAccepted =
    agricultureStrong

    .and(
      baseLikelihood.gt(0.78)
    )

    .and(
      enhancedEvidence.gt(0.72)
    )

    .and(
      nbrChangeZ.gt(2.5)
    )

    .and(

      viirsPriorZone
      .eq(1)

      .or(
        enhancedEvidence.gt(0.87)
      )

    )

    .rename(
      'AgriculturalBurnAccepted'
    );


  cleanedLikelihood =
    cleanedLikelihood

    .where(

      agriculturalBurnAccepted,

      baseLikelihood
      .max(
        ee.Image.constant(0.72)
      )

    )

    .rename(
      'CleanedBurnLikelihood'
    );


  // ==========================================================================
  // PROBABILIDAD FINAL
  // ==========================================================================

  var wildfireValidSurface =
    agricultureVeryStrong

    .not()

    .or(
      agriculturalBurnAccepted
    );


  var wildfireLikelihood =
    cleanedLikelihood

    .updateMask(
      wildfireValidSurface
    )

    .rename(
      'WildfireLikelihood'
    );


  // ==========================================================================
  // MÁSCARAS LIMPIAS
  // ==========================================================================

  var burn035 =
    cleanProbabilityMask(
      wildfireLikelihood,
      0.35,
      MIN_CONNECTED_PIXELS
    )
    .rename(
      'Burn035'
    );


  var burn050 =
    cleanProbabilityMask(
      wildfireLikelihood,
      0.50,
      MIN_CONNECTED_PIXELS
    )
    .rename(
      'Burn050'
    );


  var burn060 =
    cleanProbabilityMask(
      wildfireLikelihood,
      0.60,
      MIN_CONNECTED_PIXELS
    )
    .rename(
      'Burn060'
    );


  var burn072 =
    cleanProbabilityMask(
      wildfireLikelihood,
      0.72,
      MIN_CONNECTED_PIXELS
    )
    .rename(
      'Burn072'
    );


  var burn085 =
    cleanProbabilityMask(
      wildfireLikelihood,
      0.85,
      MIN_CONNECTED_PIXELS
    )
    .rename(
      'Burn085'
    );


  // ==========================================================================
  // ESTADÍSTICAS DE ÁREA
  // ==========================================================================

  var pixelHa =
    ee.Image.pixelArea()

    .divide(
      10000
    );


  var areaStack =
    ee.Image.cat([

      pixelHa
      .updateMask(
        burn035
      )
      .rename(
        'wf035'
      ),

      pixelHa
      .updateMask(
        burn050
      )
      .rename(
        'wf050'
      ),

      pixelHa
      .updateMask(
        burn060
      )
      .rename(
        'wf060'
      ),

      pixelHa
      .updateMask(
        burn072
      )
      .rename(
        'wf072'
      ),

      pixelHa
      .updateMask(
        burn085
      )
      .rename(
        'wf085'
      )

    ]);


  var areaStatistics =
    areaStack

    .reduceRegion({

      reducer:
        ee.Reducer.sum(),

      geometry:
        aoi,

      scale:
        20,

      maxPixels:
        1e9,

      tileScale:
        8

    });


  return {

    pre:
      pre,

    post:
      post,

    dNBR:
      dNBR,

    spectralEvidence:
      spectralEvidence,

    enhancedEvidence:
      enhancedEvidence,

    cropProbability:
      cropProbability,

    cropFrequency:
      cropFrequency,

    agricultureScore:
      agricultureScore,

    viirs:
      viirsFire,

    viirsPoints:
      viirsPoints,

    rfLikelihood:
      rfLikelihood,

    observationQuality:
      observationQuality,

    wildfireLikelihood:
      wildfireLikelihood,

    burn035:
      burn035,

    burn050:
      burn050,

    burn060:
      burn060,

    burn072:
      burn072,

    burn085:
      burn085,

    areaStatistics:
      areaStatistics

  };
}


// ============================================================================
// 12. INTERFAZ
// ============================================================================

ui.root.clear();


// ============================================================================
// MAPA
// ============================================================================

var appMap =
  ui.Map();


appMap.setOptions(
  'HYBRID'
);


appMap.setControlVisibility({

  zoomControl:
    true,

  mapTypeControl:
    true,

  scaleControl:
    true,

  fullscreenControl:
    true,

  drawingToolsControl:
    false,

  layerList:
    true

});


// ============================================================================
// PANEL
// ============================================================================

var panel =
  ui.Panel({

    style: {

      width:
        '420px',

      padding:
        '14px'

    }

  });


// ============================================================================
// TÍTULO
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Evaluación de incendios forestales',

    style: {

      fontSize:
        '22px',

      fontWeight:
        'bold',

      margin:
        '0 0 2px 0'

    }

  })

);


panel.add(

  ui.Label({

    value:
      'Sentinel-2 + VIIRS · estimación preliminar de áreas afectadas',

    style: {

      fontSize:
        '11px',

      color:
        '#666666',

      margin:
        '0 0 14px 0'

    }

  })

);


// ============================================================================
// DEPARTAMENTO
// ============================================================================

panel.add(

  ui.Label(
    'Departamento',
    {
      fontWeight:
        'bold'
    }
  )

);


var departmentSelect =
  ui.Select({

    style: {

      stretch:
        'horizontal'

    }

  });


panel.add(
  departmentSelect
);


// ============================================================================
// MUNICIPIO
// ============================================================================

panel.add(

  ui.Label(
    'Municipio',
    {

      fontWeight:
        'bold',

      margin:
        '11px 0 3px 0'

    }
  )

);


var municipalitySelect =
  ui.Select({

    style: {

      stretch:
        'horizontal'

    }

  });


panel.add(
  municipalitySelect
);


// ============================================================================
// FECHA INICIO
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Fecha aproximada de inicio',

    style: {

      fontWeight:
        'bold',

      margin:
        '13px 0 3px 0'

    }

  })

);


var fireDateSlider =
  ui.DateSlider({

    start:
      DATE_START,

    end:
      DATE_END,

    value:
      DEFAULT_FIRE_DATE,

    period:
      1,

    style: {

      stretch:
        'horizontal'

    }

  });


panel.add(
  fireDateSlider
);


var fireDateLabel =
  ui.Label({

    value:
      'Seleccionada: '
      + DEFAULT_FIRE_DATE,

    style: {

      fontSize:
        '10px',

      color:
        '#666666'

    }

  });


panel.add(
  fireDateLabel
);


// ============================================================================
// FECHA FINAL
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Fecha final del análisis',

    style: {

      fontWeight:
        'bold',

      margin:
        '13px 0 3px 0'

    }

  })

);


var endDateSlider =
  ui.DateSlider({

    start:
      DATE_START,

    end:
      DATE_END,

    value:
      DEFAULT_END_DATE,

    period:
      1,

    style: {

      stretch:
        'horizontal'

    }

  });


panel.add(
  endDateSlider
);


var endDateLabel =
  ui.Label({

    value:
      'Seleccionada: '
      + DEFAULT_END_DATE,

    style: {

      fontSize:
        '10px',

      color:
        '#666666'

    }

  });


panel.add(
  endDateLabel
);


// ============================================================================
// FUNCIONES FECHA
// ============================================================================

function sliderDate(
  slider
) {

  var range =
    slider.getValue();


  return ee.Date(
    range[0]
  );
}


fireDateSlider.onChange(

  function() {

    sliderDate(
      fireDateSlider
    )

    .format(
      'YYYY-MM-dd'
    )

    .evaluate(

      function(value) {

        if (value) {

          fireDateLabel.setValue(

            'Seleccionada: '
            + value

          );

        }

      }

    );

  }

);


endDateSlider.onChange(

  function() {

    sliderDate(
      endDateSlider
    )

    .format(
      'YYYY-MM-dd'
    )

    .evaluate(

      function(value) {

        if (value) {

          endDateLabel.setValue(

            'Seleccionada: '
            + value

          );

        }

      }

    );

  }

);


// ============================================================================
// BOTÓN
// ============================================================================

var runButton =
  ui.Button({

    label:
      'EJECUTAR ANÁLISIS',

    style: {

      stretch:
        'horizontal',

      fontWeight:
        'bold',

      margin:
        '15px 0 8px 0'

    }

  });


panel.add(
  runButton
);


// ============================================================================
// ESTADO
// ============================================================================

var statusLabel =
  ui.Label({

    value:
      'Seleccione municipio y fechas.',

    style: {

      color:
        '#555555',

      margin:
        '5px 0 11px 0'

    }

  });


panel.add(
  statusLabel
);


// ============================================================================
// DATOS SATELITALES
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Datos satelitales utilizados',

    style: {

      fontWeight:
        'bold',

      fontSize:
        '16px',

      margin:
        '10px 0 5px 0'

    }

  })

);


var preInfo =
  ui.Label(
    'PRE: —'
  );


var postInfo =
  ui.Label(
    'POST: —'
  );


var historyInfo =
  ui.Label(
    'Contexto histórico: —'
  );


panel.add(
  preInfo
);


panel.add(
  postInfo
);


panel.add(
  historyInfo
);


// ============================================================================
// RESULTADOS DE ÁREA
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Área potencialmente afectada',

    style: {

      fontWeight:
        'bold',

      fontSize:
        '16px',

      margin:
        '15px 0 5px 0'

    }

  })

);


var area035 =
  ui.Label(
    'Posible ≥ 0.35: —'
  );


var area050 =
  ui.Label(
    'Probable ≥ 0.50: —'
  );


var area060 =
  ui.Label(
    'Moderada-alta ≥ 0.60: —'
  );


var area072 =
  ui.Label(
    'Alta confianza ≥ 0.72: —'
  );


var area085 =
  ui.Label(
    'Muy alta confianza ≥ 0.85: —'
  );


panel.add(area035);
panel.add(area050);
panel.add(area060);
panel.add(area072);
panel.add(area085);


// ============================================================================
// UMBRAL INTERACTIVO
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Umbral de exploración',

    style: {

      fontWeight:
        'bold',

      margin:
        '15px 0 3px 0'

    }

  })

);


var thresholdSlider =
  ui.Slider({

    min:
      0.35,

    max:
      0.85,

    value:
      0.50,

    step:
      0.01,

    style: {

      stretch:
        'horizontal'

    }

  });


panel.add(
  thresholdSlider
);


var thresholdLabel =
  ui.Label(
    'Umbral: 0.50'
  );


panel.add(
  thresholdLabel
);


// ============================================================================
// GUÍA RÁPIDA
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Guía rápida de las capas',

    style: {

      fontWeight:
        'bold',

      fontSize:
        '15px',

      margin:
        '18px 0 5px 0'

    }

  })

);


function helpLabel(text) {

  return ui.Label({

    value:
      text,

    style: {

      fontSize:
        '10px',

      color:
        '#555555',

      margin:
        '2px 0'

    }

  });

}


panel.add(
  helpLabel(
    '01 POST: imagen posterior usada para detectar los cambios.'
  )
);


panel.add(
  helpLabel(
    '02 PRE: condición de referencia antes del incendio.'
  )
);


panel.add(
  helpLabel(
    '03 dNBR: cambio espectral asociado a pérdida de vegetación/quema.'
  )
);


panel.add(
  helpLabel(
    '04 Evidencia espectral: combinación de varios índices de quema.'
  )
);


panel.add(
  helpLabel(
    '05 Probabilidad relativa: fuerza de la evidencia de quema entre 0 y 1.'
  )
);


panel.add(
  helpLabel(
    '06 Área probable: delimitación limpia con evidencia ≥ 0.50.'
  )
);


panel.add(
  helpLabel(
    '07 Alta confianza: zonas con evidencia fuerte ≥ 0.72.'
  )
);


panel.add(
  helpLabel(
    '08 VIIRS: focos térmicos detectados por satélite.'
  )
);


panel.add(
  helpLabel(
    '09 Agricultura: zonas agrícolas usadas para reducir falsos positivos.'
  )
);


panel.add(
  helpLabel(
    '10 Calidad: disponibilidad relativa de observaciones PRE y POST.'
  )
);


// ============================================================================
// ADVERTENCIA
// ============================================================================

panel.add(

  ui.Label({

    value:
      'Estimación automatizada preliminar. '
      + 'Los resultados representan evidencia satelital compatible con '
      + 'cambios asociados a incendios y no constituyen un perímetro '
      + 'oficial validado.',

    style: {

      fontSize:
        '9px',

      color:
        '#777777',

      margin:
        '16px 0 5px 0'

    }

  })

);


// ============================================================================
// ESTADO DE LA APP
// ============================================================================

var currentResult =
  null;


var currentBoundary =
  null;


// ============================================================================
// DEPARTAMENTOS
// ============================================================================

municipalities

.aggregate_array(
  DEPARTMENT_FIELD
)

.distinct()

.sort()

.evaluate(

  function(values) {

    if (!values) {
      return;
    }


    departmentSelect
    .items()
    .reset(
      values
    );


    departmentSelect
    .setValue(
      DEFAULT_DEPARTMENT
    );

  }

);


// ============================================================================
// MUNICIPIOS
// ============================================================================

function updateMunicipalities(
  department
) {

  municipalities

  .filter(

    ee.Filter.eq(
      DEPARTMENT_FIELD,
      department
    )

  )

  .aggregate_array(
    MUNICIPALITY_FIELD
  )

  .distinct()

  .sort()

  .evaluate(

    function(values) {

      if (!values) {

        statusLabel.setValue(
          'No fue posible cargar los municipios.'
        );

        return;
      }


      municipalitySelect
      .items()
      .reset(
        values
      );


      if (

        department ===
        DEFAULT_DEPARTMENT

        &&

        values.indexOf(
          DEFAULT_MUNICIPALITY
        ) >= 0

      ) {

        municipalitySelect
        .setValue(
          DEFAULT_MUNICIPALITY
        );

      }

      else if (
        values.length > 0
      ) {

        municipalitySelect
        .setValue(
          values[0]
        );

      }


      statusLabel.setValue(
        'Listo.'
      );

    }

  );

}


departmentSelect.onChange(

  function(value) {

    updateMunicipalities(
      value
    );

  }

);


// ============================================================================
// FORMATO DE ÁREA
// ============================================================================

function formatArea(
  value
) {

  if (

    value === undefined

    ||

    value === null

  ) {

    return 'Sin datos';

  }


  return Math.round(
    value
  )

  .toLocaleString()

  + ' ha';
}


// ============================================================================
// RESET
// ============================================================================

function resetResults() {

  area035.setValue(
    'Posible ≥ 0.35: —'
  );


  area050.setValue(
    'Probable ≥ 0.50: —'
  );


  area060.setValue(
    'Moderada-alta ≥ 0.60: —'
  );


  area072.setValue(
    'Alta confianza ≥ 0.72: —'
  );


  area085.setValue(
    'Muy alta confianza ≥ 0.85: —'
  );

}


// ============================================================================
// DIBUJAR RESULTADOS
// ============================================================================

function drawResult(
  threshold
) {

  if (
    currentResult === null
  ) {

    return;

  }


  thresholdLabel.setValue(

    'Umbral: '
    + threshold.toFixed(2)

  );


  appMap
  .layers()
  .reset([]);


  // ==========================================================================
  // 01 POST
  // ==========================================================================

  appMap.addLayer(

    currentResult.post,

    {

      bands: [
        'B12',
        'B8A',
        'B4'
      ],

      min:
        0.02,

      max:
        0.40

    },

    '01 Imagen posterior al incendio',

    true

  );


  // ==========================================================================
  // 02 PRE
  // ==========================================================================

  appMap.addLayer(

    currentResult.pre,

    {

      bands: [
        'B12',
        'B8A',
        'B4'
      ],

      min:
        0.02,

      max:
        0.40

    },

    '02 Imagen previa al incendio',

    false

  );


  // ==========================================================================
  // 03 dNBR
  // ==========================================================================

  appMap.addLayer(

    currentResult.dNBR,

    {

      min:
        -0.20,

      max:
        0.70,

      palette: [

        '2166AC',
        'FFFFFF',
        'FFFF00',
        'FF8C00',
        '8B0000'

      ]

    },

    '03 Cambio espectral dNBR',

    false

  );


  // ==========================================================================
  // 04 EVIDENCIA ESPECTRAL
  // ==========================================================================

  appMap.addLayer(

    currentResult
    .spectralEvidence,

    {

      min:
        0,

      max:
        1,

      palette: [

        '000080',
        '00FFFF',
        'FFFF00',
        'FF8C00',
        '8B0000'

      ]

    },

    '04 Evidencia espectral de quema',

    false

  );


  // ==========================================================================
  // 05 PROBABILIDAD
  // ==========================================================================

  appMap.addLayer(

    currentResult
    .wildfireLikelihood,

    {

      min:
        0,

      max:
        1,

      palette: [

        '000080',
        '00FFFF',
        'FFFF00',
        'FF8C00',
        '8B0000'

      ]

    },

    '05 Probabilidad relativa de quema',

    false

  );


  // ==========================================================================
  // 06 ÁREA PROBABLE
  // ==========================================================================

  appMap.addLayer(

    currentResult
    .burn050,

    {

      palette: [
        'FF0000'
      ]

    },

    '06 Área probable afectada ≥ 0.50',

    true

  );


  // ==========================================================================
  // 07 ALTA CONFIANZA
  // ==========================================================================

  appMap.addLayer(

    currentResult
    .burn072,

    {

      palette: [
        '8B0000'
      ]

    },

    '07 Área de alta confianza ≥ 0.72',

    false

  );


  // ==========================================================================
  // 08 VIIRS
  // ==========================================================================

  appMap.addLayer(

    currentResult.viirs,

    {

      palette: [
        '00FFFF'
      ]

    },

    '08 Focos activos VIIRS',

    false

  );


  // ==========================================================================
  // 09 AGRICULTURA
  // ==========================================================================

  appMap.addLayer(

    currentResult
    .agricultureScore,

    {

      min:
        0,

      max:
        1,

      palette: [

        'FFFFFF',
        'FFFF00',
        'FF00FF'

      ]

    },

    '09 Evidencia agrícola',

    false

  );


  // ==========================================================================
  // 10 CALIDAD
  // ==========================================================================

  appMap.addLayer(

    currentResult
    .observationQuality,

    {

      min:
        0,

      max:
        1,

      palette: [

        'FF0000',
        'FFFF00',
        '00FF00'

      ]

    },

    '10 Calidad de observación',

    false

  );


  // ==========================================================================
  // 11 UMBRAL INTERACTIVO
  // ==========================================================================

  var interactiveMask =
    cleanProbabilityMask(

      currentResult
      .wildfireLikelihood,

      threshold,

      MIN_CONNECTED_PIXELS

    );


  appMap.addLayer(

    interactiveMask,

    {

      palette: [
        'FF4500'
      ]

    },

    '11 Umbral exploratorio ≥ '
    + threshold.toFixed(2),

    false

  );


  // ==========================================================================
  // LÍMITE MUNICIPAL
  // ==========================================================================

  appMap.addLayer(

    currentBoundary.style({

      color:
        'FFFFFF',

      fillColor:
        '00000000',

      width:
        2

    }),

    {},

    'Límite municipal',

    true

  );

}


// ============================================================================
// CAMBIO DE UMBRAL
// ============================================================================

thresholdSlider.onChange(

  function(value) {

    if (
      currentResult !== null
    ) {

      drawResult(
        value
      );

    }

  }

);


// ============================================================================
// EJECUTAR
// ============================================================================

runButton.onClick(

  function() {

    resetResults();


    currentResult =
      null;


    runButton.setDisabled(
      true
    );


    statusLabel.setValue(
      'Verificando imágenes disponibles...'
    );


    var department =
      departmentSelect.getValue();


    var municipality =
      municipalitySelect.getValue();


    if (
      !department ||
      !municipality
    ) {

      statusLabel.setValue(
        'Seleccione departamento y municipio.'
      );


      runButton.setDisabled(
        false
      );


      return;
    }


    var fireDate =
      sliderDate(
        fireDateSlider
      );


    var analysisEnd =
      sliderDate(
        endDateSlider
      );


    currentBoundary =
      municipalities

      .filter(

        ee.Filter.eq(
          DEPARTMENT_FIELD,
          department
        )

      )

      .filter(

        ee.Filter.eq(
          MUNICIPALITY_FIELD,
          municipality
        )

      );


    var aoi =
      currentBoundary.geometry();


    appMap.centerObject(
      currentBoundary,
      10
    );


    appMap
    .layers()
    .reset([]);


    appMap.addLayer(

      currentBoundary.style({

        color:
          'FFFFFF',

        fillColor:
          '00000000',

        width:
          2

      }),

      {},

      'Límite municipal',

      true

    );


    // ========================================================================
    // VALIDAR FECHAS
    // ========================================================================

    ee.Dictionary({

      fire:
        fireDate.millis(),

      end:
        analysisEnd.millis()

    })

    .evaluate(

      function(
        dateInfo,
        dateError
      ) {

        if (
          dateError ||
          !dateInfo
        ) {

          statusLabel.setValue(
            'Error al validar las fechas.'
          );


          runButton.setDisabled(
            false
          );


          return;
        }


        if (
          dateInfo.end <
          dateInfo.fire
        ) {

          statusLabel.setValue(
            'La fecha final debe ser posterior o igual a la fecha inicial.'
          );


          runButton.setDisabled(
            false
          );


          return;
        }


        // ====================================================================
        // DISPONIBILIDAD
        // ====================================================================

        var availability =
          getInputAvailability(

            aoi,
            fireDate,
            analysisEnd

          );


        availability.evaluate(

          function(
            info,
            inputError
          ) {

            if (
              inputError
            ) {

              statusLabel.setValue(

                'Error consultando Sentinel-2: '
                + inputError

              );


              runButton.setDisabled(
                false
              );


              return;
            }


            if (
              !info
            ) {

              statusLabel.setValue(
                'No se recibió información de las imágenes.'
              );


              runButton.setDisabled(
                false
              );


              return;
            }


            // ================================================================
            // INFORMACIÓN
            // ================================================================

            preInfo.setValue(

              'PRE: '
              + info.preStart
              + ' → '
              + info.preEnd
              + ' | '
              + info.preScenes
              + ' imágenes S2'

            );


            postInfo.setValue(

              'POST: '
              + info.postStart
              + ' → '
              + info.postEnd
              + ' | '
              + info.postScenes
              + ' imágenes S2'

            );


            historyInfo.setValue(

              'Contexto histórico: '
              + info.historyStart
              + ' → '
              + info.historyEnd
              + ' | '
              + info.historyScenes
              + ' imágenes S2'

            );


            // ================================================================
            // VALIDACIONES
            // ================================================================

            if (
              info.preScenes < 1
            ) {

              statusLabel.setValue(
                'No existen imágenes PRE para el periodo.'
              );


              runButton.setDisabled(
                false
              );


              return;
            }


            if (
              info.postScenes < 1
            ) {

              statusLabel.setValue(

                'No existen imágenes POST. '
                + 'Amplíe la fecha final.'

              );


              runButton.setDisabled(
                false
              );


              return;
            }


            if (
              info.historyScenes < 2
            ) {

              statusLabel.setValue(
                'Contexto histórico insuficiente.'
              );


              runButton.setDisabled(
                false
              );


              return;
            }


            // ================================================================
            // MODELO
            // ================================================================

            statusLabel.setValue(
              'Preparando modelo...'
            );


            currentResult =
              runBurnModel(

                aoi,
                fireDate,
                analysisEnd

              );


            drawResult(
              thresholdSlider.getValue()
            );


            statusLabel.setValue(
              'Calculando áreas delimitadas...'
            );


            // ================================================================
            // ESTADÍSTICAS
            // ================================================================

            currentResult
            .areaStatistics

            .evaluate(

              function(
                stats,
                statsError
              ) {

                if (
                  statsError
                ) {

                  statusLabel.setValue(

                    'Las capas fueron generadas, pero '
                    + 'no fue posible calcular las áreas: '
                    + statsError

                  );


                  runButton.setDisabled(
                    false
                  );


                  return;
                }


                if (
                  !stats
                ) {

                  statusLabel.setValue(

                    'Las capas fueron generadas, '
                    + 'pero no se recibieron estadísticas.'

                  );


                  runButton.setDisabled(
                    false
                  );


                  return;
                }


                area035.setValue(

                  'Posible ≥ 0.35: '
                  + formatArea(
                    stats.wf035
                  )

                );


                area050.setValue(

                  'Probable ≥ 0.50: '
                  + formatArea(
                    stats.wf050
                  )

                );


                area060.setValue(

                  'Moderada-alta ≥ 0.60: '
                  + formatArea(
                    stats.wf060
                  )

                );


                area072.setValue(

                  'Alta confianza ≥ 0.72: '
                  + formatArea(
                    stats.wf072
                  )

                );


                area085.setValue(

                  'Muy alta confianza ≥ 0.85: '
                  + formatArea(
                    stats.wf085
                  )

                );


                statusLabel.setValue(
                  'Análisis completado.'
                );


                runButton.setDisabled(
                  false
                );

              }

            );

          }

        );

      }

    );

  }

);


// ============================================================================
// LAYOUT
// ============================================================================

var splitPanel =
  ui.SplitPanel({

    firstPanel:
      panel,

    secondPanel:
      appMap,

    orientation:
      'horizontal',

    wipe:
      false,

    style: {

      stretch:
        'both'

    }

  });


ui.root.add(
  splitPanel
);


// ============================================================================
// INICIALIZACIÓN
// ============================================================================

updateMunicipalities(
  DEFAULT_DEPARTMENT
);


// ============================================================================
// FIN FIRE FOREST V7.6
// ============================================================================