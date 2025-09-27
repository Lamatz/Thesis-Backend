
import os
from flask import Flask, request, jsonify
import traceback
from flask_cors import CORS
import rasterio
import numpy as np
import geopandas as gpd # We'll keep geopandas for simplicity here
from shapely.geometry import Point
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
    traceback.print_exc()  # <-- THIS PRINTS THE FULL ERROR REPORT
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
    print(f"Error loading soil shapefile {soil_shapefile}: {e}")
    soil_gdf = None

# BACKEND NEW
try:
    slope_tif = "./data/slope_map/slope.tif"
    with rasterio.open(slope_tif) as src:
        print(f"Successfully opened slope GeoTIFF. CRS: {src.crs}")
except Exception as e:
    print(f"FATAL ERROR: Could not load slope GeoTIFF from {slope_tif}: {e}")
    slope_tif = None



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

    return jsonify({"slope": slope, "soil_type": soil})


print("--- Python script loaded. Gunicorn can now start the server. ---")

# --- Server Start Logic for Cloud Run ---
if __name__ == "__main__":
    # Cloud Run injects the PORT environment variable.
    # Default to 8080 for local testing.
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)


# --- BREADCRUMB 7: This will only be seen if Gunicorn is NOT used ---
print("--- Script finished, web server should be running ---")

# # =========================================================================
# # == MODIFIED: Fetch weather data to accept time and generate chart data ==
# # =========================================================================
# def fetch_weather_data(latitude, longitude, end_date_str, end_time_str):
#     try:
#         # Combine date and time for a precise endpoint
#         end_datetime = datetime.strptime(
#             f"{end_date_str} {end_time_str}", "%Y-%m-%d %H:%M"
#         )

#         # Fetch data for the last 6 days to ensure all windows are covered
#         api_start_date = end_datetime - timedelta(days=6)
#         api_end_date = end_datetime

#         url = "https://api.open-meteo.com/v1/forecast"
#         params = {
#             "latitude": latitude,
#             "longitude": longitude,
#             "hourly": "precipitation,soil_moisture_27_to_81cm",
#             "start_date": api_start_date.strftime("%Y-%m-%d"),
#             "end_date": api_end_date.strftime("%Y-%m-%d"),
#             "timezone": "auto",
#             "forecast_days": 0,
#             "precipitation_unit": "inch",
#         }

#         response = requests.get(url, params=params, timeout=10)
#         response.raise_for_status()
#         data = response.json()

#         hourly_data = data.get("hourly", {})
#         df = pd.DataFrame(
#             {
#                 "timestamp": pd.to_datetime(hourly_data["time"]),
#                 "rain_mm": np.array(hourly_data["precipitation"]),
#                 "soil_moisture": np.array(hourly_data["soil_moisture_27_to_81cm"]),
#             }
#         ).fillna(0.0)

#         # Filter to only include data up to the user's selected end_datetime
#         df = df[df["timestamp"] <= end_datetime].copy()
#         if df.empty:
#             return {"error": "No historical data available for the selected time."}

#         # --- Calculations for the prediction model ---
#         def compute_cumulative(hours):
#             start_time = end_datetime - timedelta(hours=hours)
#             mask = (df["timestamp"] > start_time) & (df["timestamp"] <= end_datetime)
#             return float(df.loc[mask, "rain_mm"].sum())

#         def compute_intensity(hours):
#             cumulative = compute_cumulative(hours)
#             return float(cumulative / hours) if hours > 0 else 0.0

#         time_windows = {
#             "3_hr": 3,
#             "6_hr": 6,
#             "12_hr": 12,
#             "1_day": 24,
#             "3_day": 72,
#             "5_day": 120,
#         }
#         cumulative_rainfall = {
#             label: compute_cumulative(h) for label, h in time_windows.items()
#         }
#         rain_intensity = {
#             label: compute_intensity(h) for label, h in time_windows.items()
#         }

#         # --- NEW & CORRECTED: Generate clean data specifically for the 4 charts ---

#         # 1. Hourly Chart Data (for the 12 hours leading up to end_datetime)
#         hourly_chart_data = []
#         # Get the last 12 data points from our filtered dataframe
#         last_12_hours_df = df.tail(12)

#         running_cumulative = 0
#         for index, row in last_12_hours_df.iterrows():
#             running_cumulative += row["rain_mm"]
#             hourly_chart_data.append(
#                 {
#                     "hour": row["timestamp"].strftime("%H:00"),
#                     "cumulative": running_cumulative,  # A true running total over the 12hr window
#                     "intensity": row[
#                         "rain_mm"
#                     ],  # The intensity is just the rainfall for that single hour
#                 }
#             )

