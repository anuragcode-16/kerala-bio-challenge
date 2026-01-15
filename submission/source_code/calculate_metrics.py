import pandas as pd
import json
import os
from src.data_manager import DataManager

def calculate_metrics():
    base_dir = r"c:\Users\anura\Downloads\iitpk"
    data_dir = os.path.join(base_dir, "datasets")
    
    dm = DataManager(data_dir)
    solution_path = os.path.join(data_dir, "solution.csv")
    
    if not os.path.exists(solution_path):
        print("Solution file not found.")
        return

    solution = pd.read_csv(solution_path)
    solution['date'] = pd.to_datetime(solution['date'])
    
    total_co2_credits = 0
    total_transport_emission = 0
    total_leaching_penalty = 0
    total_overflow_penalty = 0
    total_offset_gain = 0
    total_sequestration_gain = 0
    
    # Constants
    TRUCK_CAPACITY = dm.config['logistics_constants']['truck_capacity_tons']
    N_CONTENT = dm.config['agronomic_constants']['nitrogen_content_kg_per_ton_biosolid']
    OFFSET_CREDIT = dm.config['agronomic_constants']['synthetic_n_offset_credit_kg_co2_per_kg_n']
    SEQ_CREDIT = dm.config['agronomic_constants']['soil_organic_carbon_gain_kg_co2_per_kg_biosolid']
    TRANSPORT_COST = dm.config['logistics_constants']['diesel_emission_factor_kg_co2_per_km']
    LEACHING_PENALTY = dm.config['agronomic_constants']['leaching_penalty_kg_co2_per_kg_excess_n']
    
    # Track Farm Demand Consumption Daily
    # Re-simulate somewhat to check validity
    
    # Group by date for easier processing
    daily_groups = solution.groupby('date')
    
    all_dates = pd.date_range(start=f"{dm.config['simulation_metadata']['year']}-01-01", 
                              end=f"{dm.config['simulation_metadata']['year']}-12-31")
    
    stp_storage = {row['stp_id']: 0 for _, row in dm.stp_df.iterrows()}
    
    for date in all_dates:
        date_str = date.strftime('%Y-%m-%d')
        
        # 1. Update STP Flow
        for _, stp in dm.stp_df.iterrows():
            stp_storage[stp['stp_id']] += stp['daily_output_tons']
            
        # 2. Get Daily Moves
        moves = pd.DataFrame()
        if date in daily_groups.groups:
            moves = daily_groups.get_group(date)
            
        # 3. Process Moves
        if not moves.empty:
            for _, row in moves.iterrows():
                stp_id = row['stp_id']
                farm_id = row['farm_id']
                tons = row['tons_delivered']
                
                # Transport Cost
                dist = dm.distance_matrix.get((stp_id, farm_id), 0)
                # Transport emission is per km per truck? Or just per km?
                # "Every kilometer traveled by a delivery truck ... costs 0.9 kg"
                # If we assume 1 truck per delivery (<= 10 tons). 
                # If tons > 10, multiple trucks needed? But our solver capped at 10.
                # So 1 trip per row in solution provided logic holds.
                
                num_trucks = 1 # simplified as tons <= 10
                transport_emission = dist * TRANSPORT_COST * num_trucks
                total_transport_emission += transport_emission
                
                # Deduct Storage
                stp_storage[stp_id] -= tons
                
                # Farm Credits
                # Need original demand again?
                # DataManager provides it.
                daily_demands = dm.get_demand_for_day(date) 
                # BUT wait, multiple trucks to same farm?
                # GreedySolver decremented demand locally.
                # Here we need to aggregate delivery per farm per day first.
                
        # Aggregate deliveries to check leaching correctly
        if not moves.empty:
            farm_totals = moves.groupby('farm_id')['tons_delivered'].sum()
            daily_demands = dm.get_demand_for_day(date)
            
            for farm_id, delivered_tons in farm_totals.items():
                delivered_n = delivered_tons * N_CONTENT
                demand_n = daily_demands.get(farm_id, 0)
                
                useful_n = min(delivered_n, demand_n)
                excess_n = max(0, delivered_n - (demand_n * 1.1))
                
                offset_gain = useful_n * OFFSET_CREDIT
                seq_gain = delivered_tons * 1000 * SEQ_CREDIT
                leaching = excess_n * LEACHING_PENALTY
                
                total_offset_gain += offset_gain
                total_sequestration_gain += seq_gain
                total_leaching_penalty += leaching
        
        # 4. Check Overflow
        for _, stp in dm.stp_df.iterrows():
            s_id = stp['stp_id']
            max_s = stp['storage_max_tons']
            if stp_storage[s_id] > max_s:
                excess = stp_storage[s_id] - max_s
                penalty = excess * dm.config['environmental_thresholds']['stp_overflow_penalty_kg_co2_per_ton']
                total_overflow_penalty += penalty
                # Dump excess? The prompt says "excess waste is dumped". 
                # Yes, assumes it is removed from storage.
                stp_storage[s_id] = max_s 

    # --- KPI CALCULATIONS ---
    # 1. Net Carbon Credit Score
    total_net_score = (total_offset_gain + total_sequestration_gain) - \
                      (total_transport_emission + total_leaching_penalty + total_overflow_penalty)
    
    # 2. Nitrogen Precision
    # Formula: Actual N Delivered / Biological N Demand
    # We need Total Biological Demand for the whole year.
    # Load demand again for full sum
    demand_df = pd.read_csv(os.path.join(data_dir, "daily_n_demand.csv"))
    numeric_cols = [c for c in demand_df.columns if c.startswith('F_')]
    total_annual_demand_n = demand_df[numeric_cols].sum().sum()
    
    total_delivered_tons = solution['tons_delivered'].sum()
    total_delivered_n = total_delivered_tons * N_CONTENT
    
    n_precision = 0
    if total_annual_demand_n > 0:
        n_precision = total_delivered_n / total_annual_demand_n

    # 3. Logistics Efficiency
    # Formula: Total Tons Delivered / Total Round-trip KM
    # We need Total Dist for all trips
    # We assumed 1 truck per 10 tons (or part thereof) in solver.
    # In 'calculate_metrics', we calculated emission. 
    # Emission = Dist * TRANSPORT_COST * trucks.
    # TRANSPORT_COST = 0.9 kg/km.
    # Total KM Traveled = total_transport_emission / TRANSPORT_COST
    # Round Trip KM? If 0.9 is per km traveled, and we calculated per trip...
    # Let's assume the solver's 'dist' was one-way.
    # If the user wants "Round-trip KM", we should double the one-way distance for the efficiency metric denominator.
    # However, if 'transport_emission' was calculated based on 0.9 cost/km * dist, 
    # and we want 'Total Round-trip KM', we need to be careful.
    # Solver used one-way 'dist'.
    # Metric Definition: Total Tons / Total Round-trip KM.
    # Let's calculate One Way KM sum explicitly.
    
    total_one_way_km = 0
    # Re-loop to sum dist * trips accurately
    # Actually we can back it out from emission if constant:
    # Total One Way KM = total_transport_emission / TRANSPORT_COST / 1.0 (assuming trucks=1 logic held)
    # But let's be precise.
    
    # We'll accumulate km in the main loop above. 
    # To avoid rewriting the whole loop, let's use the backing-out method or re-sum from dataframe + distance matrix
    # Since we need to join anyway:
    
    sol_with_dist = solution.copy()
    sol_with_dist['dist'] = sol_with_dist.apply(lambda x: dm.distance_matrix.get((x['stp_id'], x['farm_id']), 0), axis=1)
    total_trips = len(sol_with_dist) # Assuming 10-tons per row = 1 truck
    sol_with_dist['round_trip_km'] = sol_with_dist['dist'] * 2
    total_round_trip_km = sol_with_dist['round_trip_km'].sum()
    
    logistics_efficiency = 0
    if total_round_trip_km > 0:
        logistics_efficiency = total_delivered_tons / total_round_trip_km

    # 4. Rain-Lock Resilience
    # Formula: Deliveries during Monsoon / Total Annual Deliveries
    # Kerala Monsoon: Roughly June 1 to Sept 30.
    sol_with_dist['month'] = sol_with_dist['date'].dt.month
    monsoon_mask = (sol_with_dist['month'] >= 6) & (sol_with_dist['month'] <= 9)
    monsoon_deliveries = sol_with_dist[monsoon_mask]['tons_delivered'].sum()
    total_deliveries = sol_with_dist['tons_delivered'].sum()
    
    rain_lock_resilience = 0
    if total_deliveries > 0:
        rain_lock_resilience = monsoon_deliveries / total_deliveries

    metrics = {
        "scoreboard": {
            "net_carbon_credit_score": round(total_net_score, 2),
            "nitrogen_precision": round(n_precision, 4),
            "logistics_efficiency": round(logistics_efficiency, 4),
            "rain_lock_resilience": round(rain_lock_resilience, 4)
        },
        "details": {
            "total_delivered_tons": total_delivered_tons,
            "total_demand_n_kg": total_annual_demand_n,
            "total_delivered_n_kg": total_delivered_n,
            "total_round_trip_km": total_round_trip_km
        },
        "gains": {
            "synthetic_fertilizer_offset": total_offset_gain,
            "soil_carbon_sequestration": total_sequestration_gain
        },
        "penalties": {
            "transport_emissions": total_transport_emission,
            "nitrogen_leaching": total_leaching_penalty,
            "stp_overflow": total_overflow_penalty
        }
    }
    
    print(json.dumps(metrics, indent=2))
    with open(os.path.join(data_dir, "summary_metrics.json"), 'w') as f:
        json.dump(metrics, f, indent=2)

if __name__ == "__main__":
    calculate_metrics()
