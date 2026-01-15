import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.express as px
import os
import json

# Page Config
st.set_page_config(layout="wide", page_title="Kerala Bio-Carbon Dashboard")

# Constants
# Use relative path for Streamlit Cloud
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets")

# Load Data
@st.cache_data
def load_data():
    solution = pd.read_csv(os.path.join(DATA_DIR, "solution.csv"))
    farms = pd.read_csv(os.path.join(DATA_DIR, "farm_locations.csv"))
    stps = pd.read_csv(os.path.join(DATA_DIR, "stp_registry.csv"))
    
    # Pre-process
    solution['date'] = pd.to_datetime(solution['date'])
    return solution, farms, stps

solution_df, farm_df, stp_df = load_data()

# Sidebar - Date Control
st.sidebar.title("Logistics Control")
min_date = solution_df['date'].min().date()
max_date = solution_df['date'].max().date()
selected_date = st.sidebar.slider("Select Date", min_date, max_date, min_date)

# Data Processing for Selected Date
current_date_ts = pd.to_datetime(selected_date)
daily_moves = solution_df[solution_df['date'].dt.date == selected_date]

# --- Rain Lock Logic for Visualization ---
# We need to know which zones are rain-locked on this date
from src.data_manager import DataManager
# Re-instantiate DataManager loosely (optimized for app) or load pre-computed
with open(os.path.join(DATA_DIR, "config.json")) as f:
    config = json.load(f)

weather_df = pd.read_csv(os.path.join(DATA_DIR, "daily_weather_2025.csv"))
weather_df['date'] = pd.to_datetime(weather_df['date'])

# Calculate rain lock for this specific date (5-day lookahead)
# Filter weather for [date, date+4]
mask = (weather_df['date'] >= current_date_ts) & (weather_df['date'] <= current_date_ts + pd.Timedelta(days=4))
forecast_window = weather_df.loc[mask]
rain_locked_zones = []
if not forecast_window.empty:
    numeric_cols = forecast_window.select_dtypes(include=['number']).columns
    sums = forecast_window[numeric_cols].sum()
    rain_locked_zones = sums[sums > config['environmental_thresholds']['rain_lock_threshold_mm']].index.tolist()

# Add visuals for farms: Color by Rain Status
def get_farm_color(zone):
    if zone in rain_locked_zones:
        return [128, 128, 128, 100] # Grey for Rain Locked
    return [0, 255, 0, 180] # Green for Active

farm_df['color'] = farm_df['zone'].apply(get_farm_color)

# --- KPI Calculations ---
# Load daily stats for dynamic calculation
stats_path = os.path.join(DATA_DIR, "dashboard_stats.csv")
if os.path.exists(stats_path):
    stats_df = pd.read_csv(stats_path)
    stats_df['date'] = pd.to_datetime(stats_df['date'])
    
    # Filter up to selected date (Cumulative)
    cum_stats = stats_df[stats_df['date'] <= current_date_ts]
    
    # Sum components
    c_net_score = cum_stats['net_score'].sum()
    c_tons = cum_stats['tons_delivered'].sum()
    c_n_del = cum_stats['n_delivered'].sum()
    c_n_dem = cum_stats['n_demand_system'].sum()
    c_km = cum_stats['round_trip_km'].sum()
    c_monsoon = cum_stats['monsoon_tons'].sum()
    
    # Calculate Ratios
    # 1. Net Carbon Credits
    kpi_score = c_net_score
    
    # 2. Nitrogen Precision (Cumulative Delivered / Cumulative Demand)
    kpi_precision = 0
    if c_n_dem > 0:
        kpi_precision = c_n_del / c_n_dem
        
    # 3. Logistics Efficiency (Cumulative Tons / Cumulative KM)
    kpi_eff = 0
    if c_km > 0:
        kpi_eff = c_tons / c_km
        
    # 4. Rain-Lock Resilience (Cumulative Monsoon Tons / Cumulative Tons)
    # Note: Formula says "Deliveries during Monsoon / Total Annual Deliveries"
    # User feedback "showing static results... make it according to data" implies dynamic.
    # We will use "Total Deliveries SO FAR" to show the running ratio.
    kpi_resilience = 0
    if c_tons > 0:
        kpi_resilience = c_monsoon / c_tons

    # 5. Real-time Gauge: Total STP Storage
    # This is a SNAPSHOT of the day, not a cumulative sum.
    # Get the value for the selected date.
    day_stats = stats_df[stats_df['date'].dt.date == selected_date]
    if not day_stats.empty:
        current_storage = day_stats.iloc[0]['total_storage_tons']
    else:
        current_storage = 0

