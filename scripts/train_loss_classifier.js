// ArborPulse — train our own Random Forest forest-loss screening model.
// Run in Google Earth Engine Code Editor with project composed-arch-476417-e5.
// Labels: Hansen annual tree-cover loss for 2023. Features: Sentinel-2 change
// between January and August 2023. The eastern part of the training area is
// held out for evaluation, preventing neighbouring train/test pixel leakage.
// This model produces a screening label; it does NOT confirm deforestation.

var trainingRegion = ee.Geometry.Rectangle([-62.75, -10.75, -62.25, -10.25]);
var pilotRegion = ee.Geometry.Polygon([
  [[-62.5300, -10.5300], [-62.4700, -10.5300],
   [-62.4700, -10.4700], [-62.5300, -10.4700],
   [-62.5300, -10.5300]]
]);
var labelYear = 2023;
var splitLongitude = -62.50; // west=train; east=test
var bands = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'];

function maskScl(image) {
  var scl = image.select('SCL');
  return image.updateMask(
    scl.neq(1).and(scl.neq(3)).and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10))
  );
}

function composite(year, startMonth, endMonth, region) {
  var start = ee.Date.fromYMD(year, startMonth, 1);
  var end = ee.Date.fromYMD(year, endMonth, 1);
  return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(region).filterDate(start, end).map(maskScl).median().clip(region);
}

function features(year, region) {
  var before = composite(year, 1, 4, region);
  var after = composite(year, 7, 10, region);
  var spectralDelta = after.select(bands).subtract(before.select(bands)).rename(
    bands.map(function(name) { return name + '_delta'; })
  );
  var ndviDelta = after.normalizedDifference(['B8', 'B4'])
    .subtract(before.normalizedDifference(['B8', 'B4'])).rename('NDVI_delta');
  var nbrDelta = after.normalizedDifference(['B8', 'B12'])
    .subtract(before.normalizedDifference(['B8', 'B12'])).rename('NBR_delta');
  return spectralDelta.addBands([ndviDelta, nbrDelta]);
}

var predictorImage = features(labelYear, trainingRegion);
var label = ee.Image('UMD/hansen/global_forest_change_2025_v1_13')
  .select('lossyear').eq(labelYear - 2000).rename('loss').toByte();
var input = predictorImage.addBands(label);
var predictors = predictorImage.bandNames();

var west = ee.Geometry.Rectangle([-62.75, -10.75, splitLongitude, -10.25]);
var east = ee.Geometry.Rectangle([splitLongitude, -10.75, -62.25, -10.25]);

// Balanced class samples prevent the model from learning only "no loss".
var trainSamples = input.stratifiedSample({
  numPoints: 1500, classBand: 'loss', region: west, scale: 20, seed: 42, geometries: false
});
var testSamples = input.stratifiedSample({
  numPoints: 1000, classBand: 'loss', region: east, scale: 20, seed: 99, geometries: false
});

var classifier = ee.Classifier.smileRandomForest({
  numberOfTrees: 100, minLeafPopulation: 5, bagFraction: 0.7, seed: 42
}).train({features: trainSamples, classProperty: 'loss', inputProperties: predictors});

var evaluated = testSamples.classify(classifier);
var matrix = evaluated.errorMatrix('loss', 'classification');
print('Model configuration', classifier.explain());
print('Spatial hold-out confusion matrix', matrix);
print('Spatial hold-out overall accuracy', matrix.accuracy());
print('Spatial hold-out producer accuracy (recall)', matrix.producersAccuracy());
print('Spatial hold-out consumer accuracy (precision)', matrix.consumersAccuracy());
print('Spatial hold-out F1', matrix.fscore());

// Apply the model to the ArborPulse pilot comparison. This is a 2025 model
// screening result, not an independently validated deforestation incident.
var pilotFeatures = features(2025, pilotRegion);
var predictedLoss = pilotFeatures.classify(classifier).selfMask();
Map.centerObject(pilotRegion, 12);
Map.addLayer(predictedLoss, {palette: ['#d73027']}, 'Our RF: predicted loss review pixels');
Map.addLayer(pilotRegion, {color: 'white'}, 'ArborPulse pilot boundary', false);
Map.addLayer(label.selfMask(), {palette: ['#542788']}, 'Training labels: Hansen 2023 loss', false);

print('Training sample count', trainSamples.size());
print('Testing sample count', testSamples.size());

// New Code Editor layouts can hide the Console. Show the essential model
// evaluation in the map itself, so it is visible during the demo.
var metricsPanel = ui.Panel({
  style: {
    position: 'bottom-left', padding: '8px', width: '310px',
    backgroundColor: 'white'
  }
});
metricsPanel.add(ui.Label({value: 'ArborPulse RF model evaluation', style: {fontWeight: 'bold'}}));
metricsPanel.add(ui.Label('Spatial hold-out: west = training, east = testing'));

function addMetric(name, serverValue) {
  var label = ui.Label(name + ': calculating…');
  metricsPanel.add(label);
  serverValue.evaluate(function(value) {
    label.setValue(name + ': ' + JSON.stringify(value));
  });
}

addMetric('Overall accuracy', matrix.accuracy());
addMetric('Precision by class [no-loss, loss]', matrix.consumersAccuracy());
addMetric('Recall by class [no-loss, loss]', matrix.producersAccuracy());
addMetric('F1 by class [no-loss, loss]', matrix.fscore());
addMetric('Training samples', trainSamples.size());
addMetric('Testing samples', testSamples.size());
Map.add(metricsPanel);
