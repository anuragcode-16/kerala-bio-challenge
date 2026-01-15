import pandas as pd
import numpy as np
from collections import defaultdict

class GreedySolver:
    def __init__(self, data_manager):
        self.dm = data_manager
        self.config = self.dm.config
        
        # State Tracking
        self.stp_storage = {row['stp_id']: 0 for _, row in self.dm.stp_df.iterrows()}
        self.farm_zone_map = self.dm.get_farm_zone_map()
        
        self.solution = []
        
        # Constants
        self.TRUCK_CAPACITY = self.config['logistics_constants']['truck_capacity_tons']
        self.N_CONTENT = self.config['agronomic_constants']['nitrogen_content_kg_per_ton_biosolid']
        self.OVERFLOW_PENALTY = self.config['environmental_thresholds']['stp_overflow_penalty_kg_co2_per_ton']
        self.OFFSET_CREDIT = self.config['agronomic_constants']['synthetic_n_offset_credit_kg_co2_per_kg_n']
        self.SEQ_CREDIT = self.config['agronomic_constants']['soil_organic_carbon_gain_kg_co2_per_kg_biosolid'] # per kg biosolid (tons * 1000)
        self.TRANSPORT_COST = self.config['logistics_constants']['diesel_emission_factor_kg_co2_per_km']
        self.LEACHING_PENALTY = self.config['agronomic_constants']['leaching_penalty_kg_co2_per_kg_excess_n']
        
    def solve(self):
        # Iterate through every day of 2025
        dates = pd.date_range(start=f"{self.config['simulation_metadata']['year']}-01-01", 
                              end=f"{self.config['simulation_metadata']['year']}-12-31")
        
        for date in dates:
            self._process_day(date)
            
        return pd.DataFrame(self.solution)

    def _process_day(self, date):
        date_str = date.strftime('%Y-%m-%d')
        
        # 1. Update STP Storage with Daily Output
        for _, stp in self.dm.stp_df.iterrows():
            self.stp_storage[stp['stp_id']] += stp['daily_output_tons']
            
        # 2. Get Daily Demand for all farms
        daily_demands = self.dm.get_demand_for_day(date) # {farm_id: kg_N}
        
        # 3. Identify Rain Locked Farms
        rain_locks = self.dm.rain_lock_matrix.get(date_str, {})
        valid_farms = []
        for farm_id, zone in self.farm_zone_map.items():
            if not rain_locks.get(zone, False):
                valid_farms.append(farm_id)
        
        # Optimization: Process each STP
        # Randomize order or prioritize most full STPs to avoid overflow cascading?
        # Prioritizing most critical STPs (highest % full) is better.
        
        stp_status = []
        for _, stp in self.dm.stp_df.iterrows():
            s_id = stp['stp_id']
            curr = self.stp_storage[s_id]
            max_s = stp['storage_max_tons']
            excess = max(0, curr - max_s)
            fill_ratio = curr / max_s
            stp_status.append({
                'stp_id': s_id,
                'current': curr,
                'max': max_s,
                'excess': excess,
                'fill_ratio': fill_ratio,
                'lat': stp['lat'],
                'lon': stp['lon']
            })
            
        # Sort by urgency (excess desc, fill_ratio desc)
        stp_status.sort(key=lambda x: (x['excess'], x['fill_ratio']), reverse=True)
        
        for stp in stp_status:
            self._dispatch_logic(date_str, stp, valid_farms, daily_demands)

    def _dispatch_logic(self, date_str, stp, valid_farms, daily_demands):
        stp_id = stp['stp_id']
        current_load = stp['current']
        excess_load = stp['excess']
        
        if current_load <= 0:
            return

        # Calculate score for every valid farm
        # Score per Ton = Gain - Cost
        # We assume 1 Truck (10 tons) for scoring to normalize
        
        candidates = []
        
        for farm_id in valid_farms:
            dist = self.dm.distance_matrix.get((stp_id, farm_id))
            if dist is None: continue
            
            n_demand = daily_demands.get(farm_id, 0)
            
            # Theoretical gain for 10 tons (or remaining load if less)
            package_tons = min(self.TRUCK_CAPACITY, current_load)
            package_n = package_tons * self.N_CONTENT
            
            # N Offset Credit (Capped by demand)
            # "Uptake is limited by the values in daily_n_demand.csv"
            # Does this mean we only get credit up to demand, or we are penalized for exceeding?
            # "Applying more Nitrogen than the daily demand ... results in leaching."
            # So Credit = min(applied, demand) * 5.0
            # Leaching Penalty = max(0, applied - 1.1 * demand) * 10.0 (10% buffer)
            
            useful_n = min(package_n, n_demand)
            excess_n = max(0, package_n - (n_demand * 1.1))
            
            credit = (useful_n * self.OFFSET_CREDIT) + \
                     (package_tons * 1000 * self.SEQ_CREDIT / 1000.0 * 1000.0) # wait, unit check
                     # SEQ_CREDIT is per kg of biosolid. 1 ton = 1000 kg.
                     # 0.2 * 1000 = 200 credits per ton.
            
            credits_seq = package_tons * 1000 * 0.2
            
            transport_emission = dist * self.TRANSPORT_COST # per km (one way or round trip? usually one way dist given, emission factor implies trip?)
            # Prompt: "0.9 kg CO2 eq/km". Usually implies distance traveled. Truck travels there and back? 
            # Prompt says "Every kilometer traveled by a delivery truck ... from STP to Farm".
            # Usually strict reading means One Way Distance * 0.9. If round trip needed, normally specified.
            # Let's assume One Way for standard logic unless "Round Trip" specified. 
            # Actually, trucks return. But standard Haversine is Point A to B. 
            # Let's stick to Distance * 0.9 for now. 
            
            leaching_cost = excess_n * self.LEACHING_PENALTY
            
            # Net Score
            net_score = (useful_n * self.OFFSET_CREDIT) + credits_seq - transport_emission - leaching_cost
            
            candidates.append({
                'farm_id': farm_id,
                'dist': dist,
                'score': net_score,
                'demand': n_demand,
                'useful_n': useful_n,
                'package_tons': package_tons
            })
            
        # Sort candidates
        # Strategy:
        # 1. If we have EXCESS (Overflow risk), we MUST dispatch. 
        #    Pick best scores (even if negative, better than -1000/ton penalty).
        # 2. If we are NOT overflowing, only dispatch if Score > Threshold (Profitable).
        
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        dispatched_total = 0
        
        # Greedy Dispatch
        for cand in candidates:
            # Check remaining storage inside loop (it updates)
            if self.stp_storage[stp_id] <= 0:
                break
                
            is_urgent = self.stp_storage[stp_id] > stp['max']
            is_profitable = cand['score'] > 0 # Or some small threshold to account for margin
            
            if not is_urgent and not is_profitable:
                continue # Clean optimization: stop if not forced and not profitable
                # Since list is sorted descending, if we hit non-profitable and not urgent, we can break?
                # Yes, all subsequent will be worse.
                if not is_urgent:
                    break
            
            # Determine Amount to Ship
            # If profitable: Ship as much as possible up to demand? 
            # Actually, per truck (10 tons). 
            # We can ship multiples.
            # But `cand` score was calculated for 1 truck.
            # Let's ship 1 truck at a time or calculate max optimal tonnage?
            # Simple Greedy: Ship 1 truck (or remaining), update storage, re-evaluate loop? 
            # Re-evaluating sort is expensive.
            # Approximation: Ship 10 tons.
            
            ship_tons = min(self.TRUCK_CAPACITY, self.stp_storage[stp_id])
            
            # Add to solution
            self.solution.append({
                'date': date_str,
                'stp_id': stp_id,
                'farm_id': cand['farm_id'],
                'tons_delivered': ship_tons
            })
            
            # Update State
            self.stp_storage[stp_id] -= ship_tons
            dispatched_total += ship_tons
            
            # Update Demand? The problem says "Uptake is limited by... daily_n_demand".
            # If we ship 10 tons, we delivered 250kg N.
            # If demand was 100, we saturated it. 
            # If we ship ANOTHER truck to same farm, it is PURE LEACHING (bad).
            # So we effectively "consumed" the demand for this farm for this day.
            # We should reduce the demand in our local `daily_demands` dict so next truck sees 0 demand.
            
            delivered_n = ship_tons * self.N_CONTENT
            daily_demands[cand['farm_id']] = max(0, daily_demands.get(cand['farm_id'], 0) - delivered_n)
            
            # If we are fulfilling URGENT excess, we continue even if score drops negative (leaching).
            # But wait, if we saturate a farm, the score for next truck drops massively (Zero offset credit, huge leaching).
            # So we should probably sort/re-evaluate or pick next candidate.
            # Since we iterate `candidates` once, this works nicely. We move to next farm in list.
