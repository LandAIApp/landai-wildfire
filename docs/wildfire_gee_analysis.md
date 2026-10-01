He revisado el script completo **FIRE FOREST COLOMBIA V7.6** como implementación de referencia. La conclusión principal es que no se trata de una simple clasificación de dNBR: es un flujo **pseudo-supervisado híbrido** que combina cambios espectrales PRE/POST, anomalía respecto al histórico, información agrícola, focos VIIRS, un Random Forest entrenado dinámicamente y reglas posteriores para construir una probabilidad relativa de quema. Eso coincide con la intención declarada al inicio del propio script. Texto pegado

No propongo todavía cambios algorítmicos ni código Python. Lo siguiente debe considerarse la **especificación técnica de referencia V7.6** para la migración.

# 1. Datasets utilizados

| Dataset | ID Earth Engine | Uso |
|---|---|---|
| Sentinel-2 Surface Reflectance Harmonized | `COPERNICUS/S2_SR_HARMONIZED` | Imágenes PRE, POST e históricas |
| Cloud Score+ Sentinel-2 Harmonized | `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` | Máscara de claridad mediante `cs_cdf` |
| ESA WorldCover 2021 v200 | `ESA/WorldCover/v200` | Agricultura, agua y urbano |
| Dynamic World | `GOOGLE/DYNAMICWORLD/V1` | Probabilidad y frecuencia histórica de cultivos |
| VIIRS S-NPP Collection 2 | `NASA/LANCE/SNPP_VIIRS/C2` | Evidencia térmica |
| VIIRS NOAA-20 Collection 2 | `NASA/LANCE/NOAA20_VIIRS/C2` | Evidencia térmica |

Sentinel-2 y Cloud Score+ se enlazan con `linkCollection(..., ['cs_cdf'])`. WorldCover usa únicamente la primera imagen y la banda `Map`. Texto pegado

---

# 2. Assets privados

Solo se identifica un asset privado:

`users/maikolzaraza07/mpios`

Tipo:

`ee.FeatureCollection`

Campos utilizados:

- `ADM1_ES`: departamento.
- `ADM2_ES`: municipio.
- `ADM2_PCODE`: declarado como código municipal, pero **no se utiliza posteriormente en el algoritmo**.

El asset proporciona tanto los selectores administrativos de la interfaz como la geometría AOI del análisis. Texto pegado

No existen assets privados de entrenamiento.

Esto es importante: **el Random Forest no se entrena con los 278 polígonos de validación que se manejaron en otras fases del proyecto**. En esta V7.6 el entrenamiento se construye automáticamente en cada ejecución mediante semillas positivas y negativas.

---

# 3. Bandas empleadas

## Sentinel-2

Bandas espectrales:

- `B4` — rojo.
- `B5` — red edge.
- `B6` — red edge.
- `B7` — red edge.
- `B8` — NIR.
- `B8A` — narrow NIR.
- `B11` — SWIR1.
- `B12` — SWIR2.

Bandas auxiliares:

- `SCL`.
- `CLOUDY_PIXEL_PERCENTAGE` como propiedad de imagen.
- `cs_cdf`, añadida mediante Cloud Score+.

Las ocho bandas espectrales anteriores participan en los índices; el conjunto de predictores del Random Forest utiliza directamente B4, B5, B8A, B11 y B12 PRE/POST, además de índices y variables derivadas. Texto pegado

## Dynamic World

- `crops`.

## WorldCover

- `Map`.

Clases explícitamente utilizadas:

- `40`: cultivo.
- `50`: construido.
- `80`: agua.

## VIIRS

- `confidence`.

---

# 4. Índices calculados

El modelo calcula cinco índices espectrales principales y una variable auxiliar para el composite POST.

### NBR

\[
NBR=\frac{B8A-B12}{B8A+B12}
\]

### BurnNBR

\[
BurnNBR=\frac{B12-B8A}{B12+B8A}
\]

Es esencialmente el NBR invertido y **no funciona como predictor independiente**. Su finalidad es elegir mediante `qualityMosaic()` la observación POST con mayor señal compatible con quema.

### NBR2

La implementación concreta es:

\[
NBR2=\frac{B12-B11}{B12+B11}
\]

### MIRBI

\[
MIRBI=10B12-9.8B11+2
\]

### NDVI

\[
NDVI=\frac{B8-B4}{B8+B4}
\]

### BAIS2

Se implementa exactamente mediante:

\[
term1 =
1-\sqrt{\max\left(\frac{B6B7B8A}{\max(B4,\epsilon)},0\right)}
\]

\[
term2 =
\frac{B12-B8A}
{\sqrt{\max(B12+B8A,\epsilon)}}+1
\]

\[
BAIS2=term1\times term2
\]

con:

\[
\epsilon=0.0001
\]

