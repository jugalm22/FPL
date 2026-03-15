import json, random, os

def evaluate(data, w):
    successes = 0
    for gw in data:
        best_s, best_p = -1e9, 0
        for p in gw['candidates']:
            s = 0
            if p['name'] in gw['f_picks']: s += w['f_w']
            if p['name'] in gw['ict_picks']: s += w['ict_w']
            if p['name'] in gw['s_picks']: s += w['s_w']
            
            s += p['form'] * w['f_s'] + p['l2_form'] * w['l2_f_s'] + p['lgw'] * w['lgw_s']
            s += p['ict'] * w['ict_s'] + p['hauls'] * w['h_w'] + p['cost'] * w['c_w']
            s += p['opp_leak'] * w['l_w'] + p['team_score'] * w['ts_w']
            s += w.get(f"pos_{p['pos']}_w", 0)
            
            if p['big6']: s += w['b6_w']
            if p['home']: s += w['h_b']
            if len(p['diffs']) > 1: s += w['dgw_w']
            
            for d in p['diffs']:
                rank = gw['breakdown'].get(str(d), {}).get(p['name'])
                if rank: s += w['hi_w'] - rank
            
            if s > best_s: best_s, best_p = s, p['pts']
        if best_p > 8: successes += 1
    return successes

def main():
    f23, f24 = 'data_2023-24.json', 'data_2024-25.json'
    d23, d24 = [], []
    if os.path.exists(f23):
        with open(f23, 'r') as f: d23 = json.load(f)
    if os.path.exists(f24):
        with open(f24, 'r') as f: d24 = json.load(f)
    
    if not d23 or not d24: return print("Missing data files.")

    best_score, best_w = 0, {}
    print(f"Tuning for dual 50% target...")
    for i in range(200000):
        w = {
            'f_w': random.uniform(0, 20), 'ict_w': random.uniform(0, 20), 's_w': random.uniform(0, 20),
            'f_s': random.uniform(0, 15), 'l2_f_s': random.uniform(0, 15), 'lgw_s': random.uniform(0, 5),
            'ict_s': random.uniform(0, 5), 'h_w': random.uniform(20, 100), 'c_w': random.uniform(0, 20),
            'l_w': random.uniform(0, 10), 'ts_w': random.uniform(0, 10),
            'pos_2_w': random.uniform(0, 10), 'pos_3_w': random.uniform(0, 30), 'pos_4_w': random.uniform(0, 40),
            'b6_w': random.uniform(0, 20), 'h_b': random.uniform(0, 20), 'dgw_w': random.uniform(100, 500),
            'hi_w': random.uniform(2, 20)
        }
        
        s23 = evaluate(d23, w) / len(d23)
        s24 = evaluate(d24, w) / len(d24)
        
        # Metric: Minimize the gap and maximize the lower one
        score = (s23 + s24) / 2
        if s23 < 0.40 or s24 < 0.40: score *= 0.5 # Penalty for low performance in either
        
        if score > best_score:
            best_score, best_w = score, w
            print(f"Trial {i}: 23/24: {s23*100:.1f}% | 24/25: {s24*100:.1f}% (Avg: {score*100:.1f}%)")
            if s23 >= 0.50 and s24 >= 0.50:
                print("VICTORY! Both seasons >= 50%")
                break
            
    print(f"\nFINAL BEST:")
    for k, v in best_w.items(): print(f"  {k}: {v:.2f}")

if __name__ == "__main__": main()
