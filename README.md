# Multi-Agent System: Optimal FPL Captaincy Selector

This project uses **LangGraph** to model a Multi-Agent System (MAS) flow that automates the selection of the best Fantasy Premier League (FPL) captain for a given Gameweek.

## Components / Agents
1. **The Ruler:** Scrapes `https://fantasy.premierleague.com/help/rules` to understand the FPL constraints & chip rules. Uses LLM summarization.
2. **The Puller:** Syncs the latest repository database from `vaastav/Fantasy-Premier-League`. 
3. **The Eventer:** Queries the official FPL API to grab the 15-player squad elements connected to your personal entry ID.
4. **The Mapper:** Translates elements to specific folder structures inside `data/{FY}/players`.
5. **The Captain:** Analyzes each player's latest `gw.csv` dataframe to calculate the Form & ICT index means of their last 4 rows, providing the top 3 optimal picks.

## Setup Requirements

1. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

    ```

## Usage

Simply run the agent framework:

```bash
python fpl_agent.py
```

Prompts will appear for:
- **Entry ID:** Your FPL team's ID
- **Gameweek:** Supports `latest` to auto-resolve current gameweek
- **Financial Year:** Default `2024-25` based on Vaastav's repository convention.

Next time you run, it will remember your ID & FY using the `config.json` memory persistence.
