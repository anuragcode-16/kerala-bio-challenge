import pandas as pd
import json
import os
from .utils import haversine_distance

class DataManager:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.config = self._load_json("config.json")
        self.stp_df = self._load_csv("stp_registry.csv")
        self.farm_df = self._load_csv("farm_locations.csv")
        self.weather_df = self._load_csv("daily_weather_2025.csv")
        self.demand_df = self._load_csv("daily_n_demand.csv")
        self.planting_df = self._load_csv("planting_schedule_2025.csv")
        
        self._preprocess_dates()
        self.distance_matrix = self._compute_distance_matrix()
        self.rain_lock_matrix = self._compute_rain_lock_matrix()

    def _load_json(self, filename):
        with open(os.path.join(self.data_dir, filename), 'r') as f:
            return json.load(f)

    def _load_csv(self, filename):
        return pd.read_csv(os.path.join(self.data_dir, filename))

    def _preprocess_dates(self):
        self.weather_df['date'] = pd.to_datetime(self.weather_df['date'])
        self.demand_df['date'] = pd.to_datetime(self.demand_df['date'])

    def _compute_distance_matrix(self):
        """
        Returns a dictionary {(stp_id, farm_id): distance_km}
        """
        dist_matrix = {}
        for _, stp in self.stp_df.iterrows():
            for _, farm in self.farm_df.iterrows():
                d = haversine_distance(stp['lat'], stp['lon'], farm['lat'], farm['lon'])
                dist_matrix[(stp['stp_id'], farm['farm_id'])] = d
        return dist_matrix

    def _compute_rain_lock_matrix(self):
        """
        Returns a dictionary or dataframe indicating if a zone is rain-locked on a given date.
        Rain Lock: 5-day forecast (current + 4 days) sum > 30mm.
        Config key: rain_lock_threshold_mm, forecast_window_days
        """
        threshold = self.config['environmental_thresholds']['rain_lock_threshold_mm']
        window = self.config['environmental_thresholds']['forecast_window_days']
        
        # Helper to get numeric rainfall columns (zones)
        zones = [c for c in self.weather_df.columns if c != 'date']
        
        # Calculate rolling sum forward looking. 
        # rolling(window) is backward looking usually, so we reverse, roll, reverse.
        # Or use pandas rolling with proper window centering/offset. 
        # Easier: index by date, roll matching the problem statement.
        
        # "current day + 4 days ahead" = 5 days total window starting at current day.
        # We can use rolling(window=5, min_periods=1).sum().shift(-4) 
        # shift(-4) brings the sum of [t, t+4] to row t.
        
        rain_df = self.weather_df.set_index('date').sort_index()
        indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=window)
        rolling_sum = rain_df[zones].rolling(window=indexer, min_periods=1).sum()
        
        is_locked = rolling_sum > threshold
        
        # Convert to dictionary for fast lookup: {date_str: {zone: bool}}
        # Or just keep as dataframe/fast lookup structure
        lock_dict = {}
        for date, row in is_locked.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            lock_dict[date_str] = row.to_dict()
            
        return lock_dict

    def get_demand_for_day(self, date):
        """Returns {farm_id: demand_kg} for the specific date"""
        date_str = date.strftime('%Y-%m-%d')
        # Filter demand_df
        # Since demand_df columns are farm_ids (based on sample_submission logic usually, 
        # but let's check the file content provided in context. 
        # File content of daily_n_demand.csv: date, F_1000, F_1001...
        # So it's wide format.
        
        row = self.demand_df[self.demand_df['date'] == date].iloc[0]
        # Drop date column to get just farms
        demands = row.drop('date').to_dict()
        return demands

    def get_farm_zone_map(self):
        return pd.Series(self.farm_df.zone.values, index=self.farm_df.farm_id).to_dict()
