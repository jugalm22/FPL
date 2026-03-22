# 🏆 FPL Captain Multi-Agent System (MAS)

A **10-Agent AI Pipeline** built with [LangGraph](https://github.com/langchain-ai/langgraph) that automatically identifies the optimal Fantasy Premier League (FPL) captain, scouts global market targets, and performs advanced fixture-difficulty analysis — all from your personal FPL squad.

---

## 🤖 Agent Architecture

| # | Agent | Role |
|---|-------|------|
| 1 | **The Ruler** | Scrapes FPL rules from `fantasy.premierleague.com/help/rules`. Summarizes captaincy multipliers via GPT-4o (if API key available). |
| 2 | **The Puller** | Clones or pulls the latest data from [`vaastav/Fantasy-Premier-League`](https://github.com/vaastav/Fantasy-Premier-League). |
| 3 | **The Eventer** | Calls the FPL API to fetch the 15-player squad from your personal Entry ID. Auto-resolves `latest` gameweek. |
| 4 | **The Mapper** | Translates FPL API element IDs to local player directories under `data/{FY}/players/`. |
| 5 | **The Harvester** | Central Data Scientist. Reads every player folder in the league, computes form, ICT, xG, PPV, historical difficulty bins, Weighted Difficulty Score, and next fixture tier. All downstream agents consume this shared data pool. |
| 6 | **The Captain** | Filters the harvested data to your squad and ranks the **Top 3 captaincy candidates** by Mean Form and Mean ICT (last 4 GWs). |
| 7 | **The NPA** | Net Point Aggregator. Identifies the **bottom 3 performers** in each position (GKP, DEF, MID, FWD) by total season points — your transfer candidates. |
| 8 | **The Scout** | Global FPL Market Analyst. Performs a league-wide scan across **Form, ICT Index, PPV, and xG** to surface the best-value targets in the market. Outputs a consolidated Top 15 table deduped across all three primary metrics. |
| 9 | **The Specialist** | Difficulty & Weighted Returns Analyst. Cross-references every player's `gw.csv` with `fixtures.csv` to calculate a **Weighted Difficulty Score**. Outputs a tier breakdown (T1–T5 points), the Weighted Rank, and the **Next Fixture tier** for each player. |
| 10 | **The Gaffer** | Final Decision Engine. Combines outputs from all prior agents using a calibrated scoring model (form, ICT, hauls, fixture difficulty, home advantage, DGW bonus, Big-6 premium) to produce the **Primary and Secondary captain picks**. |

---

## 📊 Agent Output Reference

### Agent 6 — The Captain
```
Player               | Mean Form  | Mean ICT
Mohamed Salah        | 9.50       | 62.30
```

### Agent 7 — The NPA (Bottom 3 per Position)
```
Pos   | Players (Total Season Pts)
DEF   | Player A (14), Player B (17), Player C (19)
```

### Agent 8 — The Scout (Global Top 15)
```
Player               | Pos   |   Form |    ICT |    PPV |     xG | Cost
Mohamed Salah        | MID   |   9.5  |  62.3  |  15.4  |   2.50 | £13.1
```
- **Form**: Mean `total_points` — last 4 GWs
- **ICT**: Mean `ict_index` — last 4 GWs
- **PPV**: `Sum of season total_points ÷ Latest value` (price efficiency)
- **xG**: Sum of `expected_goals` — last 4 GWs

### Agent 9 — The Specialist (Weighted Tier Table, Top 15)
```
Player               | W.Rank |  T1 |  T2 |  T3 |  T4 |  T5 | Next
Mohamed Salah        |   8.72 |  12 |  24 |  18 |   7 |   0 | T3
```
- **W.Rank**: Weighted Difficulty Score = `Σ(pts × difficulty) / Σ(difficulty × fixture count)`. Higher = better under pressure.
- **T1–T5**: Points scored against each fixture difficulty tier
- **Next**: The difficulty tier of the player's upcoming GW fixture

### Agent 10 — The Gaffer
```
🏆 PRIMARY:   Mohamed Salah  (Robust Score: 214.3)
🥈 SECONDARY: Erling Haaland (Robust Score: 198.7)
```

---

## ⚙️ Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. (Optional) Set OpenAI API Key for Agent 1 LLM summarization
```bash
set OPENAI_API_KEY=sk-...
```

### 3. Run
```bash
python fpl_agent.py
```

You will be prompted for:
| Prompt | Description |
|--------|-------------|
| `Entry ID` | Your FPL team ID (from the URL on the FPL website) |
| `Gameweek` | Target GW number, or `latest` to auto-resolve |
| `Season` | E.g. `2024-25` (matches Vaastav repo convention) |

Your Entry ID and Season are saved to `config.json` — subsequent runs will pre-fill these values.

---

## 📦 Requirements

```
langgraph
langchain
langchain_openai
langchain-core
requests
beautifulsoup4
pandas
```

---

## 📁 Directory Structure

```
FPL/
├── fpl_agent.py          # Main MAS pipeline
├── config.json           # Persisted user inputs (Entry ID, Season)
├── requirements.txt
├── README.md
└── Fantasy-Premier-League/   # Auto-cloned from vaastav/Fantasy-Premier-League
    └── data/
        └── 2024-25/
            ├── fixtures.csv
            ├── players_raw.csv
            └── players/
                └── Mohamed_Salah_302/
                    └── gw.csv
```

---

## 🛠️ Tech Stack

- **Python 3.10+**
- **LangGraph** — Multi-agent state graph orchestration
- **Pandas** — Data processing
- **BeautifulSoup4** — FPL rules scraping
- **LangChain / OpenAI** — Optional LLM rule summarization
- **Vaastav's FPL Dataset** — Historical GW-level data

---

## 📝 License

MIT
