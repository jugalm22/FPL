import os
import pandas as pd
import json
import warnings
warnings.filterwarnings('ignore')

def prepare_data(fy):
    print(f"Preparing {fy} data...")
    repo_path = os.path.join(os.getcwd(), "Fantasy-Premier-League")
    players_dir = os.path.join(repo_path, "data", fy, "players")
    players_raw_csv = os.path.join(repo_path, "data", fy, "players_raw.csv")
    fixtures_csv = os.path.join(repo_path, "data", fy, "fixtures.csv")
    
    fixtures_df = pd.read_csv(fixtures_csv)
    raw_pdf = pd.read_csv(players_raw_csv)
    el_to_team = dict(zip(raw_pdf['id'], raw_pdf['team']))
    el_to_pos = dict(zip(raw_pdf['id'], raw_pdf['element_type']))
    el_to_cost = dict(zip(raw_pdf['id'], raw_pdf['now_cost']))
    
    BIG_SIX = [1, 6, 12, 13, 14, 18]
    team_def, team_off = {}, {}
    max_gw = int(fixtures_df[fixtures_df['finished'] == True]['event'].max())
    
    for gw_idx in range(1, max_gw + 1):
        team_def[gw_idx], team_off[gw_idx] = {}, {}
        gw_f = fixtures_df[fixtures_df['event'] <= gw_idx]
        for tid in range(1, 21):
            games = gw_f[(gw_f['team_h'] == tid) | (gw_f['team_a'] == tid)].tail(4)
            conceded = 0
            scored = 0
            for _, r in games.iterrows():
                if r['team_h'] == tid:
                    conceded += r['team_a_score']
                    scored += r['team_h_score']
                else:
                    conceded += r['team_h_score']
                    scored += r['team_a_score']
            team_def[gw_idx][tid] = conceded
            team_off[gw_idx][tid] = scored

    all_data = []
    for cur_gw in range(5, max_gw + 1):
        stats = []
        for folder in os.listdir(players_dir):
            p_path = os.path.join(players_dir, folder)
            if not os.path.isdir(p_path): continue
            gw_csv = os.path.join(p_path, "gw.csv")
            if not os.path.exists(gw_csv): continue
            
            try:
                p_id = int(folder.split('_')[-1])
                if el_to_pos.get(p_id, 9) >= 5: continue # Filter managers
                
                df = pd.read_csv(gw_csv)
                past_df = df[df['round'] < cur_gw]
                if past_df.empty: continue
                
                p4 = past_df.tail(4)
                target = df[df['round'] == cur_gw]
                team_id = el_to_team.get(p_id, 0)
                
                f_cur = fixtures_df[fixtures_df['event'] == cur_gw]
                f_cur = f_cur[(f_cur['team_h'] == team_id) | (f_cur['team_a'] == team_id)]
                diffs = []
                for _, r in f_cur.iterrows():
                    diffs.append(int(r['team_h_difficulty'] if r['team_h'] == team_id else r['team_a_difficulty']))
                
                hist = {d: 0 for d in range(1, 6)}
                for _, r in p4[p4['minutes'] > 1].iterrows():
                    f_row = fixtures_df[fixtures_df['id'] == r['fixture']].iloc[0]
                    d = f_row['team_h_difficulty'] if r['was_home'] else f_row['team_a_difficulty']
                    hist[int(d)] += r['total_points']
                
                stats.append({
                    'name': " ".join(folder.split('_')[:-1]),
                    'team': team_id, 'pos': el_to_pos.get(p_id, 3),
                    'form': float(p4['total_points'].mean()),
                    'l2_form': float(past_df.tail(2)['total_points'].mean()),
                    'lgw': float(past_df.tail(1)['total_points'].values[0]),
                    'ict': float(p4['ict_index'].mean()),
                    'hauls': len(p4[p4['total_points'] > 8]),
                    'cost': float(el_to_cost.get(p_id, 0) / 10.0),
                    'opp_leak': team_def.get(cur_gw-1, {}).get(team_id, 0),
                    'team_score': team_off.get(cur_gw-1, {}).get(team_id, 0),
                    'hist': hist, 'big6': team_id in BIG_SIX,
                    'diffs': diffs, 'home': any(target['was_home']) if not target.empty else False,
                    'pts': int(target['total_points'].sum()) if not target.empty else 0
                })
            except: continue

        stats.sort(key=lambda x: x['form'] + x['hauls']*2, reverse=True)
        ghost = stats[:50]
        
        breakdown = {d: {p['name']: i+1 for i, p in enumerate(sorted(ghost, key=lambda x: x['hist'][d], reverse=True)[:3])} for d in range(1, 6)}
        
        all_data.append({
            'gw': cur_gw, 'candidates': ghost,
            'f_picks': [p['name'] for p in sorted(ghost, key=lambda x: x['form'], reverse=True)[:3]],
            'ict_picks': [p['name'] for p in sorted(ghost, key=lambda x: x['ict'], reverse=True)[:3]],
            's_picks': [p['name'] for p in sorted(ghost, key=lambda x: x['form'], reverse=True)[:5]],
            'breakdown': breakdown
        })
        
    with open(f'data_{fy}.json', 'w') as f: json.dump(all_data, f)
    print(f"Saved data_{fy}.json")

if __name__ == "__main__":
    prepare_data("2023-24")
    prepare_data("2024-25")
