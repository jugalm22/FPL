/* ===== FPL Dashboard — Application Logic ===== */

const API_BASE = '';
let pollTimer = null;

// Load saved config on startup
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        const cfg = await resp.json();
        if (cfg.last_entry_id) document.getElementById('entryId').value = cfg.last_entry_id;
        if (cfg.last_fy) document.getElementById('season').value = cfg.last_fy;
    } catch (e) { /* config not available yet */ }
});

// --- Run Pipeline ---
async function runPipeline() {
    const entryId = document.getElementById('entryId').value.trim();
    const gameweek = document.getElementById('gameweek').value.trim() || 'latest';
    const season = document.getElementById('season').value.trim() || '2024-25';

    if (!entryId) {
        setStatus('error', 'Please enter your FPL Entry ID');
        return;
    }

    // UI state: loading
    const btn = document.getElementById('runBtn');
    btn.classList.add('loading');
    btn.textContent = '⏳ Running...';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('results').style.display = 'none';
    document.getElementById('loadingSkeleton').classList.add('visible');
    setStatus('running', 'Pipeline started — Agents 1→10 analyzing...');

    try {
        const resp = await fetch(`${API_BASE}/api/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entry_id: entryId, gameweek: gameweek, fy: season })
        });
        const data = await resp.json();

        if (resp.status === 409) {
            setStatus('running', data.message);
        }

        // Start polling
        startPolling();
    } catch (e) {
        setStatus('error', `Connection error: ${e.message}`);
        btn.classList.remove('loading');
        btn.textContent = '▶ Run Analysis';
    }
}

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
        try {
            const resp = await fetch(`${API_BASE}/api/status`);
            const data = await resp.json();

            if (data.status === 'running') {
                setStatus('running', 'Agents processing... please wait');
            } else if (data.status === 'done' || data.status === 'error') {
                clearInterval(pollTimer);
                pollTimer = null;

                const btn = document.getElementById('runBtn');
                btn.classList.remove('loading');
                btn.textContent = '▶ Run Analysis';
                document.getElementById('loadingSkeleton').classList.remove('visible');

                if (data.status === 'error') {
                    setStatus('error', `Error: ${data.data?._error || 'Unknown error'}`);
                } else {
                    setStatus('done', 'Analysis complete ✓');
                    renderResults(data.data);
                }
            }
        } catch (e) {
            // keep polling
        }
    }, 2000);
}

function setStatus(type, message) {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    dot.className = 'status-dot ' + type;
    text.textContent = message;
}

// --- Render Results ---
function renderResults(res) {
    document.getElementById('results').style.display = 'block';

    renderGaffer(res);
    renderCaptainPicks(res);
    renderNPA(res);
    renderScout(res);
    renderSpecialist(res);
    renderRules(res);
}

// --- Agent 10: Gaffer ---
function renderGaffer(res) {
    const gaffer = res.gaffer_picks || [];
    const el = document.getElementById('gafferCard');

    if (!gaffer.length) {
        el.innerHTML = '<p style="color: var(--text-muted)">No captain picks could be determined.</p>';
        return;
    }

    let html = '';
    gaffer.forEach((pick, i) => {
        html += `
            <div class="captain-pick">
                <div class="label">${i === 0 ? '🏆 PRIMARY CAPTAIN' : '🥈 VICE CAPTAIN'}</div>
                <div class="name">${pick.name}</div>
                <div class="score">Robust Score: <span>${pick.score.toFixed(1)}</span></div>
                <div class="logic-box">
                    <strong>Logic:</strong> ${pick.logic || 'N/A'}
                </div>
            </div>
        `;
    });
    el.innerHTML = html;
}

// --- Agent 6: Captain Picks ---
function renderCaptainPicks(res) {
    const picks = res.top_picks?.form_picks || [];
    const el = document.getElementById('captainCard');

    if (!picks.length) {
        el.innerHTML = '<p style="color: var(--text-muted)">No captain analysis data available.</p>';
        return;
    }

    let html = `<table class="data-table">
        <thead><tr>
            <th>#</th><th>Player</th><th>Position</th><th>Form (Avg)</th><th>ICT (Avg)</th><th>xG</th><th>Cost</th>
        </tr></thead><tbody>`;
    picks.forEach((p, i) => {
        html += `<tr>
            <td>${i + 1}</td>
            <td class="player-name">${p.name}</td>
            <td><span class="pos-badge pos-${p.pos_name}">${p.pos_name}</span></td>
            <td class="${valClass(p.form, 6, 3)}">${p.form.toFixed(1)}</td>
            <td class="${valClass(p.ict, 50, 20)}">${p.ict.toFixed(1)}</td>
            <td>${(p.xg || 0).toFixed(2)}</td>
            <td>£${p.cost.toFixed(1)}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

// --- Agent 7: NPA ---
function renderNPA(res) {
    const npa = res.npa_picks || {};
    const el = document.getElementById('npaCard');
    const posOrder = ['GKP', 'DEF', 'MID', 'FWD'];
    const posColors = { GKP: 'var(--accent-gold)', DEF: 'var(--accent-teal)', MID: 'var(--accent-primary)', FWD: 'var(--accent-rose)' };

    let html = '<div class="npa-grid">';
    posOrder.forEach(pos => {
        const players = npa[pos] || [];
        html += `<div class="npa-cell">
            <div class="pos-label" style="color: ${posColors[pos]}">${pos}</div>`;
        if (players.length === 0) {
            html += '<div class="player-item" style="color: var(--text-muted)">No data</div>';
        }
        players.forEach(p => {
            html += `<div class="player-item">
                <span>${p.name}</span>
                <span class="pts">${p.last_pts ?? '?'} (GW) · ${p.p4_pts ?? '?'} (L4)</span>
            </div>`;
        });
        html += '</div>';
    });
    html += '</div>';
    el.innerHTML = html;
}

// --- Agent 8: Scout ---
// --- Table Sorting Logic ---
let currentTableData = { scout: [], specialist: [] };
let sortConfig = { scout: { key: null, asc: false }, specialist: { key: null, asc: false } };

function renderScout(res) {
    const data = res.scout_picks || [];
    currentTableData.scout = data;
    const el = document.getElementById('scoutCard');
    if (!data.length) { el.innerHTML = '<p>No data</p>'; return; }
    
    updateTable('scout');
}

function renderSpecialist(res) {
    const data = res.specialist_picks || [];
    currentTableData.specialist = data;
    const el = document.getElementById('specialistCard');
    if (!data.length) { el.innerHTML = '<p>No data</p>'; return; }

    updateTable('specialist');
}

function updateTable(type) {
    let data = [...currentTableData[type]];
    const config = sortConfig[type];
    const el = document.getElementById(type + 'Card');

    // Apply Filters for Scout
    if (type === 'scout') {
        const nameFilter = document.getElementById('scoutNameFilter').value.toLowerCase();
        const posFilter = document.getElementById('scoutPosFilter').value;
        const statusFilter = document.getElementById('scoutStatusFilter').value;

        if (nameFilter) {
            data = data.filter(p => (p.name || '').toLowerCase().includes(nameFilter));
        }
        if (posFilter !== 'ALL') {
            data = data.filter(p => p.pos_name === posFilter);
        }
        if (statusFilter !== 'ALL') {
            if (statusFilter === 'SQUAD') data = data.filter(p => p.in_squad);
            if (statusFilter === 'MARKET') data = data.filter(p => !p.in_squad);
        }
    }

    if (config.key) {
        data.sort((a, b) => {
            const v1 = a[config.key];
            const v2 = b[config.key];
            if (v1 < v2) return config.asc ? -1 : 1;
            if (v1 > v2) return config.asc ? 1 : -1;
            return 0;
        });
    }

    if (type === 'scout') {
        const wrapper = document.getElementById('scoutTableWrapper');
        let html = `<table class="data-table">
            <thead><tr>
                <th onclick="sortTable('scout', 'name')">Player ${getSortIcon('scout', 'name')}</th>
                <th>Status</th>
                <th onclick="sortTable('scout', 'pos_name')">Pos ${getSortIcon('scout', 'pos_name')}</th>
                <th onclick="sortTable('scout', 'form')">Form ${getSortIcon('scout', 'form')}</th>
                <th onclick="sortTable('scout', 'ict')">ICT ${getSortIcon('scout', 'ict')}</th>
                <th onclick="sortTable('scout', 'ppv')">PPV ${getSortIcon('scout', 'ppv')}</th>
                <th onclick="sortTable('scout', 'xg')">xG ${getSortIcon('scout', 'xg')}</th>
                <th onclick="sortTable('scout', 'cost')">Cost ${getSortIcon('scout', 'cost')}</th>
            </tr></thead><tbody>`;
        
        if (data.length === 0) {
            html += '<tr><td colspan="8" style="text-align:center; padding: 20px; color: var(--text-muted)">No players match filters</td></tr>';
        }

        data.slice(0, 25).forEach(p => {
            const squadBadge = p.in_squad ? '<span class="badge badge-squad">IN SQUAD</span>' : '<span class="text-muted">Market</span>';
            html += `<tr>
                <td class="player-name">${truncate(p.name, 22)}</td>
                <td>${squadBadge}</td>
                <td><span class="pos-badge pos-${p.pos_name}">${p.pos_name}</span></td>
                <td class="${valClass(p.form, 6, 3)}">${p.form.toFixed(1)}</td>
                <td class="${valClass(p.ict, 50, 20)}">${p.ict.toFixed(1)}</td>
                <td class="${valClass(p.ppv, 15, 8)}">${p.ppv.toFixed(1)}</td>
                <td>${(p.xg || 0).toFixed(2)}</td>
                <td>£${p.cost.toFixed(1)}</td>
            </tr>`;
        });
        html += '</tbody></table>';
        wrapper.innerHTML = html;
    } else {
        let html = `<table class="data-table">
            <thead><tr>
                <th onclick="sortTable('specialist', 'name')">Player ${getSortIcon('specialist', 'name')}</th>
                <th onclick="sortTable('specialist', 'w_score')">W.Score ${getSortIcon('specialist', 'w_score')}</th>
                <th>T1</th><th>T2</th><th>T3</th><th>T4</th><th>T5</th>
                <th onclick="sortTable('specialist', 'next_tier')">Next ${getSortIcon('specialist', 'next_tier')}</th>
            </tr></thead><tbody>`;
        data.slice(0, 15).forEach(p => {
            const h = p.hist || {};
            const nt = p.next_tier || 3;
            html += `<tr>
                <td class="player-name">${truncate(p.name, 22)}</td>
                <td class="${valClass(p.w_score, 6, 3)}">${p.w_score.toFixed(2)}</td>
                <td>${h['1'] || 0}</td><td>${h['2'] || 0}</td><td>${h['3'] || 0}</td><td>${h['4'] || 0}</td><td>${h['5'] || 0}</td>
                <td><span class="tier-badge tier-${nt}">T${nt}</span></td>
            </tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    }
}

function sortTable(type, key) {
    if (sortConfig[type].key === key) {
        sortConfig[type].asc = !sortConfig[type].asc;
    } else {
        sortConfig[type].key = key;
        sortConfig[type].asc = false; // default desc for stats
    }
    updateTable(type);
}

function getSortIcon(type, key) {
    if (sortConfig[type].key !== key) return '↕';
    return sortConfig[type].asc ? '↑' : '↓';
}

// --- Agent 1: Rules ---
function renderRules(res) {
    const rules = res.rules_summary || 'No rules data available.';
    document.getElementById('rulesCard').innerHTML = `<p>${rules}</p>`;
}

// --- Utilities ---
function valClass(val, high, mid) {
    if (val >= high) return 'val-high';
    if (val >= mid) return 'val-mid';
    return 'val-low';
}

function truncate(str, len) {
    return str.length > len ? str.substring(0, len) + '…' : str;
}
