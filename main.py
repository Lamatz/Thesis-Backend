
import os
import pickle
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
import traceback

import rasterio
import fiona
from shapely.geometry import Point, shape
import geopandas as gpd
from pyproj import Transformer


print("--- Python script starting to load... ---")

# App Initialization
app = Flask(__name__)
CORS(app) 

# --- Data Loading with Full Error Reporting ---
try:
    print("--- Attempting to load soil shapefile... ---")
    soil_shapefile = "./data/soil_map/hays.shp"
    with fiona.open(soil_shapefile, 'r') as collection:
        soil_features = [(shape(f['geometry']), f['properties']) for f in collection]
    print("--- Soil shapefile loaded successfully. ---")
except Exception:
    print("--- FATAL ERROR LOADING SOIL SHAPEFILE ---")
    traceback.print_exc()  
    soil_features = []

try:
    print("--- Attempting to reference slope tif... ---")
    slope_tif = "./data/slope_map/slope.tif"
    # We will try to open it here to ensure it's valid
    with rasterio.open(slope_tif) as src:
        print(f"--- Slope TIF opened successfully. CRS is {src.crs} ---")
except Exception:
    print("--- FATAL ERROR WITH SLOPE TIF FILE ---")
    traceback.print_exc()  # <-- THIS PRINTS THE FULL ERROR REPORT



# Load spatial files 
try:
    soil_shapefile = "./data/soil_map/hays.shp"
    soil_gdf = gpd.read_file(soil_shapefile)
    soil_gdf.sindex  
except Exception as e:
    traceback.print_exc()  
    print(f"Error loading soil shapefile {soil_shapefile}: {e}")
    soil_gdf = None

# BACKEND NEW
# Load Slope Files
try:
    slope_tif = "./data/slope_map/slope.tif"
    with rasterio.open(slope_tif) as src:
        print(f"Successfully opened slope GeoTIFF. CRS: {src.crs}")
except Exception as e:
    traceback.print_exc()  
    print(f"FATAL ERROR: Could not load slope GeoTIFF from {slope_tif}: {e}")
    slope_tif = None

# Load the models
try:
    with open("./models/model_4.pkl", "rb") as model_file:
        model = pickle.load(model_file)
    with open("./models/scaler_4.pkl", "rb") as scaler_file:
        scaler = pickle.load(scaler_file)
except Exception as e:
    traceback.print_exc()  
    print(f"Error loading ML models: {e}")
    model = None
    scaler = None

# Convert coordinates from WGS84 to raster CRS
def convert_coords(lon, lat, crs):
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return transformer.transform(lon, lat)


# Function to extract soil type from shapefile
def get_soil_type(lon, lat):
    if soil_gdf is None:
        return "Error: Shapefile not loaded"
    point = Point(lon, lat)
    if not point.is_valid:
        return "Error: Invalid coordinates for soil lookup"
    try:
        # BACKEND NEW --------
         # Use spatial index for fast lookup
        possible_matches_index = list(soil_gdf.sindex.intersection(point.bounds))
        possible_matches = soil_gdf.iloc[possible_matches_index]
        precise_matches = possible_matches[possible_matches.intersects(point)]
        if not precise_matches.empty:
            return precise_matches.iloc[0].get("SNUM", "Unknown")
        return "Unknown"  # Point not found in any polygon
        # BACKEND NEW --------
    except Exception as e:
        print(f"Error in get_soil_type: {e}")
        return "Error during processing"


# BACKEND NEW (new get_slope funciton)
# Function to extract slope from GeoTIFF
def get_slope(lon, lat):
    if slope_tif is None:
        return "Error: Raster file not loaded on server"
    try:
        with rasterio.open(slope_tif) as src:
            x, y = convert_coords(lon, lat, src.crs)
            if not (src.bounds.left <= x <= src.bounds.right and src.bounds.bottom <= y <= src.bounds.top):
                return None
            row, col = src.index(x, y)
            if 0 <= row < src.height and 0 <= col < src.width:
                window = ((row, row + 1), (col, col + 1))
                slope_value = src.read(1, window=window, boundless=True)[0, 0]
                if src.nodata is not None and slope_value == src.nodata or np.isnan(slope_value):
                    return None
                return float(slope_value)
            else:
                return None
    except Exception as e:
        print(f"Error during slope extraction: {e}")
        return "Error during processing"


# --- Main API Endpoint ---
# BACKEND NEW (replaced the get location data function) -----------
@app.route("/get_geo_data", methods=["GET"])
def get_geo_data():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if lat is None or lon is None:
        return jsonify({"error": "Missing or invalid coordinates"}), 400

    slope = get_slope(lon, lat)
    soil = get_soil_type(lon, lat)

    return jsonify({
        "slope": float(slope) if slope is not None else None,
        "soil_type": str(soil) if soil is not None else None
    })


@app.route("/predict", methods=["POST"])
def predict():
    if not model or not scaler:
        traceback.print_exc()  
        return jsonify({"error": "Machine learning models are not loaded on the server"}), 503

    try:
        data = request.json
        features = [
            int(data.get("soil_type", 0)),
            float(data.get("slope", 0)),
            float(data.get("soil_moisture", 0)),
            float(data.get("rainfall-3-hr", 0)),
            float(data.get("rainfall-6-hr", 0)),
            float(data.get("rainfall-12-hr", 0)),
            float(data.get("rain-intensity-3-hr", 0)),
            float(data.get("rain-intensity-6hr", 0)),
            float(data.get("rain-intensity-12-hr", 0)),
            float(data.get("rainfall-1-day", 0)),
            float(data.get("rainfall-3-day", 0)),
            float(data.get("rainfall-5-day", 0)),
            float(data.get("rain-intensity-1-day", 0)),
            float(data.get("rain-intensity-3-day", 0)),
            float(data.get("rain-intensity-5-day", 0)),
        ]

        features_scaled = scaler.transform([features])
        probabilities = model.predict_proba(features_scaled)[0]
        prediction = int(np.argmax(probabilities))
        
        return jsonify(
            {
                "prediction": "Landslide" if prediction == 1 else "No Landslide",
                "confidence": f"{max(probabilities) * 100:.2f}%",
            }
        )

    except Exception as e:
        traceback.print_exc()  
        print(f"Error during prediction: {e}")
        return jsonify({"error": str(e)}), 400


# --- Server Start Logic for Cloud Run ---
if __name__ == "__main__":
    # Cloud Run injects the PORT environment variable.
    # Default to 8080 for local testing.
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)




