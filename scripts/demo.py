"""
demo.py — Automated live demo script for ThreatSense-AI.
Cycles through footage files, polls stats, and prints a live summary.

Usage:
    python scripts/demo.py [--host http://localhost:5000] [--password admin123]
"""
import argparse, requests, time, json, sys

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='http://localhost:5000')
    p.add_argument('--password', default='admin123')
    p.add_argument('--username', default='admin')
    args = p.parse_args()

    BASE = f'{args.host}/api'

    # Login
    r = requests.post(f'{BASE}/login', json={'username': args.username, 'password': args.password})
    if r.status_code != 200:
        sys.exit(f'Login failed: {r.text}')
    token = r.json()['token']
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    print(f'[demo] Logged in as {args.username}')

    # List footage
    r = requests.get(f'{BASE}/footage', headers=headers)
    sources = r.json().get('sources', [])
    print(f'[demo] Available sources: {[s["label"] for s in sources]}')

    # Cycle through each video
    for source in sources:
        if source['value'] == '0':
            continue
        
        print(f'\n[demo] Switching to: {source["label"]}')
        r = requests.post(f'{BASE}/pipeline/switch_source', headers=headers,
                         json={'source': source['value']})
        if r.status_code != 200:
            print(f'  Switch failed: {r.text}')
            continue
        
        print(f'  {r.json()["message"]}')
        time.sleep(2)

        # Poll stats while video plays
        for i in range(8):
            time.sleep(3)
            s = requests.get(f'{BASE}/system_status').json()
            stats = requests.get(f'{BASE}/stats', headers=headers).json()
            print(f'  t+{(i+1)*3}s | FPS:{s.get("fps",0):.1f} | '
                  f'Alerts:{stats["total_alerts"]} | Incidents:{stats["total_incidents"]}')

    # Switch back to webcam
    requests.post(f'{BASE}/pipeline/switch_source', headers=headers, json={'source': '0'})
    print('\n[demo] Switched back to webcam. Demo complete.')

    # Final stats
    final = requests.get(f'{BASE}/stats', headers=headers).json()
    print(f'\n=== FINAL STATS ===')
    for k, v in final.items():
        print(f'  {k}: {v}')

if __name__ == '__main__':
    main()
