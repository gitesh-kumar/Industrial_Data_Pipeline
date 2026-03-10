import pandas as pd
import numpy as np
from datetime import datetime

class EnergyMarketAPI:
    def get_current_price(self):
        # Prices in Germany fluctuate. We'll simulate a "Peak" during 
        # day hours and "Off-Peak" at night.
        now = datetime.now()
        hour = now.hour
        
        # Base price 150 EUR/MWh. Peak (9am-5pm) adds 100 EUR.
        base_price = 150.0
        peak_surge = 100.0 if 9 <= hour <= 17 else 0.0
        
        # Add some market volatility
        market_price = base_price + peak_surge + np.random.normal(0, 15)
        
        return {
            "timestamp": now.strftime('%Y-%m-%d %H:%M:%S'),
            "unit": "EUR/MWh",
            "price": round(market_price, 2)
        }

if __name__ == "__main__":
    api = EnergyMarketAPI()
    print(f"Current Energy Market Data: {api.get_current_price()}")