#         # 2. Daily Chart Data (for the 5 days leading up to end_date)
#         daily_df = df[
#             df["timestamp"]
#             >= end_datetime.replace(hour=0, minute=0, second=0) - timedelta(days=4)
#         ].copy()
#         daily_summary = (
#             daily_df.groupby(daily_df["timestamp"].dt.date)
#             .agg(
#                 daily_cumulative=("rain_mm", "sum"),
#                 # The average intensity for a day is the total rain divided by 24 hours
#                 daily_avg_intensity=("rain_mm", lambda x: x.sum() / 24),
#             )
#             .reset_index()
#         )

#         daily_chart_data = [
#             {
#                 "date": row["timestamp"].strftime("%b %d"),
#                 "cumulative": float(row["daily_cumulative"]),
#                 "intensity": float(row["daily_avg_intensity"]),
#             }
#             for _, row in daily_summary.iterrows()
#         ]

#         return {
#             "soil_moisture": float(df["soil_moisture"].iloc[-1]),
#             "cumulative_rainfall": cumulative_rainfall,
#             "rain_intensity": rain_intensity,
#             "hourly_chart_data": hourly_chart_data,
#             "daily_chart_data": daily_chart_data,
#         }

#     except Exception as e:
#         print(f"Error processing weather data: {e}")
#         return {"error": f"Error processing weather data: {e}"}


# # ... (rest of your ./data routes: search_locations, get_weather endpoint handler, predict endpoint handler, model loading, main execution block) ...


# @app.route("/search_locations", methods=["GET"])
# def search_locations():
#     query = request.args.get("query")
#     if not query:
#         return jsonify({"error": "Missing query parameter"}), 400

#     # Added a minimum query length for efficiency and relevance
#     if len(query.strip()) < 3:
#         return jsonify({"suggestions": []})  # Return empty list for short queries

#     # Add a User-Agent header as recommended by Nominatim
#     query = request.args.get("query")  # This line likely exists already
#     url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1&countrycodes=PH"

#     headers = {"User-Agent": "Two-Step-Ahead (eriksonss1535@gmail.com)"}
#     response = requests.get(url, headers=headers)

#     if response.status_code != 200:
#         print(f"Error fetching Nominatim data: Status {response.status_code}")
#         return (
#             jsonify({"error": "Failed to fetch location data from Nominatim"}),
#             response.status_code,
#         )

#     data = response.json()

#     # Debugging output
#     print("Nominatim Query:", query)
#     print("Nominatim Response (first 5):", data[:1])  # Print only first few for brevity

#     if not data:
#         print("No results found for Nominatim query:", query)
#         return jsonify({"suggestions": []})  # Return empty list if no results

#     locations = []
#     for item in data:
#         # **Crucially: ONLY extract and return basic info from Nominatim**
#         # **DO NOT call get_soil_type, get_slope, or fetch_weather_data here**
#         locations.append(
#             {
#                 "name": item.get("display_name", "Unnamed Location"),
#                 "lat": item.get("lat"),
#                 "lon": item.get("lon"),
#                 # Add other useful Nominatim fields if needed, but avoid fetching external data
#                 "category": item.get("category"),
#                 "type": item.get("type"),
#             }
#         )

#     print(f"Returning {len(locations)} search suggestions.")
#     return jsonify({"suggestions": locations})


# # ==========================================================
# # == MODIFIED: /get_weather endpoint to accept time param ==
# # ==========================================================
# @app.route("/get_weather", methods=["GET"])
# def get_weather():
#     latitude = request.args.get("latitude", type=float)
#     longitude = request.args.get("longitude", type=float)
#     date = request.args.get("date", type=str)
#     # Get time, with a default of 23:59 if not provided
#     time = request.args.get("time", "23:59")

#     if not all([latitude, longitude, date, time]):
#         return jsonify({"error": "Missing required parameters"}), 400

#     data = fetch_weather_data(latitude, longitude, date, time)
#     return jsonify(data)


# # I WILL CHANGE THIS PATHING

# # Load trained model and scaler
# with open("./data/model_4.pkl", "rb") as model_file:
#     model = pickle.load(model_file)

# with open("./data/scaler_4.pkl", "rb") as scaler_file:
#     scaler = pickle.load(scaler_file)


