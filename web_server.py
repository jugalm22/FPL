"""
FPL Captain MAS — Web Server
Serves the dashboard UI and exposes the agent pipeline as a JSON API.
"""
import os, sys, json, threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Ensure UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__, static_folder='static')
CORS(app)

# Cache for the latest run result
latest_result = {}
run_lock = threading.Lock()
is_running = False

def run_pipeline(entry_id: str, gameweek: str, fy: str):
    """Run the FPL agent pipeline and return serializable results."""
    global latest_result, is_running
    # Import here to avoid circular imports
    from fpl_agent import (
        FPLState, StateGraph, END,
        ruler_agent, puller_agent, eventer_agent, mapper_agent,
        harvester_agent, captain_agent, npa_agent, scout_agent,
        specialist_agent, gaffer_agent, save_config
    )
    save_config(entry_id, fy)

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

    compiled = graph.compile()
    res = compiled.invoke({
        "entry_id": entry_id, "gameweek": gameweek, "fy": fy,
        "errors": [], "squad_ids": [], "player_paths": [],
        "top_picks": {}, "npa_picks": {},
        "scout_picks": [], "specialist_picks": [], "gaffer_picks": [],
        "rules_summary": "", "repo_path": "", "harvester_data": {}
    })

    # Serialize — strip non-JSON-serializable fields (like DataFrames)
    def clean(obj):
        if isinstance(obj, dict):
            return {str(k): clean(v) for k, v in obj.items() if k != 'fixtures'}
        elif isinstance(obj, list):
            return [clean(i) for i in obj]
        elif hasattr(obj, 'item'): # Handle numpy scalars
            return obj.item()
        elif isinstance(obj, (int, float, str, bool)) or obj is None:
            return obj
        else:
            try:
                json.dumps(obj)
                return obj
            except:
                return str(obj)

    return clean(res)


# ---------- API Routes ----------

@app.route('/api/config', methods=['GET'])
def get_config():
    config_file = "config.json"
    if os.path.exists(config_file):
        with open(config_file) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route('/api/run', methods=['POST'])
def run_agents():
    global latest_result, is_running
    if is_running:
        return jsonify({"status": "busy", "message": "Pipeline is already running..."}), 409

    data = request.json or {}
    entry_id = data.get('entry_id', '')
    gameweek = data.get('gameweek', 'latest')
    fy = data.get('fy', '2024-25')

    def background_run():
        global latest_result, is_running
        with run_lock:
            is_running = True
            try:
                latest_result = run_pipeline(entry_id, gameweek, fy)
                latest_result['_status'] = 'done'
            except Exception as e:
                latest_result = {'_status': 'error', '_error': str(e)}
            finally:
                is_running = False

    t = threading.Thread(target=background_run, daemon=True)
    t.start()
    return jsonify({"status": "started", "message": "Pipeline started. Poll /api/status for results."})


@app.route('/api/status', methods=['GET'])
def get_status():
    if is_running:
        return jsonify({"status": "running"})
    if not latest_result:
        return jsonify({"status": "idle"})
    return jsonify({"status": latest_result.get('_status', 'done'), "data": latest_result})


# ---------- Static File Routes ----------

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)


if __name__ == '__main__':
    print("🚀 FPL Dashboard starting at http://localhost:5000")
    app.run(debug=True, port=5000, use_reloader=False)
