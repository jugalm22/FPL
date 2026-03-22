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
    cur_gw = int(state['gameweek'])
    try:
        raw = pd.read_csv(os.path.join(repo, "data", fy, "players_raw.csv"))
        fix = pd.read_csv(os.path.join(repo, "data", fy, "fixtures.csv"))
        el_to_team: Dict[int, int] = cast(Dict[int, int], dict(zip(raw['id'].astype(int), raw['team'].astype(int))))
        el_to_pos: Dict[int, int] = cast(Dict[int, int], dict(zip(raw['id'].astype(int), raw['element_type'].astype(int))))
        pos_names: Dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

        # Pre-build fixture lookup by ID for efficient cross-referencing
        fix_by_id: Dict[int, Any] = {int(row['id']): row for _, row in fix.iterrows()}

        # Team leakage (goals conceded in last 4 finished games)
        team_leak: Dict[int, int] = {}
        for tid in range(1, 21):
            team_games = fix[((fix['team_h'] == tid) | (fix['team_a'] == tid))]
            finished = team_games[team_games['finished'] == True].tail(4)  # noqa: E712
            leak = 0
            for _, r in finished.iterrows():
                leak += int(r['team_a_score']) if int(r['team_h']) == tid else int(r['team_h_score'])
            team_leak[tid] = leak

        # Pre-compute next fixture tier per team (event > cur_gw)
        next_tier_map: Dict[int, int] = {}
        future_fix = fix[fix['event'].notna()].copy()
        future_fix['event_int'] = future_fix['event'].astype(float).astype(int)
        future_fix = future_fix[future_fix['event_int'] > cur_gw].sort_values('event_int')
        for tid in range(1, 21):
            team_next = future_fix[(future_fix['team_h'].astype(int) == tid) | (future_fix['team_a'].astype(int) == tid)]
            if not team_next.empty:
                r0 = team_next.iloc[0]
                d = int(r0['team_h_difficulty']) if int(r0['team_h']) == tid else int(r0['team_a_difficulty'])
                next_tier_map[tid] = max(1, min(5, d))
            else:
                next_tier_map[tid] = 3  # neutral fallback

        all_players: List[Dict[str, Any]] = []
        p_dir = os.path.join(repo, "data", fy, "players")
        for folder in os.listdir(p_dir):
            path = os.path.join(p_dir, folder)
            if not os.path.isdir(path): continue
            gw_csv = os.path.join(path, "gw.csv")
            if not os.path.exists(gw_csv): continue
            try:
                p_folder = str(folder)
                p_id = int(p_folder.split('_')[-1])
                if el_to_pos.get(p_id, 9) >= 5: continue
                df = pd.read_csv(gw_csv)
                df = df.sort_values('round')
                past = df[df['round'] <= cur_gw]
                if past.empty: continue
                latest_val = float(past['value'].iloc[-1] / 10.0)
                total_pts = int(past['total_points'].sum())
                p4 = past.tail(4)
                tid_int = int(el_to_team.get(p_id, 0))

                # --- T1-T5: Full season points vs each difficulty tier ---
                hist: Dict[int, int] = {d: 0 for d in range(1, 6)}
                counts: Dict[int, int] = {d: 0 for d in range(1, 6)}
                played = past[past['minutes'] > 1]
                for _, r in played.iterrows():
                    fid = int(r['fixture'])
                    f_row = fix_by_id.get(fid)
                    if f_row is None: continue
                    d = int(f_row['team_h_difficulty']) if bool(r['was_home']) else int(f_row['team_a_difficulty'])
                    if 1 <= d <= 5:
                        hist[d] += int(r['total_points'])
                        counts[d] += 1

                # Weighted Difficulty Score: Σ(pts × difficulty) / Σ(difficulty × count)
                num = sum(hist[d] * d for d in range(1, 6))
                den = sum(counts[d] * d for d in range(1, 6))
                w_score = float(num / den) if den > 0 else 0.0

                # xG from last 4
                xg = float(p4['expected_goals'].astype(float).sum()) if 'expected_goals' in p4.columns else 0.0

                # Explicitly cast to standard Python int for JSON serialization
                p4_pts = int(p4['total_points'].sum())
                last_pts = int(past['total_points'].iloc[-1])
                all_players.append({
                    'id': int(p_id), 'name': p_folder.rsplit('_', 1)[0],
                    'team': int(tid_int), 'pos': int(el_to_pos.get(p_id, 3)),
                    'pos_name': str(pos_names.get(int(el_to_pos.get(p_id, 0)), "Unknown")),
                    'form': float(p4['total_points'].mean()), 'ict': float(p4['ict_index'].mean()),
                    'p4_pts': p4_pts, 'last_pts': last_pts, 'xg': float(xg), 'hauls': int(len(p4[p4['total_points'] > 8])),
                    'cost': float(latest_val), 'total_pts': int(total_pts),
                    'ppv': float(total_pts / latest_val) if latest_val > 0 else 0.0,
                    'leak': int(team_leak.get(tid_int, 0)),
                    'hist': hist, 'counts': counts, 'w_score': float(w_score),
                    'next_tier': int(next_tier_map.get(tid_int, 3)),
                    'l2_form': float(past.tail(2)['total_points'].mean())
                })
            except: continue

        # Per-difficulty top 3 ranks (used by Gaffer)
        ranks: Dict[int, Dict[str, int]] = {}
        for d in range(1, 6):
            sorted_tier = sorted(all_players, key=lambda x: x['hist'].get(d, 0), reverse=True)
            ranks[d] = {p['name']: i+1 for i, p in enumerate(sorted_tier[:3])}

        print(f"   ✅ Processed metadata for {len(all_players)} players.")
        return {"harvester_data": {"all_players": all_players, "team_leak": team_leak, "ranks": ranks, "fixtures": fix}}
    except Exception as e:
        return {"errors": [f"Harvester Error: {str(e)}"]}

