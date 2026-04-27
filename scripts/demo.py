import requests
import time

def run_demo():
    print("Starting ThreatSense-AI demo script...")
    
    # Wait 5 seconds
    print("Waiting 5 seconds for system to stabilize...")
    time.sleep(5)
    
    # Call /api/stats
    print("Fetching system stats...")
    try:
        response = requests.get("http://localhost:5000/api/stats")
        if response.status_code == 200:
            data = response.json()
            # Printing alert count if it exists in the payload, otherwise print generic success
            print("Successfully retrieved stats.")
            if "alert_count" in data:
                print(f"Alert count: {data['alert_count']}")
        else:
            print(f"Failed to get stats. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        
    # Simulate switching source
    print("Simulating camera source switch...")
    time.sleep(2)
    print("Switched to Backup Camera 2.")

if __name__ == "__main__":
    run_demo()