# @app.route("/predict", methods=["POST"])
# def predict():
#     try:
#         data = request.json
#         features = [
#             int(data.get("soil_type", 0)),
#             float(data.get("slope", 0)),
#             float(data.get("soil_moisture", 0)),
#             float(data.get("rainfall-3-hr", 0)),
#             float(data.get("rainfall-6-hr", 0)),
#             float(data.get("rainfall-12-hr", 0)),
#             float(data.get("rain-intensity-3-hr", 0)),
#             float(data.get("rain-intensity-6hr", 0)),
#             float(data.get("rain-intensity-12-hr", 0)),
#             float(data.get("rainfall-1-day", 0)),
#             float(data.get("rainfall-3-day", 0)),
#             float(data.get("rainfall-5-day", 0)),
#             float(data.get("rain-intensity-1-day", 0)),
#             float(data.get("rain-intensity-3-day", 0)),
#             float(data.get("rain-intensity-5-day", 0)),
#         ]

#         features_scaled = scaler.transform([features])
#         probabilities = model.predict_proba(features_scaled)[0]
#         prediction = int(np.argmax(probabilities))
#         print(features)
#         print(features_scaled)
#         print(probabilities)
#         return jsonify(
#             {
#                 "prediction": "Landslide" if prediction == 1 else "No Landslide",
#                 "confidence": f"{max(probabilities) * 100:.2f}%",
#             }
#         )

#     except Exception as e:
#         return jsonify({"error": str(e)}), 400


# # ==========================================================
# # == CODE for the Generate AI Report ==
# # ==========================================================


# # In order to use this properly you need to first:
# # 1. Have an api key for the gemini model (you can use mine but I recommend you have you own so that mine doesn't reach the rate limit. AIzaSyB-rg3sokaltFw2IHB8eiR1hbjNFaGxMpQ )
# # 2. create a ' .env ' file and the content should be ' GEMINI_API_KEY="your_api_key" '
# # 3. the .env file and the server.py file should be in the same directory/within the same folder
# # 4. It should now work but if it doesn't make sure to save everything and reload you work
# load_dotenv()

# client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# # === ENDPOINT 2: NEW GEMINI REPORT GENERATOR ===
# @app.route("/generate_report", methods=["POST"])  # <-- NEW, SEPARATE URL
# def generate_report():
#     """
#     Receives data and uses Gemini to generate a detailed text report.
#     """
#     try:
#         data = request.get_json()
#         if not data:
#             return jsonify({"error": "No JSON data received"}), 400
#         print("Received data for GEMINI report:", data)

#         response = client.models.generate_content_stream(
#             model="gemini-2.5-flash",
            
#             contents=f"""
#             Generate a comprehensive risk assessment report for a potential landslide.
#             The report should be structured, professional, and easy for a non-expert to understand.
#             Your analysis should consider all the environmental data provided below.
#             Conclude with a clear risk level (e.g., Low, Moderate, High, Critical) and a list of actionable recommendations for Local Government Units (LGUs) and residents.
            
#             ---
#             **DISCLAIMER:**
#             This report is based on the available data and predictive models. Ground conditions can change rapidly. Furthermore, this report was made using the gemini model. This assessment should be used as a guide for disaster preparedness and mitigation and not as a substitute for on-site engineering and geological assessments.

#             ---
#             **INCIDENT AND ASSESSMENT OVERVIEW:**
#             - **Report Generation Date:** {data.get('date_today', 'N/A')}
#             - **Prediction for Date:** {data.get('prediction_date', 'N/A')}
#             - **Location:** {data.get('location_name', 'N/A')} 
#             - **Coordinates:** (for latitude: {data.get('location_lat', 'N/A')} ) (for longituded {data.get('location_lng', 'N/A')})

#             ---
#             **INITIAL PREDICTION CONTEXT:**
#             - **Initial Model Prediction:** {data.get('original_model_prediction', 'N/A')}
#             - **Initial Model Confidence:** {data.get('original_model_confidence', 'N/A')}

#             ---
#             **GEOLOGICAL AND SITE CHARACTERISTICS:**

#             - **Geological Assessment:** [Provide a brief description of the area's geology, e.g., "The area is underlain by [rock formation], which is known for its susceptibility to weathering and erosion."]
#             - **Soil Type:** {data.get('soil_type', 'N/A')} 
#             - **Slope Angle (degrees):** {data.get('slope', 'N/A')} if the slope is 1 then the slope is less than 10 degress it is 2 the slope value is between 10 to 20 degress if it is 3 then the value is between 20 to 30 degrees if the value is 4 then the value is between 30 to 40 degress if it is 5 then the value is 40 to 50 degress if it is 6 then the value is more than 50 degrees
 

