import os, sys, json, requests, subprocess, pandas as pd, operator, itertools
from typing import List, Dict, Any, TypedDict, Annotated, cast
from bs4 import BeautifulSoup
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# --- State definition ---
class FPLState(TypedDict):
    entry_id: str
    gameweek: str
    fy: str
    rules_summary: str
    repo_path: str
    squad_ids: List[int]
    player_paths: List[str]
    # Analysis outputs
    top_picks: Dict[str, List[Dict[str, Any]]]
    npa_picks: Dict[str, List[Dict[str, Any]]]
    scout_picks: List[Dict[str, Any]]
    specialist_picks: List[Dict[str, Any]]
    gaffer_picks: List[Dict[str, Any]]
    # Shared data pool
    harvester_data: Dict[str, Any]
    errors: Annotated[List[str], operator.add]

# --- Memory Persistence ---
CONFIG_FILE = "config.json"
def load_config(): return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else {}
def save_config(eid, fy): json.dump({"last_entry_id": eid, "last_fy": fy}, open(CONFIG_FILE, "w"), indent=4)

if sys.stdout.encoding.lower() != 'utf-8': sys.stdout.reconfigure(encoding='utf-8')

# --- Agent 1: The Ruler ---
def ruler_agent(state: FPLState):
    print("🤖 Agent 1 (The Ruler): Scraping FPL Rules...")
    try:
        url = "https://fantasy.premierleague.com/help/rules"
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        rules_text = soup.get_text(separator=' ', strip=True)
        summary = "Captains earn 2x points. Triple Captain chip earns 3x points. Vice-captain scores if captain plays 0 mins."
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            try:
                llm = ChatOpenAI(model="gpt-4o", temperature=0)
                prompt = f"Extract a brief summary of captaincy multipliers from:\n\n{rules_text[:5000]}"
                summary = llm.invoke([HumanMessage(content=prompt)]).content
            except: pass
        print("   ✅ Rules scraped.")
        return {"rules_summary": summary}
    except Exception as e:
        return {"rules_summary": "Error fetching rules.", "errors": [f"Ruler Error: {str(e)}"]}

# --- Agent 2: The Puller ---
def puller_agent(state: FPLState):
    print("🤖 Agent 2 (The Puller): Syncing Data Repository...")
    target_dir = os.path.join(os.getcwd(), "Fantasy-Premier-League")
    try:
        if os.path.exists(target_dir):
            subprocess.run(["git", "pull"], cwd=target_dir, check=True, capture_output=True)
        else:
            subprocess.run(["git", "clone", "https://github.com/vaastav/Fantasy-Premier-League.git", target_dir], check=True, capture_output=True)
        print("   ✅ Data synced.")
        return {"repo_path": target_dir}
    except Exception as e:
        return {"errors": [f"Puller Error: {str(e)}"]}

# --- Agent 3: The Eventer ---
def eventer_agent(state: FPLState):
    print("🤖 Agent 3 (The Eventer): Fetching Squad...")
    eid, gw = state['entry_id'], state['gameweek']
    try:
        if str(gw).lower() == 'latest':
            bs = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/").json()
            events = bs.get('events', [])
            gw = next((e['id'] for e in events if e['is_current']), 1)
            if not next((e['id'] for e in events if e['is_current']), None):
                gw = next((e['id'] for e in events if e['is_next']), 1)
        resp = requests.get(f"https://fantasy.premierleague.com/api/entry/{eid}/event/{gw}/picks/").json()
        squad_ids = [p['element'] for p in resp.get('picks', [])]
        print(f"   ✅ GW{gw} squad fetched.")
        return {"squad_ids": squad_ids, "gameweek": str(gw)}
    except Exception as e:
        return {"errors": [f"Eventer Error: {str(e)}"]}