El histórico vuelve a calcular solamente NBR y NDVI. Texto pegado

---

# 5. Ventanas temporales

Sea `fireDate` la fecha aproximada de inicio del incendio.

### PRE

Inicio:

`fireDate - 90 días`

Fin exclusivo:

`fireDate - 7 días`

Es decir, se deja una separación de aproximadamente una semana respecto al inicio indicado.

### POST

Inicio:

`fireDate`

Fin exclusivo:

`analysisEnd + 1 día`

La adición de un día hace que la fecha final seleccionada por el usuario quede incluida.

### Histórico

Inicio:

`fireDate - 6 meses`

Fin exclusivo:

`fireDate - 15 días`

Por tanto, el histórico evita aproximadamente las dos semanas inmediatamente anteriores al incendio.

Texto pegado

### VIIRS

Tiene su propia ventana:

`fireDate - 10 días` → `POST_END`

Por tanto, incluye evidencia térmica hasta 10 días anterior a la fecha aproximada declarada.

---

# 6. Filtros de nubes

Hay **dos niveles de filtrado**.

### Filtro por escena

PRE:

`CLOUDY_PIXEL_PERCENTAGE < 85`

Histórico:

`CLOUDY_PIXEL_PERCENTAGE < 85`

POST:

`CLOUDY_PIXEL_PERCENTAGE < 90`

Son deliberadamente permisivos porque posteriormente existe filtrado píxel a píxel. Texto pegado

### Filtro por píxel — Cloud Score+

Se exige:

`cs_cdf >= 0.55`

### Filtro por SCL

Se eliminan las clases:

`1, 3, 7, 8, 9, 10, 11`

La máscara se aplica antes de calcular los índices.

Posteriormente la imagen completa se divide entre `10000`. Texto pegado

---

# 7. Composites

Aquí existe una diferencia importante entre PRE y POST.

## PRE

```text
preCollection.median()
```

Es decir, se obtiene una mediana temporal.

## POST

```text
postCollection.qualityMosaic('BurnNBR')
```

Para cada píxel se selecciona la observación con el valor más alto de `BurnNBR`.

Por tanto:

**PRE = condición temporal robusta de referencia.**

**POST = observación con mayor señal compatible con quema.**

Esto debe conservarse exactamente en la primera migración porque forma parte de la lógica del algoritmo, no de la interfaz. Texto pegado

---

# 8. Variables PRE y POST

El Random Forest recibe explícitamente:

### PRE

- `pre_B4`
- `pre_B5`
- `pre_B8A`
- `pre_B11`
- `pre_B12`
- `pre_NBR`

### POST

- `post_B4`
- `post_B5`
- `post_B8A`
- `post_B11`
- `post_B12`
- `post_NBR`

Texto pegado

---

# 9. Diferencias calculadas

Existen diez variables principales de cambio.

### Espectrales

- `dB4 = POST B4 − PRE B4`
- `dB5 = POST B5 − PRE B5`
- `dB8A = POST B8A − PRE B8A`
- `dB11 = POST B11 − PRE B11`
- `dB12 = POST B12 − PRE B12`

### Índices

- `dNBR = PRE NBR − POST NBR`
- `dNBR2 = POST NBR2 − PRE NBR2`
- `dMIRBI = POST MIRBI − PRE MIRBI`
- `dNDVI = PRE NDVI − POST NDVI`
- `dBAIS2 = POST BAIS2 − PRE BAIS2`

Las direcciones no son iguales para todos los índices; esto es deliberado para que el aumento de evidencia asociada a quema tienda hacia valores positivos. Texto pegado

---

# 10. Reglas y umbrales

Hay varios niveles distintos de umbrales; no deben confundirse.

## Cloud Score

`CLEAR_THRESHOLD = 0.55`

## Dynamic World

`DW_CROP_PROB_THRESHOLD = 0.40`

## Agricultura

- fuerte: `>= 0.55`
- muy fuerte: `>= 0.70`

## Conectividad

`MIN_CONNECTED_PIXELS = 6`

## Delimitación final

- 0.35
- 0.50
- 0.60
- 0.72
- 0.85

Aunque existen constantes:

- `LOW_THRESHOLD = 0.35`
- `MEDIUM_THRESHOLD = 0.50`
- `HIGH_THRESHOLD = 0.72`

las máscaras finales están escritas nuevamente con valores numéricos explícitos. Es una cuestión de organización del código, no una diferencia algorítmica.

## Evidencias normalizadas

| Evidencia | Low | High |
|---|---:|---:|
| dNBR | 0.08 | 0.50 |
| dMIRBI | 0.03 | 0.45 |
| dNBR2 | 0.01 | 0.20 |
| dNDVI | 0.03 | 0.35 |
| dBAIS2 | 0.05 | 1.50 |
| NBR change Z | 1 | 5 |

