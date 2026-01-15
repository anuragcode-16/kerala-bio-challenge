import os
import pandas as pd
from src.data_manager import DataManager
from src.solver import GreedySolver

def main():
    base_dir = r"c:\Users\anura\Downloads\iitpk"
    data_dir = os.path.join(base_dir, "datasets")
    
    print("Loading data...")
    dm = DataManager(data_dir)
    
    print("Initializing solver...")
    solver = GreedySolver(dm)
    
    print("Solving logistics...")
    solution_df = solver.solve()
    
    # Save solution
    output_path = os.path.join(data_dir, "solution.csv")
    solution_df.to_csv(output_path, index=False)
    print(f"Solution saved to {output_path}")
    
    # Preliminary Check
    print(f"Total Deliveries: {len(solution_df)}")
    print(f"Total Tons Delivered: {solution_df['tons_delivered'].sum()}")

if __name__ == "__main__":
    main()