#             ---
#             **HYDRO-METEOROLOGICAL DATA:**

#             **CUMULATIVE RAINFALL (mm):**
#             - **Last 3 hours:** {data.get('rainfall-3_hr', 'N/A')}
#             - **Last 6 hours:** {data.get('rainfall-6_hr', 'N/A')}
#             - **Last 12 hours:** {data.get('rainfall-12_hr', 'N/A')}
#             - **Last 1 day:** {data.get('rainfall-1-day', 'N/A')}
#             - **Last 3 days:** {data.get('rainfall-3-day', 'N/A')}
#             - **Last 5 days:** {data.get('rainfall-5-day', 'N/A')}

#             **RAINFALL INTENSITY (mm/hr):**
#             - **Average over last 3 hours:** {data.get('rain-intensity-3_hr', 'N/A')}
#             - **Average over last 6 hours:** {data.get('rain-intensity-6_hr', 'N/A')}
#             - **Average over last 12 hours:** {data.get('rain-intensity-12_hr', 'N/A')}
#             - **Average over last 1 day:** {data.get('rain-intensity-1-day', 'N/A')}
#             - **Average over last 3 days:** {data.get('rain-intensity-3-day', 'N/A')}
#             - **Average over last 5 days:** {data.get('rain-intensity-5-day', 'N/A')}

#             **SOIL MOISTURE:**
#             - **Current Soil Moisture (percentage):** {data.get('soil_moisture', 'N/A')}%

#             ---
#             **VULNERABILITY AND RISK ASSESSMENT:**

#             **Analysis of Landslide Contributing Factors:**
#             [This section should synthesize the data above. For example: "The steep slope of {data.get('slope', 'N/A')}, combined with the soil type ({data.get('soil_type', 'N/A')}), makes the area inherently susceptible to landslides. The recent heavy rainfall over the past 3 days ({data.get('rainfall-3-day', 'N/A')} mm) has likely increased soil saturation and pore water pressure, further elevating the risk."]

#             **Agreement with Initial Prediction:**
#             [Comment on the initial model's prediction. For example: "The initial model's prediction of a {data.get('original_model_prediction', 'N/A')} risk level is consistent with this detailed analysis. The high confidence of {data.get('original_model_confidence', 'N/A')}% is supported by the combination of geological and meteorological factors."]

#             ---
#             **LANDSLIDE REPORT SUMMARY:**
#             **Summary/Conclusion:**
#             [Provide a clear and concise summary of the report so far]
            
#             ---

#             **RECOMMENDATIONS:**

#             **For the Local Government Unit (LGU) / Disaster Risk Reduction and Management Office (DRRMO):**
#             1.  **Information Dissemination:** Immediately disseminate this warning to the affected barangays and communities.
#             2.  **Monitoring:** Continuously monitor rainfall and be alert for signs of impending landslides (e.g., tension cracks, bulging ground, unusual sounds). Observe for rapid increases or decreases in creek/river water levels, which may be accompanied by increased turbidity.
#             3.  **Pre-emptive Evacuation:** For areas rated as Highly or Critically susceptible, consider and, if necessary, implement pre-emptive evacuation, especially for residents in the most dangerous areas.
#             4.  **Evacuation Centers:** Ensure that designated evacuation centers are ready, accessible, and equipped with necessary supplies.
#             5.  **Road Safety:** Monitor road conditions and advise the public of any potential road closures.

#             **For Residents and the Community:**
#             1.  **Be Vigilant:** Be aware of your surroundings and watch for any signs of land movement.
#             2.  **Stay Informed:** Monitor official news and advisories from PAGASA and your local DRRMO.
#             3.  **Evacuate if Necessary:** If you are in a high-risk area, be prepared to evacuate immediately when instructed by local authorities.
#             4.  **Community-Based Monitoring:** Report any unusual observations to your barangay officials.


#             **--- END OF REPORT ---**

#             """,
#         )

#         def stream_generator():
#             for stream in response:
#                 if stream.text:
#                     yield stream.text

#         return Response(stream_generator(), mimetype="text/plain")
#         # return jsonify({"report": response.text})

#     except Exception as e:
#         print(f"An error occurred in report generation: {e}")
#         return (
#             jsonify(
#                 {"error": "An internal error occurred while generating the report."}
#             ),
#             500,
#         )