La normalización es:

\[
clip\left(\frac{x-low}{high-low},0,1\right)
\]

---

# 11. Modelo de clasificación

Sí existe.

Es:

`ee.Classifier.smileRandomForest`

Configuración exacta:

- árboles: **150**
- `variablesPerSplit: null`
- `minLeafPopulation: 3`
- `bagFraction: 0.65`
- `seed: 2026`
- output: `PROBABILITY`

La salida se denomina:

`RFLikelihood`

Texto pegado

Pero debe remarcarse que no es un Random Forest supervisado convencional con un dataset de verdad terreno permanente.

Es un **Random Forest pseudo-supervisado local**, entrenado de nuevo para el AOI/fecha utilizando píxeles etiquetados automáticamente por reglas.

---

# 12. Datos de entrenamiento

No existe un asset externo de entrenamiento.

Las muestras se generan durante la ejecución.

### Positivas

Máximo solicitado:

`3000`

Seed aleatorio:

`2026`

### Negativas

Máximo solicitado:

`5000`

Seed:

`2027`

### Resolución

`20 m`

### geometries

`false`

### tileScale

`4`

Después:

`training = positiveSamples.merge(negativeSamples)`

Texto pegado

---

# 13. Lógica de semillas positivas

Se unen tres tipos de evidencia.

## A. fireSeed

Debe cumplirse:

- dentro de buffer VIIRS de 700 m;
- `enhancedEvidence > 0.40`;
- `dNBR > 0.08`;
- disponer de PRE y POST.

## B. spectralSeed

Debe cumplirse:

- `enhancedEvidence > 0.72`;
- `nbrChangeZ > 2.3`;
- `dNBR > 0.22`;
- `dMIRBI > 0.06`;
- NO agricultura muy fuerte;
- NO agua;
- NO construido;
- observado.

## C. agriculturalFireSeed

Para permitir incendios reales dentro de agricultura:

- agricultura fuerte;
- VIIRS dentro de 3 km;
- `enhancedEvidence > 0.80`;
- `nbrChangeZ > 3.0`;
- `dNBR > 0.30`;
- `dMIRBI > 0.10`;
- observado.

Finalmente:

`positiveSeed = A OR B OR C`

Texto pegado

---

# 14. Semillas negativas

Se combinan cinco tipos.

### stableNegative

- `dNBR < 0.03`
- `dMIRBI < 0.03`
- observado

### cropHardNegative

- agricultura fuerte
- `cropFrequency > 0.30`
- `nbrChangeZ < 2`
- sin VIIRS en buffer de 3 km
- observado

### veryStrongCropNegative

- agricultura muy fuerte
- `enhancedEvidence < 0.72`
- sin VIIRS en buffer de 700 m
- observado

### seasonalCropNegative

- agricultura fuerte
- `nbrStd > 0.14`
- `ndviStd > 0.14`
- `enhancedEvidence < 0.65`
- sin VIIRS dentro de 3 km
- observado

### surfaceNegative

- agua OR construido
- observado

Finalmente:

`negativeSeed = unión de las cinco condiciones`.

Texto pegado

---

# 15. Contexto histórico y anomalía

El histórico calcula:

- desviación estándar temporal de NBR;
- desviación estándar temporal de NDVI.

Después:

\[
NBR\_change\_z=
\frac{dNBR}{NBR_{std}+0.03}
\]

limitado a:

`[-10, 10]`

No es un z-score estadístico clásico porque no resta una media de cambios históricos; es una **razón normalizada por variabilidad histórica**, denominada en el script `NBR_change_z`.

La evidencia de anomalía se obtiene normalizando ese valor entre 1 y 5.

Texto pegado

---

# 16. Evidencia espectral

Se combinan cinco evidencias normalizadas:

\[
SpectralEvidence =
0.32E_{dNBR}
+0.22E_{MIRBI}
+0.14E_{NBR2}
+0.14E_{NDVI}
+0.18E_{BAIS2}
\]

Los pesos suman 1.

Posteriormente:

\[
EnhancedEvidence =
0.75 \times SpectralEvidence
+
0.25 \times AnomalyEvidence
\]

Por tanto, el histórico interviene en la detección antes incluso de ejecutar el Random Forest.

---

# 17. Tratamiento de cultivos

Es uno de los componentes más elaborados.

## Dynamic World

Primero:

`cropProbability = median(crops)`

Segundo:

para cada imagen:

`cropFlag = crops >= 0.40`

y:

`cropFrequency = mean(cropFlag)`

Esto mide la persistencia de identificación como cultivo a través del histórico.

## WorldCover

`wcCrop = Map == 40`

## AgricultureScore

\[
AgricultureScore =
0.50\,wcCrop+
0.20\,cropProbability+
0.30\,cropFrequency
\]