else:
    # Fallback to zero
    kpi_score, kpi_precision, kpi_eff, kpi_resilience, current_storage = 0, 0, 0, 0, 0

st.sidebar.markdown("### The Scoreboard")
st.sidebar.metric("Net Carbon Credits", f"{kpi_score:,.0f}", 
    help="(Synthetic Offset + SOC Gain) - (Transport + Leaching + Overflow Costs)")

st.sidebar.markdown("---")
col_kpi1, col_kpi2 = st.sidebar.columns(2)

col_kpi1.metric("Nitrogen Precision", f"{kpi_precision:.1%}", 
    help="Actual N Delivered / Biological N Demand")

col_kpi2.metric("Logistics Efficiency", f"{kpi_eff:.3f}", 
    help="Total Tons Delivered / Total Round-trip KM")

st.sidebar.metric("Rain-Lock Resilience", f"{kpi_resilience:.1%}", 
    help="Deliveries during Monsoon (Jun-Sep) / Total Annual Deliveries")

st.sidebar.markdown("### Real-time Gauges")
st.sidebar.metric("Total STP Storage", f"{current_storage:,.0f} Tons", help="Current total biosolids held in all 4 STPs")

# Metrics Row (Daily)
st.subheader(f"Logistics Overview - {selected_date.strftime('%Y-%m-%d')}")
col1, col2, col3, col4 = st.columns(4)
daily_tons = daily_moves['tons_delivered'].sum()
col1.metric("Daily Delivery", f"{daily_tons} Tons")
col2.metric("Active Trucks", f"{len(daily_moves)}")
col3.metric("Rain Locked Zones", f"{len(rain_locked_zones)}", delta_color="inverse")
col4.metric("Active STPs", f"{daily_moves['stp_id'].nunique()}/4")


# Map Visualization
st.subheader("Dynamic Logistics Dashboard")

# 1. Farm Layer (Dynamic Color)
farm_layer = pdk.Layer(
    "ScatterplotLayer",
    data=farm_df,
    get_position='[lon, lat]',
    get_fill_color='color',
    get_radius=300,
    pickable=True,
    auto_highlight=True
)

# 2. STP Layer
stp_layer = pdk.Layer(
    "ScatterplotLayer",
    data=stp_df,
    get_position='[lon, lat]',
    get_fill_color='[255, 0, 0, 200]',
    get_radius=1500,
    pickable=True
)

# 3. Connection Layer (Arcs)
if not daily_moves.empty:
    moves_mapped = daily_moves.merge(stp_df[['stp_id', 'lat', 'lon']], on='stp_id', suffixes=('_s', '')) \
                              .rename(columns={'lat': 'lat_s', 'lon': 'lon_s'}) \
                              .merge(farm_df[['farm_id', 'lat', 'lon']], on='farm_id', suffixes=('_s', '_f')) \
                              .rename(columns={'lat': 'lat_f', 'lon': 'lon_f'})
    
    arc_layer = pdk.Layer(
        "ArcLayer",
        data=moves_mapped,
        get_source_position='[lon_s, lat_s]',
        get_target_position='[lon_f, lat_f]',
        get_source_color=[255, 255, 0, 100], # Yellow pulse
        get_target_color=[0, 255, 0, 100],
        get_width=3,
        width_min_pixels=2
    )
    layers = [farm_layer, stp_layer, arc_layer]
else:
    layers = [farm_layer, stp_layer]

# View State
view_state = pdk.ViewState(
    latitude=10.5,
    longitude=76.5,
    zoom=7.5,
    pitch=40,
    bearing=0
)

r = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    tooltip={"text": "Farm: {farm_id}\nZone: {zone}"},
    map_style='mapbox://styles/mapbox/dark-v10'
)

st.pydeck_chart(r)

# Rain Warning
if rain_locked_zones:
    st.warning(f"Rain Lock Active in: {', '.join(rain_locked_zones)}. Deliveries suspended to these zones.")
else:
    st.success("No Rain Locks active. All zones open.")


# Analysis Charts
st.subheader("Daily Trends")
daily_agg = solution_df.groupby('date')['tons_delivered'].sum().reset_index()
fig = px.bar(daily_agg, x='date', y='tons_delivered', title="Daily Tonnage Delivered")
st.plotly_chart(fig, use_container_width=True)
