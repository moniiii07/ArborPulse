// ArborPulse — Rondônia vegetation-change map for Google Earth Engine Code Editor.
// Open https://code.earthengine.google.com/?project=composed-arch-476417-e5,
// paste this script, and click Run. This is a screening map, not a final
// deforestation classification; visually validate hotspots before reporting.

var region = ee.Geometry.Polygon([
  [[-62.5300, -10.5300], [-62.4700, -10.5300],
   [-62.4700, -10.4700], [-62.5300, -10.4700],
   [-62.5300, -10.5300]]
]);

var beforeDate = '2025-01-15';
var afterDate = '2025-08-15';
var searchDays = 7;
var lossThreshold = -0.20; // after NDVI minus before NDVI

function maskScl(image) {
  var scl = image.select('SCL');
  var valid = scl.neq(1)  // saturated / defective
    .and(scl.neq(3))      // cloud shadow
    .and(scl.neq(8))      // cloud, medium probability
    .and(scl.neq(9))      // cloud, high probability
    .and(scl.neq(10));    // cirrus
  return image.updateMask(valid);
}

function bestScene(targetDate) {
  var target = ee.Date(targetDate);
  return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(region)
    .filterDate(target.advance(-searchDays, 'day'), target.advance(searchDays + 1, 'day'))
    .sort('CLOUDY_PIXEL_PERCENTAGE')
    .first();
}

function ndvi(image) {
  return image.normalizedDifference(['B8', 'B4']).rename('NDVI');
}

var before = maskScl(bestScene(beforeDate));
var after = maskScl(bestScene(afterDate));
var beforeNdvi = ndvi(before);
var afterNdvi = ndvi(after);
var ndviDelta = afterNdvi.subtract(beforeNdvi).rename('NDVI_delta');
var likelyLoss = ndviDelta.lte(lossThreshold).selfMask();

var rgb = {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000};
var ndviStyle = {min: 0, max: 1, palette: ['#8c510a', '#f6e8c3', '#1b7837']};
var deltaStyle = {
  min: -0.5, max: 0.5,
  palette: ['#b2182b', '#ef8a62', '#f7f7f7', '#67a9cf', '#2166ac']
};

Map.centerObject(region, 12);
Map.addLayer(before.clip(region), rgb, 'Before: Sentinel-2 RGB (Jan 2025)', false);
Map.addLayer(after.clip(region), rgb, 'After: Sentinel-2 RGB (Aug 2025)', false);
Map.addLayer(beforeNdvi.clip(region), ndviStyle, 'Before NDVI', false);
Map.addLayer(afterNdvi.clip(region), ndviStyle, 'After NDVI', false);
Map.addLayer(ndviDelta.clip(region), deltaStyle, 'NDVI change: after − before');
Map.addLayer(likelyLoss.clip(region), {palette: ['#ff0000']}, 'Review queue: NDVI decline ≤ −0.20');
Map.addLayer(region, {color: '#ffffff'}, 'ArborPulse pilot boundary', false);

print('Before scene', before.get('system:index'));
print('After scene', after.get('system:index'));
print('Mean NDVI change', ndviDelta.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: region, scale: 20, maxPixels: 1e7
}));
print('Share of pixels in review queue', likelyLoss.unmask(0).reduceRegion({
  reducer: ee.Reducer.mean(), geometry: region, scale: 20, maxPixels: 1e7
}));