limitado a `[0,1]`.

Luego:

- `agricultureStrong >= 0.55`
- `agricultureVeryStrong >= 0.70`

Texto pegado

Pero agricultura **no se excluye directamente**. Se utiliza en cuatro lugares diferentes:

1. creación de negativos;
2. creación de una semilla positiva agrícola especial;
3. penalización de probabilidad;
4. máscara final con excepción para incendios agrícolas suficientemente respaldados.

Esto debe conservarse como un subsistema, no convertirse simplemente en un `mask crops`.

---

# 18. Uso de VIIRS

Se combinan:

- S-NPP VIIRS C2;
- NOAA-20 VIIRS C2.

Ventana:

`fireDate - 10 días → analysisEnd incluido`.

Se conserva `confidence`, se hace `unmask(0)`, `toByte()` y posteriormente se toma el máximo temporal.

Un fallback constante cero evita una colección vacía.

Después:

`viirsFire = viirsConfidence >= 1`

Es decir, en esta implementación **cualquier confidence no nulo se interpreta como evidencia VIIRS**.

Los píxeles VIIRS se vectorizan:

- `scale: 375`
- `geometryType: centroid`
- `eightConnected: true`
- `maxPixels: 1e7`
- `tileScale: 4`

A continuación se generan dos buffers:

- **700 m** → `viirsSeedZone`
- **3000 m** → `viirsPriorZone`

Texto pegado

Conceptualmente:

- 700 m = evidencia espacial fuerte para semillas;
- 3 km = evidencia contextual/prior.

---

# 19. Lógica de probabilidad de quema

Este es el núcleo posterior al RF.

## Calidad de observación

Primero:

\[
q_{pre} = \frac{\min(preCount,3)}{3}
\]

\[
q_{post} = \frac{\min(postCount,3)}{3}
\]

\[
ObservationQuality=\sqrt{q_{pre}q_{post}}
\]

Por tanto, tres observaciones válidas PRE y tres POST alcanzan calidad 1.

## Bonus VIIRS

Si el píxel está dentro de `viirsPriorZone`:

`+0.08`

## Penalización de superficie

Si es agua o construido:

`−0.40`

## BaseLikelihood

\[
BaseLikelihood =
0.72\,RFLikelihood
+
0.28\,EnhancedEvidence
+
VIIRSBonus
-
SurfacePenalty
\]

y después se multiplica por:

\[
0.85+0.15\,ObservationQuality
\]

Finalmente se restringe a `[0,1]`.

---

# 20. Penalización agrícola

Se aplican tres penalizaciones.

### AgriculturePenalty

\[
0.45\times AgricultureScore\times(1-EnhancedEvidence)
\]

Cuanto mayor sea la evidencia de incendio, menor es la penalización.

### CropFrequencyPenalty

\[
0.20\times CropFrequency\times(1-AnomalyEvidence)
\]

### VariabilityPenalty

Primero:

\[
TemporalVariability=
\frac{NBR_{std}+NDVI_{std}}2
\]

limitada entre 0 y 0.30 y posteriormente normalizada a 0–1.

Después:

\[
VariabilityPenalty=
TemporalVariability
\times AgricultureScore
\times0.15
\]

Finalmente:

\[
CleanedLikelihood =
BaseLikelihood
-
AgriculturePenalty
-
CropFrequencyPenalty
-
VariabilityPenalty
\]

clamp `[0,1]`.

---

# 21. Excepción de quema agrícola

Para no eliminar incendios agrícolas verdaderos existe:

`AgriculturalBurnAccepted`

Debe cumplirse:

- agricultura fuerte;
- `baseLikelihood > 0.78`;
- `enhancedEvidence > 0.72`;
- `nbrChangeZ > 2.5`;
- además:
  - VIIRS dentro de 3 km, **o**
  - `enhancedEvidence > 0.87`.

Cuando se acepta:

```text
CleanedLikelihood =
max(BaseLikelihood, 0.72)
```

en esos píxeles.

Después la superficie válida es:

```text
NOT agricultureVeryStrong
OR agriculturalBurnAccepted
```

Por tanto, agricultura muy fuerte queda enmascarada **salvo cuando existe evidencia suficiente para aceptar una quema agrícola**.

Esta lógica forma parte esencial del modelo final.

---

# 22. Lógica de delimitación final

La imagen continua final es:

`WildfireLikelihood`

Se generan cinco máscaras:

- `Burn035`
- `Burn050`
- `Burn060`
- `Burn072`
- `Burn085`

Cada una ejecuta:

1. `WildfireLikelihood >= threshold`;
2. `selfMask()`;
3. `connectedPixelCount(100, true)`;
4. conservar únicamente componentes con `>= 6 píxeles`.

