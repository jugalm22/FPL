import json, os

def validate():
    # Best weights found during 68-GW tuning sessions
    w = {
        'f_w': 1.90, 'ict_w': 4.42, 's_w': 0.12,
        'f_s': 5.31, 'l2_f_s': 0.66, 'lgw_s': 0.77,
        'ict_s': 1.24, 'h_w': 45.49, 'c_w': 1.30,
        'l_w': 4.87, 'ts_w': 1.50, # Estimated team_score weight
        'pos_2_w': 1.91, 'pos_3_w': 13.52, 'pos_4_w': 2.73,
        'b6_w': 5.61, 'h_b': 9.40, 'dgw_w': 141.51,
        'hi_w': 2.84
    }
    
    files = ['data_2023-24.json', 'data_2024-25.json']
    for f_name in files:
        if not os.path.exists(f_name): continue
        with open(f_name, 'r') as f: data = json.load(f)
        
        successes = 0
        total = len(data)
        print(f"\n--- Validation: {f_name} ({total} GWs) ---")
        
        for gw in data:
            best_s, best_p, best_n = -1e9, 0, ""
            for p in gw['candidates']:
                s = 0
                if p['name'] in gw['f_picks']: s += w['f_w']
                if p['name'] in gw['ict_picks']: s += w['ict_w']
                if p['name'] in gw['s_picks']: s += w['s_w']
                
                s += p['form'] * w['f_s'] + p['l2_form'] * w['l2_f_s'] + p['lgw'] * w['lgw_s']
                s += p['ict'] * w['ict_s'] + p['hauls'] * w['h_w'] + p['cost'] * w['c_w']
                s += p.get('opp_leak', 0) * w['l_w'] + p.get('team_score', 0) * w['ts_w']
                s += w.get(f"pos_{p['pos']}_w", 0)
                
                if p['big6']: s += w['b6_w']
                if p['home']: s += w['h_b']
                if len(p['diffs']) > 1: s += w['dgw_w']
                
                for d in p['diffs']:
                    rank = gw['breakdown'].get(str(d), {}).get(p['name'])
                    if rank: s += w['hi_w'] - rank
                
                if s > best_s: best_s, best_p, best_n = s, p['pts'], p['name']
            
            if best_p > 8:
                successes += 1
                print(f"GW{gw['gw']}: SUCCESS: {best_n} ({best_p} pts)")
            else:
                print(f"GW{gw['gw']}: FAIL: {best_n} ({best_p} pts)")
        
        print(f"RESULT: {successes}/{total} ({successes/total*100:.1f}%)")

if __name__ == "__main__":
    validate()