# --- Agent 4: The Mapper ---
def mapper_agent(state: FPLState):
    print("🤖 Agent 4 (The Mapper): Mapping IDs to Local Folders...")
    repo, fy, squad = state['repo_path'], state['fy'], state['squad_ids']
    p_dir = os.path.join(repo, "data", fy, "players")
    paths = []
    folders = [f for f in os.listdir(p_dir) if os.path.isdir(os.path.join(p_dir, f))]
    for sid in squad:
        for f in folders:
            if f.endswith(f"_{sid}"):
                paths.append(os.path.join(p_dir, f))
                break
    print(f"   ✅ Mapped {len(paths)} players.")
    return {"player_paths": paths}

# --- Agent 5: The Harvester (Data Scientist) ---
def harvester_agent(state: FPLState):
    print("🤖 Agent 5 (The Harvester): Gathering Global Data...")
    repo, fy = state['repo_path'], state['fy']
    next_gw = int(state['gameweek']) + 1
    try:
        raw = pd.read_csv(f"{repo}/data/{fy}/players_raw.csv")
        fix = pd.read_csv(f"{repo}/data/{fy}/fixtures.csv")
        # Explicit typing for Pyre
        el_to_team: Dict[int, int] = cast(Dict[int, int], dict(zip(raw['id'].astype(int), raw['team'].astype(int))))
        el_to_pos: Dict[int, int] = cast(Dict[int, int], dict(zip(raw['id'].astype(int), raw['element_type'].astype(int))))
        pos_names: Dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

        # Team leakage (last 4 games)
        team_leak: Dict[int, int] = {}
        for tid in range(1, 21):
            games = fix[(fix['finished']==True) & ((fix['team_h']==tid) | (fix['team_a']==tid))].tail(4)
            leak = 0
            for _, r in games.iterrows(): leak += int(r['team_a_score'] if r['team_h']==tid else r['team_h_score'])
            team_leak[tid] = leak

        all_players: List[Dict[str, Any]] = []
        p_dir = os.path.join(repo, "data", fy, "players")
        for f in os.listdir(p_dir):
            path = os.path.join(p_dir, f)
            if not os.path.isdir(path): continue
            csv = os.path.join(path, "gw.csv")
            if not os.path.exists(csv): continue
            try:
                p_id = int(str(f).split('_')[-1])
                if el_to_pos.get(p_id, 9) >= 5: continue
                df = pd.read_csv(csv)
                val_df = df[df['round'] < next_gw]
                latest_val = float(val_df['value'].iloc[-1]/10.0) if not val_df.empty else 0.0
                total_pts = int(val_df['total_points'].sum()) if not val_df.empty else 0
                past = df[df['round'] < next_gw]
                if past.empty: continue
                p4 = past.tail(4)
                tid = el_to_team.get(p_id, 0)
                
                # Next fixture tier
                nf_rows = fix[fix['event'] == next_gw]
                p_nf = nf_rows[(nf_rows['team_h'] == tid) | (nf_rows['team_a'] == tid)]
                next_tier = int(p_nf.iloc[0]['team_h_difficulty'] if p_nf.iloc[0]['team_h'] == tid else p_nf.iloc[0]['team_a_difficulty']) if not p_nf.empty else 0
                
                # Performance by difficulty
                hist = {d: 0 for d in range(1, 6)}
                counts = {d: 0 for d in range(1, 6)}
                for _, r in p4[p4['minutes'] > 1].iterrows():
                    f_row = fix[fix['id']==r['fixture']].iloc[0]
                    d = f_row['team_h_difficulty'] if r['was_home'] else f_row['team_a_difficulty']
                    hist[int(d)] += int(r['total_points'])
                    counts[int(d)] += 1
                
                # Weighted Difficulty Score
                num = sum(hist[d] * d for d in range(1, 6))
                den = sum(counts[d] * d for d in range(1, 6))
                w_score = float(num / den) if den > 0 else 0.0
                
                all_players.append({
                    'id': p_id, 'name': " ".join(str(f).split('_')[:-1]),
                    'team': tid, 'pos': int(el_to_pos.get(p_id, 3)), 'pos_name': str(pos_names.get(int(el_to_pos.get(p_id, 0)), "Unknown")),
                    'form': float(p4['total_points'].mean()), 'ict': float(p4['ict_index'].mean()),
                    'xg': float(p4['expected_goals'].sum()) if 'expected_goals' in p4.columns else 0.0,
                    'hauls': int(len(p4[p4['total_points'] > 8])), 'cost': float(latest_val), 'total_pts': int(total_pts),
                    'ppv': float(total_pts / latest_val) if latest_val > 0 else 0.0, # pyre-ignore
                    'leak': int(team_leak.get(tid, 0)), 'hist': hist, 'counts': counts, 'w_score': w_score,
                    'next_tier': next_tier,
                    'l2_form': float(past.tail(2)['total_points'].mean())
                })
            except: continue

        # Local ranks for Agent 8/9
        ranks = {d: {p['name']: i+1 for i, p in enumerate(sorted(all_players, key=lambda x: x['hist'][d], reverse=True)[:3])} for d in range(1, 6)} # pyre-ignore
        
        print(f"   ✅ Processed metadata for {len(all_players)} players.")
        return {"harvester_data": {"all_players": all_players, "team_leak": team_leak, "ranks": ranks, "fixtures": fix}}
    except Exception as e:
        return {"errors": [f"Harvester Error: {str(e)}"]}