Texto pegado

La conectividad es de ocho vecinos porque el segundo argumento de `connectedPixelCount` es `true`.

A escala nominal de 20 m usada posteriormente para estadísticas, seis píxeles equivaldrían aproximadamente a 0.24 ha si fueran píxeles de 20 × 20 m, aunque la operación en EE depende de la proyección efectiva de la imagen. Para la especificación de referencia conviene conservar la regla como **6 píxeles conectados**, no traducirla todavía a hectáreas.

---

# 23. Reducers

Se identifican los siguientes.

### `median()`

- PRE Sentinel-2.
- Dynamic World `cropProbability`.

### `qualityMosaic('BurnNBR')`

- POST Sentinel-2.

### `count()`

- observaciones válidas PRE;
- observaciones válidas POST.

### `ee.Reducer.stdDev()`

- NBR histórico;
- NDVI histórico.

### `mean()`

- frecuencia histórica de cultivos.

### `max()`

- confidence VIIRS temporal.

### `reduceToVectors()`

- VIIRS raster → centroides.

### `ee.Reducer.sum()` con `reduceRegion()`

- hectáreas para cinco thresholds.

El cálculo final del área se realiza sobre `pixelArea()/10000` y utiliza `scale=20`, `maxPixels=1e9`, `tileScale=8`. Texto pegado

---

# 24. Escalas

Existen tres escalas explícitas relevantes.

| Operación | Escala |
|---|---:|
| Vectorización VIIRS | 375 m |
| Muestreo RF positivo/negativo | 20 m |
| Estadísticas de superficie | 20 m |

Además:

- `reduceToVectors`: `tileScale=4`
- sampling: `tileScale=4`
- estadísticas: `tileScale=8`

No existe un `reproject()` explícito.

Esto es positivo para la migración: Earth Engine mantiene evaluación diferida de las proyecciones.

---

# 25. Server-side vs client-side

## Server-side

Prácticamente todo el algoritmo científico es server-side:

- `ee.Image`
- `ee.ImageCollection`
- `ee.FeatureCollection`
- `ee.Date`
- filtros
- máscaras
- índices
- composites
- reducers
- Dynamic World
- WorldCover
- VIIRS
- buffers de features
- sampling
- entrenamiento Random Forest
- clasificación
- probabilidad
- máscaras
- estadísticas

La llamada de una función JS mediante `.map()` tampoco significa procesamiento local: esas operaciones construyen el grafo server-side de Earth Engine.

## Client-side

Son client-side:

- variables normales JS de control de UI;
- callbacks;
- `if` después de `.evaluate()`;
- `Math.round`;
- `toLocaleString`;
- `threshold.toFixed(2)`;
- `values.indexOf()`;
- construcción y actualización de widgets;
- `currentResult`;
- `currentBoundary`;
- activar/desactivar botón;
- mostrar textos;
- administración de layers del mapa.

La separación es bastante clara: el algoritmo ya se encuentra mayormente preparado conceptualmente para trasladarse al backend.

---

# 26. `getInfo()` y `.evaluate()`

## `getInfo()`

**No existe ninguna llamada a `getInfo()` en el script.**

Esto es relevante porque evita sincronizaciones bloqueantes directas desde GEE JavaScript.

## `.evaluate()`

Hay **7 llamadas**:

1. etiqueta de fecha inicial;
2. etiqueta de fecha final;
3. cargar departamentos;
4. cargar municipios;
5. validar fireDate/endDate;
6. comprobar disponibilidad de Sentinel-2;
7. obtener estadísticas finales de superficie.

Las primeras cuatro son esencialmente necesidades de la UI. Las últimas tres constituyen cruces explícitos server → client para controlar el flujo de la aplicación.

La validación de fechas, disponibilidad y estadísticas finales se hace mediante callbacks de `.evaluate()`, no mediante `getInfo()`. Texto pegado

---

# 27. Exports

**La V7.6 suministrada no contiene ningún `Export.image`, `Export.table`, `Export.video` ni otro `Export.*`.**

Por tanto, los productos actuales existen únicamente como:

- objetos EE temporales;
- capas de mapa;
- estadísticas mostradas en la interfaz.

La capacidad de descargar GeoTIFF, GeoJSON, SHP, CSV o generar reportes pertenecerá a una fase posterior de Land AI y **no debe interpretarse como comportamiento existente de la implementación de referencia**.

---

# 28. Capas visualizadas

El resultado de `drawResult()` contiene:

| # | Capa | Visible inicialmente |
|---|---|---|
| 01 | Imagen POST B12/B8A/B4 | Sí |
| 02 | Imagen PRE B12/B8A/B4 | No |
| 03 | dNBR | No |
| 04 | SpectralEvidence | No |
| 05 | WildfireLikelihood | No |
| 06 | Burn050 | **Sí** |
| 07 | Burn072 | No |
| 08 | VIIRS | No |
| 09 | AgricultureScore | No |
| 10 | ObservationQuality | No |
| 11 | máscara para threshold interactivo | No |
| — | límite municipal | Sí |