# --- Agent 6: The Captain ---
def captain_agent(state: FPLState):
    print("🤖 Agent 6 (The Captain): Analyzing Captaincy Picks...")
    h = cast(Dict[str, Any], state['harvester_data'])
    squad_ids = cast(List[int], state['squad_ids'])
    all_players = cast(List[Dict[str, Any]], h.get('all_players', []))
    squad_stats = [p for p in all_players if p['id'] in squad_ids]
    form_picks = list(itertools.islice(sorted(squad_stats, key=lambda x: float(x.get('form', 0)), reverse=True), 3))
    ict_picks = list(itertools.islice(sorted(squad_stats, key=lambda x: float(x.get('ict', 0)), reverse=True), 3))
    return {"top_picks": {"form_picks": form_picks, "ict_picks": ict_picks}}

# --- Agent 7: Agent NPA ---
def npa_agent(state: FPLState):
    print("🤖 Agent 7 (The NPA): Analyzing Positional Gaps...")
    h = cast(Dict[str, Any], state['harvester_data'])
    squad_ids = cast(List[int], state['squad_ids'])
    all_players = cast(List[Dict[str, Any]], h.get('all_players', []))
    squad_stats = [p for p in all_players if int(p.get('id', 0)) in squad_ids]
    npa_picks: Dict[str, List[Dict[str, Any]]] = {}
    for p_type in ["GKP", "DEF", "MID", "FWD"]:
        pos_list = [p for p in squad_stats if p.get('pos_name') == p_type]
        # Sort by last 4 gameweek total points as priority (ASCENDING for bottom 3)
        # We also prioritize those with lower total points if L4 is tied
        sorted_pos = sorted(
            pos_list, 
            key=lambda x: (int(x.get('p4_pts', 0)), int(x.get('total_pts', 0)))
        )
        npa_picks[p_type] = list(itertools.islice(sorted_pos, 3))
    return {"npa_picks": npa_picks}

# --- Agent 8: The Scout ---
def scout_agent(state: FPLState):
    print("🤖 Agent 8 (The Scout): Scanning Global FPL Market...")
    h = cast(Dict[str, Any], state['harvester_data'])
    all_p = cast(List[Dict[str, Any]], h.get('all_players', []))
    
    # Top 10 by each metric
    t_form = list(itertools.islice(sorted(all_p, key=lambda x: float(x.get('form', 0)), reverse=True), 10))
    t_ict = list(itertools.islice(sorted(all_p, key=lambda x: float(x.get('ict', 0)), reverse=True), 10))
    t_ppv = list(itertools.islice(sorted(all_p, key=lambda x: float(x.get('ppv', 0)), reverse=True), 10))
    
    # Consolidated unique pool
    unique = {p['id']: p for p in (t_form + t_ict + t_ppv)}
    scout_picks = list(itertools.islice(sorted(unique.values(), key=lambda x: (float(x.get('form', 0)), float(x.get('ict', 0)), float(x.get('ppv', 0))), reverse=True), 25))
    
    # Mark if player is in current squad
    s_ids = {int(x) for x in cast(List[int], state.get('squad_ids', []))}
    for p in scout_picks:
        p['in_squad'] = int(p['id']) in s_ids

    return {"scout_picks": scout_picks}