# --- Agent 6: The Captain ---
def captain_agent(state: FPLState):
    print("🤖 Agent 6 (The Captain): Analyzing Captaincy Picks...")
    h = cast(Dict[str, Any], state['harvester_data'])
    squad_ids = cast(List[int], state['squad_ids'])
    squad_stats = [p for p in cast(List[Dict[str, Any]], h['all_players']) if p['id'] in squad_ids]
    form_picks = sorted(squad_stats, key=lambda x: float(x['form']), reverse=True)[:3] # pyre-ignore
    ict_picks = sorted(squad_stats, key=lambda x: float(x['ict']), reverse=True)[:3] # pyre-ignore
    return {"top_picks": {"form_picks": form_picks, "ict_picks": ict_picks}}

# --- Agent 7: Agent NPA ---
def npa_agent(state: FPLState):
    print("🤖 Agent 7 (The NPA): Analyzing Positional Gaps...")
    h = state['harvester_data']
    squad_ids = state['squad_ids']
    squad_stats = [p for p in h['all_players'] if p['id'] in squad_ids]
    npa_picks = {}
    for p_type in ["GKP", "DEF", "MID", "FWD"]:
        pos_list = [p for p in squad_stats if p['pos_name'] == p_type]
        npa_picks[p_type] = sorted(pos_list, key=lambda x: x['total_pts'])[:3] # pyre-ignore
    return {"npa_picks": npa_picks}

# --- Agent 8: The Scout ---
def scout_agent(state: FPLState):
    print("🤖 Agent 8 (The Scout): Scanning Global FPL Market...")
    h = cast(Dict[str, Any], state['harvester_data'])
    all_p = cast(List[Dict[str, Any]], h['all_players'])
    
    # Top 10 by each metric
    t_form = sorted(all_p, key=lambda x: x['form'], reverse=True)[:10] # pyre-ignore
    t_ict = sorted(all_p, key=lambda x: x['ict'], reverse=True)[:10] # pyre-ignore
    t_ppv = sorted(all_p, key=lambda x: x['ppv'], reverse=True)[:10] # pyre-ignore
    
    # Consolidated unique pool
    unique = {p['id']: p for p in (t_form + t_ict + t_ppv)}
    scout_picks = sorted(unique.values(), key=lambda x: (x['form'], x['ict'], x['ppv']), reverse=True)[:15] # pyre-ignore
    return {"scout_picks": scout_picks}