El mapa POST/PRE usa:

- bandas `[B12, B8A, B4]`
- min `0.02`
- max `0.40`.

El dNBR usa visualización de `-0.20 → 0.70`.

La probabilidad y evidencias utilizan `0 → 1`.

---

# 29. Controles UI

La UI GEE contiene:

- mapa `HYBRID`;
- zoom;
- cambio de mapa base;
- escala;
- fullscreen;
- layer list;
- drawing tools desactivado;
- selector de departamento;
- selector de municipio;
- DateSlider para fecha aproximada del incendio;
- DateSlider para fecha final;
- botón `EJECUTAR ANÁLISIS`;
- estado del procesamiento;
- información de imágenes PRE;
- información de imágenes POST;
- información histórica;
- cinco resultados de superficie;
- slider interactivo de threshold `0.35–0.85`;
- paso `0.01`;
- guía de interpretación de capas;
- disclaimer;
- panel izquierdo + mapa mediante `ui.SplitPanel`.

La implementación advierte explícitamente que el resultado es una **estimación automatizada preliminar y no un perímetro oficial validado**. Texto pegado

---

# 30. Validaciones antes de ejecutar

La UI exige:

1. departamento;
2. municipio;
3. `analysisEnd >= fireDate`;
4. al menos 1 escena PRE;
5. al menos 1 escena POST;
6. al menos 2 escenas históricas.

Solo después se llama a:

`runBurnModel()`.

Esto conviene conservar como contrato del backend/API de Land AI, aunque ya no se implemente mediante widgets GEE.

---

# 31. Posibles cuellos de botella

Sin modificar todavía el algoritmo, identifico estos puntos técnicos para la migración.

### A. Entrenamiento RF en cada ejecución

Cada combinación:

`AOI + fireDate + analysisEnd`

vuelve a:

- generar semillas;
- muestrear hasta 8000 píxeles;
- entrenar 150 árboles;
- clasificar toda el área.

Es probablemente uno de los principales costes computacionales.

### B. VIIRS `reduceToVectors()`

Rasterizar → vectorizar → bufferizar → volver a pintar a raster implica:

`Image → FeatureCollection → buffers → Image`.

Para municipios grandes o muchos focos puede incrementar considerablemente el coste.

### C. `qualityMosaic()` POST

Con periodos POST extensos puede requerir evaluar muchas escenas completas.

### D. histórico Sentinel-2

Se procesa hasta seis meses de imágenes, incluyendo:

- máscara;
- NBR;
- NDVI;
- stdDev.

### E. Dynamic World histórico

Es otra colección temporal independiente sobre aproximadamente la misma ventana.

### F. muchos cálculos derivados a 10–20 m

Se mantienen simultáneamente numerosas bandas intermedias y features RF.

### G. `reduceRegion(scale=20)`

Para AOI extensos, cinco superficies son agregadas en una sola operación con hasta `1e9` píxeles.

### H. cinco máscaras finales

Se llama cinco veces a `connectedPixelCount()` sobre la misma probabilidad para thresholds distintos.

### I. slider interactivo

Cada cambio del slider genera otra llamada a `cleanProbabilityMask()`. En GEE Code Editor esto resulta práctico; en una aplicación web externa no conviene necesariamente solicitar un cálculo Earth Engine completo en cada movimiento continuo del slider.

### J. consultas UI secuenciales

El flujo actual realiza varios viajes servidor-cliente mediante `.evaluate()` antes y después del modelo.

Nada de esto implica que deba cambiarse ahora; simplemente son los puntos que habrá que medir en Land AI.

---

# 32. Qué puede migrarse directamente a Earth Engine Python API

La mayor parte del núcleo.

Se puede mantener conceptualmente casi 1:1:

- carga de datasets;
- FeatureCollection municipal;
- `linkCollection`;
- filtrado espacial;
- filtrado temporal;
- Cloud Score+;
- SCL;
- índices;
- `.map()`;
- mediana PRE;
- `qualityMosaic` POST;
- diferencias PRE/POST;
- conteos de observaciones;
- histórico NBR/NDVI;
- reducers `stdDev`;
- Dynamic World;
- WorldCover;
- AgricultureScore;
- VIIRS;
- `reduceToVectors`;
- buffers;
- `paint`;
- semillas positivas;
- semillas negativas;
- construcción de features;
- sampling;
- `smileRandomForest`;
- clasificación;
- ponderación de probabilidades;
- penalización agrícola;
- excepción agrícola;
- conectividad;
- `pixelArea`;
- `reduceRegion`.

