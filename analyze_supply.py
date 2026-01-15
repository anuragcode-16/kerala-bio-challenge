import pandas as pd
import os

def analyze_supply_demand():
    base_dir = r"c:\Users\anura\Downloads\iitpk"
    data_dir = os.path.join(base_dir, "datasets")
    
    # Load Supply
    stps = pd.read_csv(os.path.join(data_dir, "stp_registry.csv"))
    total_daily_output = stps['daily_output_tons'].sum()
    total_annual_tons = total_daily_output * 365
    nitrogen_content = 25 # kg per ton
    total_supply_n = total_annual_tons * nitrogen_content
    
    print(f"Total Annual Biosolid Supply: {total_annual_tons:,.0f} tons")
    print(f"Total Annual Nitrogen Supply: {total_supply_n:,.0f} kg N")
    
    # Load Demand
    demand_df = pd.read_csv(os.path.join(data_dir, "daily_n_demand.csv"))
    # Demand is in columns F_xxxx. Sum all numeric columns excluding date.
    farm_cols = [c for c in demand_df.columns if c.startswith('F_')]
    
    total_daily_demand = demand_df[farm_cols].sum().sum()
    print(f"Total Annual Nitrogen Demand: {total_daily_demand:,.0f} kg N")
    
    balance = total_daily_demand - total_supply_n
    print(f"Net Balance (Demand - Supply): {balance:,.0f} kg N")
    
    if balance < 0:
        print("CONCLUSION: Supply exceeds Demand. Leaching is INEVITABLE.")
    else:
        print("CONCLUSION: Demand exceeds Supply. Optimization can potentially avoid leaching.")

if __name__ == "__main__":
    analyze_supply_demand()