# --- Agent 9: The Specialist ---
def specialist_agent(state: FPLState):
    print("🤖 Agent 9 (The Specialist): Deep Historical Analysis...")
    h = cast(Dict[str, Any], state['harvester_data'])
    # Weighted Rank by w_score
    specialist_list = sorted(cast(List[Dict[str, Any]], h['all_players']), key=lambda x: x['w_score'], reverse=True)[:15] # pyre-ignore
    return {"specialist_picks": specialist_list}

# --- Agent 10: The Gaffer ---
def gaffer_agent(state: FPLState):
    print("🤖 Agent 10 (The Gaffer): Making Final Recommendations...")
    h = state['harvester_data']
    squad_ids, next_gw = state['squad_ids'], int(state['gameweek']) + 1
    squad_stats = [p for p in h['all_players'] if p['id'] in squad_ids]
    
    w = {'f_w': 8.7, 'ict_w': 2.4, 'f_s': 1.6, 'l2_f_s': 3.3, 'ict_s': 0.8, 'h_w': 48.0, 'c_w': 1.9, 'l_w': 2.4, 'b6_w': 3.9, 'home_b': 7.9, 'dgw_w': 186.0, 'hi_w': 3.5, 'p3': 5.8, 'p4': 7.9}
    
    form_picks = [p['name'] for p in state['top_picks']['form_picks']]
    ict_picks = [p['name'] for p in state['top_picks']['ict_picks']]
    ranks, fix = h['ranks'], h['fixtures']
    nf = fix[fix['event'] == next_gw]
    
    gaffer_scores = []
    for p in squad_stats:
        score = 0.0
        if str(p['name']) in form_picks: score += float(w['f_w'])
        if str(p['name']) in ict_picks: score += float(w['ict_w'])
        score += float(p['form'])*float(w['f_s']) + float(p['l2_form'])*float(w['l2_f_s']) + float(p['ict'])*float(w['ict_s']) + int(p['hauls'])*float(w['h_w']) + float(p['cost'])*float(w['c_w']) + int(p['leak'])*float(w['l_w'])
        if int(p['pos']) == 3: score += float(w['p3'])
        if int(p['pos']) == 4: score += float(w['p4'])
        if int(p['team']) in [1, 6, 12, 13, 14, 18]: score += float(w['b6_w'])
        
        p_fix = nf[(nf['team_h'] == p['team']) | (nf['team_a'] == p['team'])]
        if len(p_fix) > 1: score += w['dgw_w']
        for _, r in p_fix.iterrows():
            is_h = r['team_h'] == p['team']
            if is_h: score += w['home_b']
            d = r['team_h_difficulty'] if is_h else r['team_a_difficulty']
            rank = cast(Dict[int, Dict[str, int]], ranks).get(int(d), {}).get(str(p['name']))
            if rank: score += float(w['hi_w']) - float(rank)
        gaffer_scores.append({'name': p['name'], 'score': score})
    
    return {"gaffer_picks": sorted(gaffer_scores, key=lambda x: float(x['score']), reverse=True)[:2]} # pyre-ignore

