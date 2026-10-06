"""Dynamic pseudo-supervised sampling and Random Forest (V7.6).

No external polygons are used. Samples are generated per run from seeds.
"""
from __future__ import annotations

import ee

from .config import (
    N_NEGATIVE_SAMPLES, N_POSITIVE_SAMPLES, N_TREES, NEGATIVE_SAMPLE_SEED,
    POSITIVE_SAMPLE_SEED, RF_BAG_FRACTION, RF_MIN_LEAF_POPULATION, RF_SEED,
    RF_VARIABLES_PER_SPLIT, SAMPLE_SCALE, SAMPLE_TILE_SCALE,
)


def sample_training(features: ee.Image, positive_seed: ee.Image, negative_seed: ee.Image,
                    aoi: ee.Geometry) -> dict[str, ee.FeatureCollection]:
    """Sample positives (class 1) and negatives (class 0) and merge them.

    numPixels is an approximate request; masked pixels are dropped, so real
    counts can be lower. Use sample_counts() to obtain the real counts.
    """
    positive_label = positive_seed.multiply(0).add(1).rename('class')
    negative_label = negative_seed.multiply(0).rename('class')
    positive = (features.addBands(positive_label).updateMask(positive_seed)
                .sample(region=aoi, scale=SAMPLE_SCALE, numPixels=N_POSITIVE_SAMPLES,
                        seed=POSITIVE_SAMPLE_SEED, geometries=False,
                        tileScale=SAMPLE_TILE_SCALE))
    negative = (features.addBands(negative_label).updateMask(negative_seed)
                .sample(region=aoi, scale=SAMPLE_SCALE, numPixels=N_NEGATIVE_SAMPLES,
                        seed=NEGATIVE_SAMPLE_SEED, geometries=False,
                        tileScale=SAMPLE_TILE_SCALE))
    return {'positive': positive, 'negative': negative, 'training': positive.merge(negative)}


def sample_counts(samples: dict[str, ee.FeatureCollection]) -> ee.Dictionary:
    """Deferred actual sample counts: {'positive': n, 'negative': m}."""
    return ee.Dictionary({'positive': samples['positive'].size(),
                          'negative': samples['negative'].size()})


def train_random_forest(training: ee.FeatureCollection, predictors: ee.List) -> ee.Classifier:
    """smileRandomForest, 150 trees, PROBABILITY output (V7.6 configuration)."""
    return (ee.Classifier.smileRandomForest(
                numberOfTrees=N_TREES,
                variablesPerSplit=RF_VARIABLES_PER_SPLIT,
                minLeafPopulation=RF_MIN_LEAF_POPULATION,
                bagFraction=RF_BAG_FRACTION,
                seed=RF_SEED)
            .setOutputMode('PROBABILITY')
            .train(features=training, classProperty='class', inputProperties=predictors))


def classify_random_forest(features: ee.Image, classifier: ee.Classifier) -> ee.Image:
    return features.classify(classifier).rename('RFLikelihood')
