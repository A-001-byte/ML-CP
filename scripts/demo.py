"""
demo.py — Automated live demo script for ThreatSense-AI.
Cycles through footage files, polls stats, and prints a live summary.

Usage:
    python scripts/demo.py [--host http://localhost:5000] [--password admin123]
"""
import argparse, requests, time, json, sys

def checked_request(method, url, timeout=10, **kwargs):
    response = requests.request(method, url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='http://localhost:5000')
    p.add_argument('--password', default='admin123')
    p.add_argument('--username', default='admin')
    args = p.parse_args()

    BASE = f'{args.host}/api'

    # Login
    try:
        r = checked_request('POST', f'{BASE}/login', json={'username': args.username, 'password': args.password})
        token = r.json()['token']
    except requests.exceptions.RequestException as e:
        sys.exit(f'Login failed: {e}')

    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    print(f'[demo] Logged in as {args.username}')

    # List footage
    r = checked_request('GET', f'{BASE}/footage', headers=headers)
    sources = r.json().get('sources', [])
    print(f'[demo] Available sources: {[s["label"] for s in sources]}')

    # Cycle through each video
    for source in sources:
        if source['value'] == '0':
            continue
        
        print(f'\n[demo] Switching to: {source["label"]}')
        try:
            r = checked_request('POST', f'{BASE}/pipeline/switch_source', headers=headers, json={'source': source['value']})
            print(f'  {r.json()["message"]}')
        except requests.exceptions.RequestException as e:
            print(f'  Switch failed: {e}')
            continue
        
        time.sleep(2)

        # Poll stats while video plays
        for i in range(8):
            time.sleep(3)
            try:
                s = checked_request('GET', f'{BASE}/system_status').json()
                stats = checked_request('GET', f'{BASE}/stats', headers=headers).json()
                print(f'  t+{(i+1)*3}s | FPS:{s.get("fps",0):.1f} | '
                      f'Alerts:{stats["total_alerts"]} | Incidents:{stats["total_incidents"]}')
            except requests.exceptions.RequestException as e:
                print(f'  Poll failed: {e}')

    # Switch back to webcam
    try:
        checked_request('POST', f'{BASE}/pipeline/switch_source', headers=headers, json={'source': '0'})
    except requests.exceptions.RequestException:
        pass
    print('\n[demo] Switched back to webcam. Demo complete.')

    # Final stats
    try:
        final = checked_request('GET', f'{BASE}/stats', headers=headers).json()
        print(f'\n=== FINAL STATS ===')
        for k, v in final.items():
            print(f'  {k}: {v}')
    except requests.exceptions.RequestException as e:
        print(f'Failed to get final stats: {e}')

if __name__ == '__main__':
    main()