def main():
    print("🏆 FPL Captain Multi-Agent System (Unified Brain) 🏆")
    config = load_config()
    eid = input(f"Entry ID [{config.get('last_entry_id', '')}]: ") or config.get('last_entry_id', "")
    gw = input("Gameweek [latest]: ") or "latest"
    fy = input(f"Season [{config.get('last_fy', '2024-25')}]: ") or config.get('last_fy', "2024-25")
    save_config(eid, fy)

    graph = StateGraph(FPLState)
    graph.add_node("ruler", ruler_agent)
    graph.add_node("puller", puller_agent)
    graph.add_node("eventer", eventer_agent)
    graph.add_node("mapper", mapper_agent)
    graph.add_node("harvester", harvester_agent)
    graph.add_node("captain", captain_agent)
    graph.add_node("npa", npa_agent)
    graph.add_node("scout", scout_agent)
    graph.add_node("specialist", specialist_agent)
    graph.add_node("gaffer", gaffer_agent)
    
    graph.set_entry_point("ruler")
    graph.add_edge("ruler", "puller")
    graph.add_edge("puller", "eventer")
    graph.add_edge("eventer", "mapper")
    graph.add_edge("mapper", "harvester")
    graph.add_edge("harvester", "captain")
    graph.add_edge("captain", "npa")
    graph.add_edge("npa", "scout")
    graph.add_edge("scout", "specialist")
    graph.add_edge("specialist", "gaffer")
    graph.add_edge("gaffer", END)
    
    app = graph.compile()
    res = app.invoke({"entry_id": eid, "gameweek": gw, "fy": fy, "errors": [], "squad_ids": [], "player_paths": [], "top_picks": {}, "npa_picks": {}, "scout_picks": [], "specialist_picks": [], "gaffer_picks": [], "rules_summary": "", "repo_path": "", "harvester_data": {}})

    print("\n" + "="*45 + "\n🎯 FINAL CAPTAINCY RECOMMENDATIONS 🎯\n" + "="*45)
    print(f"\n📋 RULES SUMMARY:\n{res['rules_summary']}")
    
    print("\n🔥 AGENT 5 (CAPTAIN): TOP SQUAD PICKS (Mean Last 4 GWs)")
    print(f"{'Player':<20} | {'Mean Form':<10} | {'Mean ICT':<10}")
    print("-" * 45)
    for p in res['top_picks']['form_picks']:
        print(f"{p['name']:<20} | {p['form']:<10.2f} | {p['ict']:<10.2f}")
    
    print("\n🛡️ AGENT 6 (NPA): POSITION BOTTOM 3 (TO BENCH/SELL) - Total Pts Season")
    print(f"{'Pos':<5} | {'Players (Total Pts)':<40}")
    print("-" * 45)
    for pos, players in res['npa_picks'].items():
        p_str = ", ".join([f"{p['name']} ({p['total_pts']})" for p in players])
        print(f"{pos:<5} | {p_str}")

    print("\n🌍 AGENT 8 (SCOUT): GLOBAL MARKET CONSOLIDATED TOP (Form/ICT/PPV/xG)")
    print(f"{'Player':<20} | {'Pos':<5} | {'Form':>6} | {'ICT':>6} | {'PPV':>6} | {'xG':>6} | {'Cost':<5}")
    print("-" * 75)
    for p in cast(List[Dict[str, Any]], res['scout_picks'])[:15]: # pyre-ignore
        print(f"{p['name'][:20]:<20} | {p['pos_name']:<5} | {p['form']:>6.1f} | {p['ict']:>6.1f} | {p['ppv']:>6.1f} | {p['xg']:>6.2f} | £{p['cost']:<5.1f}")

    print("\n🎯 AGENT 9 (SPECIALIST): WEIGHTED TIER PERFORMANCE & RANK")
    print(f"{'Player':<20} | {'W.Rank':>7} | {'T1':>3} | {'T2':>3} | {'T3':>3} | {'T4':>3} | {'T5':>3} | {'Next'}")
    print("-" * 75)
    for p in cast(List[Dict[str, Any]], res['specialist_picks'])[:15]: # pyre-ignore
        hv = cast(Dict[int, int], p['hist'])
        nt = p.get('next_tier', 0)
        print(f"{p['name'][:20]:<20} | {p['w_score']:>7.2f} | {hv.get(1,0):>3} | {hv.get(2,0):>3} | {hv.get(3,0):>3} | {hv.get(4,0):>3} | {hv.get(5,0):>3} | T{nt}")

    print("\n🧠 AGENT 9 (THE GAFFER): FINAL CAPTAIN CHOICE")
    c1 = res['gaffer_picks'][0]
    print(f" 🏆 PRIMARY: {c1['name']} (Robust Score: {c1['score']:.1f})")
    if len(res['gaffer_picks']) > 1:
        c2 = res['gaffer_picks'][1]
        print(f" 🥈 SECONDARY: {c2['name']} (Robust Score: {c2['score']:.1f})")

if __name__ == "__main__": main()