# --- Agent 9: The Specialist ---
def specialist_agent(state: FPLState):
    print("🤖 Agent 9 (The Specialist): Deep Historical Analysis...")
    scout_pool = cast(List[Dict[str, Any]], state.get('scout_picks', []))
    if not scout_pool:
        # Fallback to all players if scout didn't run
        h = cast(Dict[str, Any], state['harvester_data'])
        scout_pool = cast(List[Dict[str, Any]], h['all_players'])

    # Calculate total matches played per player (sum of fixture counts across all tiers)
    for p in scout_pool:
        p['matches_played'] = sum(p.get('counts', {}).get(d, 0) for d in range(1, 6))

    # Remove outliers: filter out players with matches < 50% of median
    match_counts = sorted([p['matches_played'] for p in scout_pool])
    median_matches = match_counts[len(match_counts) // 2] if match_counts else 0
    min_threshold = max(3, median_matches // 2)  # at least 3 matches required
    filtered = [p for p in scout_pool if p['matches_played'] >= min_threshold]

    # Sort by Weighted Difficulty Score (higher = better returns against tough opponents)
    specialist_list = list(itertools.islice(sorted(filtered, key=lambda x: float(x.get('w_score', 0)), reverse=True), 15))
    return {"specialist_picks": specialist_list}

# --- Agent 10: The Gaffer ---
def gaffer_agent(state: FPLState):
    print("🤖 Agent 10 (The Gaffer): Making Final Recommendations...")
    h = cast(Dict[str, Any], state['harvester_data'])
    squad_ids_int: List[int] = [int(x) for x in state['squad_ids']]
    cur_gw = int(state['gameweek'])
    next_gw = cur_gw + 1
    all_p = cast(List[Dict[str, Any]], h['all_players'])
    squad_stats = [p for p in all_p if int(p['id']) in squad_ids_int]

    if not squad_stats:
        print("   ⚠️ Gaffer: No squad players matched. Falling back to top form players.")
        squad_stats = sorted(all_p, key=lambda x: x['form'], reverse=True)[:5]

    w = {'f_w': 8.7, 'ict_w': 2.4, 'f_s': 1.6, 'l2_f_s': 3.3, 'ict_s': 0.8, 'h_w': 48.0, 'c_w': 1.9, 'l_w': 2.4, 'b6_w': 3.9, 'home_b': 7.9, 'dgw_w': 186.0, 'hi_w': 3.5, 'p3': 5.8, 'p4': 7.9}

    top_picks = state.get('top_picks', {})
    form_names = [str(p['name']) for p in top_picks.get('form_picks', [])]
    ict_names = [str(p['name']) for p in top_picks.get('ict_picks', [])]
    ranks = cast(Dict[int, Dict[str, int]], h.get('ranks', {}))
    fix = h['fixtures']

    # Robust next-GW fixture filter
    fix_ev = fix['event'].dropna().astype(float).astype(int)
    nf = fix.loc[fix_ev.index][fix_ev == next_gw]

    gaffer_scores = []
    for p in squad_stats:
        tid = int(p['team'])
        score = 0.0
        reasoning = []
        if str(p['name']) in form_names: 
            score += float(w['f_w'])
            reasoning.append("Global Top Form")
        if str(p['name']) in ict_names: 
            score += float(w['ict_w'])
            reasoning.append("Global Top ICT Index")
        
        comp_score = float(p['form'])*float(w['f_s']) + float(p['l2_form'])*float(w['l2_f_s']) + float(p['ict'])*float(w['ict_s']) + int(p['hauls'])*float(w['h_w']) + float(p['cost'])*float(w['c_w']) + int(p['leak'])*float(w['l_w'])
        score += comp_score
        
        if int(p['pos']) == 3: score += float(w['p3'])
        if int(p['pos']) == 4: score += float(w['p4'])
        if tid in [1, 6, 12, 13, 14, 18]: 
            score += float(w['b6_w'])
            reasoning.append("Big 6 Team Bonus")

        p_fix = nf[(nf['team_h'].astype(int) == tid) | (nf['team_a'].astype(int) == tid)]
        if len(p_fix) > 1: 
            score += float(w['dgw_w'])
            reasoning.append("Double Gameweek")
        
        for _, r in p_fix.iterrows():
            is_h = int(r['team_h']) == tid
            if is_h: 
                score += float(w['home_b'])
                reasoning.append("Home Advantage")
            d = int(r['team_h_difficulty'] if is_h else r['team_a_difficulty'])
            reasoning.append(f"Fixture Difficulty: T{d}")
            rank = ranks.get(d, {}).get(str(p['name']))
            if rank: 
                score += float(w['hi_w']) - float(rank)
                reasoning.append(f"Difficulty Tier Specialist (Rank {rank})")
        
        if p['hauls'] > 0:
            reasoning.append(f"{p['hauls']} Hauls in last 4 GWs")

        gaffer_scores.append({'name': p['name'], 'score': score, 'logic': ", ".join(list(dict.fromkeys(reasoning)))})

    gaffer_sorted = sorted(gaffer_scores, key=lambda x: float(x.get('score', 0)), reverse=True)
    return {"gaffer_picks": list(itertools.islice(gaffer_sorted, 2))}

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

    print("\n" + "="*80 + "\n🎯 FINAL CAPTAINCY RECOMMENDATIONS 🎯\n" + "="*80)
    print(f"\n📋 RULES SUMMARY:\n{res['rules_summary']}")

    print("\n🔥 AGENT 6 (CAPTAIN): TOP SQUAD PICKS (Mean Last 4 GWs)")
    print(f"{'Player':<20} | {'Mean Form':<10} | {'Mean ICT':<10}")
    print("-" * 45)
    for p in res['top_picks'].get('form_picks', []):
        print(f"{p['name']:<20} | {p['form']:<10.2f} | {p['ict']:<10.2f}")

    print("\n🛡️ AGENT 7 (NPA): POSITION BOTTOM 3 (TO BENCH/SELL) — Total Season Pts")
    print(f"{'Pos':<5} | {'Players (Total Pts)':<60}")
    print("-" * 65)
    for pos, players in res.get('npa_picks', {}).items():
        p_str = ", ".join([f"{p['name']} ({p.get('last_pts', 0)}pts GW / {p.get('p4_pts', 0)}pts L4)" for p in players])
        print(f"{pos:<5} | {p_str}")

    print("\n🌍 AGENT 8 (SCOUT): GLOBAL MARKET — Top Picks (S = In Squad)")
    print(f"{'Player':<20} | {'S':<1} | {'Pos':<5} | {'Form':>6} | {'ICT':>6} | {'PPV':>6} | {'xG':>6} | {'Cost'}")
    print("-" * 75)
    scout_list = cast(List[Dict[str, Any]], res.get('scout_picks', []))
    for p in list(itertools.islice(scout_list, 25)):
        s_mark = "S" if p.get('in_squad') else " "
        print(f"{str(p['name'])[:20]:<20} | {s_mark:<1} | {p['pos_name']:<5} | {p['form']:>6.1f} | {p['ict']:>6.1f} | {p['ppv']:>6.1f} | {p['xg']:>6.2f} | £{p['cost']:<5.1f}")

    print("\n🎯 AGENT 9 (SPECIALIST): WEIGHTED DIFFICULTY SCORE — T1–T5 Season Pts & Next Fixture")
    print(f"{'Player':<20} | {'W.Score':>7} | {'T1':>4} | {'T2':>4} | {'T3':>4} | {'T4':>4} | {'T5':>4} | Next")
    print("-" * 80)
    specialist_list = cast(List[Dict[str, Any]], res.get('specialist_picks', []))
    for p in list(itertools.islice(specialist_list, 15)):
        h = p.get('hist', {})
        nt = p.get('next_tier', 3)
        print(f"{str(p['name'])[:20]:<20} | {p['w_score']:>7.2f} | {h.get(1,0):>4} | {h.get(2,0):>4} | {h.get(3,0):>4} | {h.get(4,0):>4} | {h.get(5,0):>4} | T{nt}")

    print("\n🧠 AGENT 10 (THE GAFFER): FINAL CAPTAIN CHOICE")
    gaffer = res.get('gaffer_picks', [])
    if not gaffer:
        print(" ⚠️  No captain picks could be determined. Check squad ID or season data.")
    else:
        c1 = gaffer[0]
        print(f" 🏆 PRIMARY:   {c1['name']} (Robust Score: {c1['score']:.1f})")
        if len(gaffer) > 1:
            c2 = gaffer[1]
            print(f" 🥈 SECONDARY: {c2['name']} (Robust Score: {c2['score']:.1f})")

if __name__ == "__main__": main()
