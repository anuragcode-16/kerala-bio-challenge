import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import os

def generate_gif():
    base_dir = r"c:\Users\anura\Downloads\iitpk"
    data_dir = os.path.join(base_dir, "datasets")
    
    # Load Data
    solution = pd.read_csv(os.path.join(data_dir, "solution.csv"))
    farms = pd.read_csv(os.path.join(data_dir, "farm_locations.csv"))
    stps = pd.read_csv(os.path.join(data_dir, "stp_registry.csv"))
    
    solution['date'] = pd.to_datetime(solution['date'])
    
    # Find busiest month
    solution['month'] = solution['date'].dt.to_period('M')
    top_month = solution.groupby('month')['tons_delivered'].sum().idxmax()
    print(f"Generating GIF for busiest month: {top_month}")
    
    monthly_data = solution[solution['month'] == top_month]
    days = sorted(monthly_data['date'].unique())
    
    # Setup Plot
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(75.5, 77.5) # Approximate Kerala Longitude
    ax.set_ylim(8.0, 12.5)  # Approximate Kerala Latitude
    ax.set_title(f"Logistics Flow - {top_month}")
    
    # Static Background
    ax.scatter(farms['lon'], farms['lat'], s=10, c='green', alpha=0.3, label='Farms')
    ax.scatter(stps['lon'], stps['lat'], s=100, c='red', marker='^', label='STPs')
    ax.legend(loc='lower right')
    
    lines = []
    
    def update(frame_date):
        # Clear previous lines
        for line in lines:
            line.remove()
        lines.clear()
        
        day_moves = monthly_data[monthly_data['date'] == frame_date]
        
        ax.set_title(f"Logistics Flow - {frame_date.date()}")
        
        for _, row in day_moves.iterrows():
            stp = stps[stps['stp_id'] == row['stp_id']].iloc[0]
            farm = farms[farms['farm_id'] == row['farm_id']].iloc[0]
            
            line, = ax.plot([stp['lon'], farm['lon']], [stp['lat'], farm['lat']], 
                            c='blue', alpha=0.5, linewidth=0.5)
            lines.append(line)
            
    ani = animation.FuncAnimation(fig, update, frames=days, interval=200)
    
    output_path = os.path.join(data_dir, "dashboard_preview.gif")
    ani.save(output_path, writer='pillow')
    print(f"GIF saved to {output_path}")

if __name__ == "__main__":
    generate_gif()