La sintaxis cambia de JavaScript a Python, pero **la semántica de Earth Engine puede conservarse**.

---

# 33. Qué pertenece exclusivamente a UI GEE

Debe reemplazarse por Land AI frontend/backend:

- `ui.root`
- `ui.Map`
- `ui.Panel`
- `ui.Label`
- `ui.Select`
- `ui.DateSlider`
- `ui.Slider`
- `ui.Button`
- `ui.SplitPanel`
- `.onChange()`
- `.onClick()`
- `.setValue()`
- `.setDisabled()`
- `Map.addLayer` / `appMap.addLayer`
- `centerObject`
- layer list
- estado `currentResult`
- estado `currentBoundary`
- callbacks de presentación.

En Land AI esto debería convertirse conceptualmente en:

**Frontend → API backend → Earth Engine Python → resultados/metadatos/tile URLs → frontend.**

No hay necesidad de reproducir la UI GEE en Python.

---

# 34. Tabla maestra de especificación

| Componente | Implementación actual | Entrada | Salida | Debe conservarse | Mejora posible |
|---|---|---|---|---|---|
| AOI | asset municipios + ADM1/ADM2 | departamento/municipio | geometría | **Sí** | Separar catálogo administrativo del modelo |
| Ventanas | fechas relativas | fireDate/endDate | PRE/POST/HISTORY | **Sí** | Parametrizarlas posteriormente |
| Sentinel-2 | S2 SR Harmonized | AOI + fechas | colecciones | **Sí** | Cache/metadatos |
| Cloud Score+ | `cs_cdf >= .55` | S2 | píxeles claros | **Sí** | Parametrizable |
| SCL | exclusión clases | S2 | píxeles válidos | **Sí** | Revisar clases en validación futura |
| PRE composite | mediana | PRE Collection | imagen PRE | **Sí** | Evaluar alternativas después |
| POST composite | qualityMosaic BurnNBR | POST Collection | imagen POST | **Sí** | Evaluar sensibilidad después |
| Índices | NBR/NBR2/MIRBI/NDVI/BAIS2 | S2 | bandas índices | **Sí** | Modularización |
| Cambios | PRE/POST differences | composites | d* | **Sí** | Modularización |
| Histórico | stdDev NBR/NDVI | 6 meses S2 | variabilidad | **Sí** | Cache histórico |
| Anomalía | dNBR/(std+.03) | cambio + histórico | NBR_change_z | **Sí** | Revisar estadísticamente más adelante |
| Dynamic World | crops | histórico | prob./frecuencia | **Sí** | Cache |
| WorldCover | clases 40/50/80 | AOI | crop/built/water | **Sí** | Dataset actualizable posteriormente |
| AgricultureScore | 0.5 WC + .2 prob + .3 freq | capas agrícolas | score 0–1 | **Sí** | Calibrar pesos posteriormente |
| VIIRS | SNPP + NOAA20 | fechas/AOI | focos | **Sí** | Optimizar procesamiento |
| VIIRS seed | buffer 700 m | focos | seed zone | **Sí** | Revisar resolución después |
| VIIRS prior | buffer 3000 m | focos | prior zone | **Sí** | Parametrizable |
| SpectralEvidence | combinación ponderada | 5 cambios | 0–1 | **Sí** | Calibrar con validación |
| EnhancedEvidence | 75% spectral + 25% anomaly | evidencias | 0–1 | **Sí** | Calibrar |
| PositiveSeed | 3 reglas | evidencias/VIIRS/agri | etiqueta 1 | **Sí** | Auditar cantidad/calidad |
| NegativeSeed | 5 reglas | estabilidad/agri/surface | etiqueta 0 | **Sí** | Auditar balance |
| Training | sample 3000/5000 | features + seeds | FeatureCollection | **Sí** | Métricas QA |
| Random Forest | 150 árboles | training | RFLikelihood | **Sí** | Persistencia/model versioning futuro |
| ObservationQuality | counts PRE/POST | colecciones | 0–1 | **Sí** | Exponer al usuario |
| BaseLikelihood | RF + evidence + VIIRS − surface | capas | 0–1 | **Sí** | Calibración |
| Agri penalty | 3 penalizaciones | cultivo/histórico | cleaned likelihood | **Sí** | Calibración |
| Agri exception | reglas fuertes | evidencias + VIIRS | aceptación | **Sí** | Exponer bandera QA |
| WildfireLikelihood | likelihood + máscara agrícola | resultados | probabilidad final | **Sí** | Producto raster principal |
| Limpieza espacial | ≥ threshold + ≥6 conectados | likelihood | máscaras | **Sí** | Optimizar multi-threshold |
| Áreas | pixelArea + sum | masks | hectáreas | **Sí** | API estructurada |
| Disponibilidad | scene count | AOI/fechas | conteos | **Sí** | Endpoint previo |
| Visualización | GEE UI | resultados | capas | No como implementación | Tile URLs web |
| Threshold slider | UI 0.35–0.85 | probability | mask | Conservar función | Procesar bajo demanda/caché |
| Estadísticas UI | evaluate + labels | reducer | textos | No como UI | JSON API |
| Exports | inexistentes | — | — | No aplica | Añadir como fase nueva |
| Disclaimer | texto UI | — | aviso | **Sí conceptualmente** | Integrarlo en Land AI |

La regla de migración que usaría sería: **primero reproducir V7.6 exactamente; después crear una V7.6+ donde las mejoras se prueben una por una contra el resultado de referencia.**

---

# 35. División propuesta en funciones Python

Sin escribir todavía el código, sugiero que el núcleo Python quede dividido aproximadamente así:

```text
config/
    WildfireConfig

administrative/
    load_municipalities()
    get_aoi()

dates/
    get_time_windows()

sentinel2/
    get_s2_collection()
    mask_s2()
    add_burn_indices()
    add_history_indices()
    build_pre_collection()
    build_post_collection()
    build_pre_composite()
    build_post_composite()
    get_observation_counts()

changes/
    calculate_spectral_changes()

history/
    build_history_collection()
    calculate_historical_variability()
    calculate_nbr_anomaly()

landcover/
    get_dynamic_world_crops()
    get_worldcover_masks()
    calculate_agriculture_score()

viirs/
    normalize_viirs_confidence()
    get_viirs_collection()
    build_viirs_fire_mask()
    build_viirs_points()
    build_viirs_zones()

evidence/
    scale_01()
    calculate_spectral_evidence()
    calculate_anomaly_evidence()
    calculate_enhanced_evidence()

training/
    create_positive_seeds()
    create_negative_seeds()
    build_predictor_stack()
    sample_training_data()

model/
    train_random_forest()
    classify_random_forest()

probability/
    calculate_observation_quality()
    calculate_base_likelihood()
    calculate_agriculture_penalties()
    apply_agricultural_exception()
    calculate_wildfire_likelihood()

postprocessing/
    clean_probability_mask()
    create_threshold_masks()

statistics/
    calculate_area_statistics()

validation/
    get_input_availability()
    validate_analysis_inputs()

orchestration/
    run_burn_model()
```

## La función orquestadora

`run_burn_model()` debería seguir siendo relativamente pequeña. Su función sería coordinar:

```text
AOI
 ↓
ventanas temporales
 ↓
Sentinel-2 PRE / POST
 ↓
composites
 ↓
cambios espectrales
 ↓
contexto histórico
 ↓
agricultura
 ↓
VIIRS
 ↓
evidencias
 ↓
semillas
 ↓
features
 ↓
Random Forest
 ↓
probabilidad base
 ↓
penalizaciones / excepción agrícola
 ↓
WildfireLikelihood
 ↓
threshold masks
 ↓
estadísticas
```

No debería contener internamente cientos de líneas con toda la matemática.

---

# 36. Contrato de salida recomendado para preservar V7.6

Sin cambiar todavía el algoritmo, la futura función Python principal debería ser capaz de producir conceptualmente el mismo conjunto que devuelve actualmente `runBurnModel()`:

```text
pre
post
dNBR
spectralEvidence
enhancedEvidence
cropProbability
cropFrequency
agricultureScore
viirs
viirsPoints
rfLikelihood
observationQuality
wildfireLikelihood
burn035
burn050
burn060
burn072
burn085
areaStatistics
```

Eso es especialmente importante para la migración porque permite realizar una **comparación capa por capa GEE JavaScript vs Earth Engine Python**. La implementación actual devuelve exactamente esos productos principales. Texto pegado

## Punto crítico para Land AI

Yo trataría **`WildfireLikelihood` como el producto analítico principal**, y `burn035...burn085` como interpretaciones discretas derivadas. Así, Land AI puede conservar toda la información continua 0–1 y permitir posteriormente diferentes thresholds sin volver a entrenar el RF.

Pero eso no supone cambiar V7.6: actualmente ya existe esa imagen continua y las máscaras son derivadas de ella.

En resumen, la arquitectura natural de migración es:

**V7.6 GEE JavaScript = referencia científica → Earth Engine Python = motor analítico equivalente → API Land AI = orquestación → frontend = interacción/visualización.**

El siguiente paso correcto antes de construir la aplicación sería convertir esta especificación en un **“contrato de equivalencia V7.6”**, definiendo para cada función Python sus argumentos, tipo EE de entrada, tipo EE de salida, nombres exactos de bandas y pruebas que permitan demostrar que Python genera los mismos resultados que el script JavaScript.