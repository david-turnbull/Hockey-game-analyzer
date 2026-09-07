// PuckLens Game Dashboard Client Script
// Decoupled from main.js for cleaner frontend separation

// Tab Switcher Logic
window.switchTab = function(event, tabId) {
    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(el => {
        el.style.display = 'none';
    });
    // Remove active class from all tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    // Show selected tab content
    document.getElementById(tabId).style.display = 'block';
    // Add active class to clicked button
    event.currentTarget.classList.add('active');
    
    // If we switched to shotmap or timeline tab, resize Plotly plot to fit container correctly
    if (tabId === 'tab-shotmap') {
        const plotEl = document.getElementById('shot-map-plot');
        if (plotEl && window.Plotly) {
            window.Plotly.Plots.resize(plotEl);
        }
    } else if (tabId === 'tab-timeline') {
        const plotEl = document.getElementById('xg-timeline-plot');
        if (plotEl && window.Plotly) {
            window.Plotly.Plots.resize(plotEl);
        }
    }
};

// Timeline Filters Logic
window.filterTimeline = function() {
    const showGoal = document.getElementById('tl-show-goal').checked;
    const showPenalty = document.getElementById('tl-show-penalty').checked;
    const showHit = document.getElementById('tl-show-hit').checked;
    const showFaceoff = document.getElementById('tl-show-faceoff').checked;
    const showBlock = document.getElementById('tl-show-blocked-shot').checked;
    const showMiss = document.getElementById('tl-show-missed-shot').checked;
    
    const items = document.querySelectorAll('.timeline-item');
    items.forEach(item => {
        const type = item.getAttribute('data-event-type');
        let visible = false;
        if (type === 'goal') visible = showGoal;
        else if (type === 'penalty') visible = showPenalty;
        else if (type === 'hit') visible = showHit;
        else if (type === 'faceoff') visible = showFaceoff;
        else if (type === 'blocked-shot') visible = showBlock;
        else if (type === 'missed-shot') visible = showMiss;
        
        item.style.display = visible ? 'flex' : 'none';
    });
    
    // Hide period group header if it contains no visible items
    const groups = document.querySelectorAll('.timeline-period-group');
    groups.forEach(group => {
        const visibleItems = Array.from(group.querySelectorAll('.timeline-item')).filter(i => i.style.display !== 'none');
        group.style.display = visibleItems.length > 0 ? 'block' : 'none';
    });
};

// On-Ice Reconstruct Explorer Logic
window.selectExplorerEvent = function(element) {
    document.querySelectorAll('.explorer-event-item').forEach(el => {
        el.classList.remove('active');
    });
    element.classList.add('active');
    
    const period = element.getAttribute('data-period');
    const time = element.getAttribute('data-time');
    
    document.getElementById('explorer-period').value = period;
    document.getElementById('explorer-time').value = time;
    
    const contentText = element.innerText.replace(time, '').trim();
    window.fetchOnIcePlayers(contentText);
};

window.fetchOnIcePlayers = async function(contextLabel = "") {
    const period = document.getElementById('explorer-period').value;
    const time = document.getElementById('explorer-time').value;
    
    const banner = document.getElementById('explorer-active-time-banner');
    const homeList = document.getElementById('explorer-home-players');
    const awayList = document.getElementById('explorer-away-players');
    
    if (!/^\d{1,2}:\d{2}$/.test(time)) {
        banner.textContent = "Error: Invalid time format (use MM:SS)";
        banner.style.color = "var(--danger)";
        return;
    }
    
    banner.style.color = "var(--accent-color)";
    banner.textContent = `Loading lineups for P${period} @ ${time}...`;
    
    try {
        const res = await fetch(`/api/game/${GAME_ID}/on-ice?period=${period}&time=${time}`);
        if (!res.ok) throw new Error("Failed to fetch on-ice players");
        const data = await res.json();
        
        banner.innerHTML = contextLabel 
            ? `Active Lineup at <strong>P${period} ${time}</strong> (${contextLabel})`
            : `Active Lineup at <strong>P${period} ${time}</strong>`;
            
        const renderList = (players, container) => {
            container.innerHTML = "";
            container.style.justifyContent = "flex-start";
            container.style.borderStyle = "solid";
            container.style.padding = "0.5rem";
            container.style.width = "auto";
            
            if (players.length === 0) {
                container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 2rem; font-size: 0.85rem; width: 100%;">No players reconstructed on ice</div>`;
                return;
            }
            
            players.forEach(p => {
                const row = document.createElement('div');
                row.style.display = "flex";
                row.style.justifyContent = "space-between";
                row.style.alignItems = "center";
                row.style.padding = "0.4rem 0.6rem";
                row.style.background = "rgba(255, 255, 255, 0.01)";
                row.style.border = "1px solid var(--border-color)";
                row.style.borderRadius = "4px";
                row.style.fontSize = "0.85rem";
                row.style.marginBottom = "0.25rem";
                
                row.innerHTML = `
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <span style="font-weight: 700; color: var(--accent-color); font-family: var(--font-mono); width: 25px;">#${p.number !== null ? p.number : ''}</span>
                        <span style="color: var(--text-primary); font-weight: 500;">${p.name}</span>
                    </div>
                    <span style="font-size: 0.75rem; font-weight: 600; color: var(--text-muted); background: var(--bg-secondary); padding: 0.1rem 0.3rem; border-radius: 3px;">${p.position}</span>
                `;
                container.appendChild(row);
            });
        };
        
        renderList(data.home, homeList);
        renderList(data.away, awayList);
        
    } catch (err) {
        console.error(err);
        banner.textContent = "Error loading players: " + err.message;
        banner.style.color = "var(--danger)";
    }
};

// Interactive Shot Map & Expected Goals Timeline Logic
document.addEventListener("DOMContentLoaded", () => {
    if (typeof GAME_ID !== 'undefined') {
        initShotMap();
        initXGTimeline();
    }
});

async function initShotMap() {
    const plotContainer = document.getElementById("shot-map-plot");
    const teamFilter = document.getElementById("filter-team");
    const playerFilter = document.getElementById("filter-player");
    const periodFilter = document.getElementById("filter-period");
    const outcomeFilter = document.getElementById("filter-outcome");
    const strengthFilter = document.getElementById("filter-strength");
    const normalizeToggle = document.getElementById("toggle-normalize");

    if (!plotContainer) return;

    let allShots = [];

    // 1. Fetch all shots for this game using normalized RESTful API route
    try {
        const res = await fetch(`/api/game/${GAME_ID}/shots`);
        if (!res.ok) throw new Error("Failed to fetch shots from API");
        allShots = await res.json();
    } catch (err) {
        console.error("Shot Map Load Error:", err);
        plotContainer.innerHTML = `<p style="color: var(--danger); text-align: center; padding-top: 5rem;">Failed to load shots data: ${err.message}</p>`;
        return;
    }

    // 2. Populate player dropdown dynamically
    const shooters = [...new Set(allShots.map(s => s.shooter_name))].sort();
    shooters.forEach(name => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        playerFilter.appendChild(opt);
    });

    // 3. Render plot
    function renderPlot() {
        const teamVal = teamFilter.value;
        const playerVal = playerFilter.value;
        const periodVal = periodFilter.value;
        const outcomeVal = outcomeFilter.value;
        const strengthVal = strengthFilter.value;
        const normalize = normalizeToggle.checked;

        const filtered = allShots.filter(s => {
            if (teamVal !== "all" && s.team_abbrev !== teamVal) return false;
            if (playerVal !== "all" && s.shooter_name !== playerVal) return false;
            if (periodVal !== "all" && String(s.period) !== periodVal) return false;
            if (strengthVal !== "all" && s.strength_state !== strengthVal) return false;
            
            if (outcomeVal !== "all") {
                if (outcomeVal === "sog") {
                    if (s.outcome !== "Goal" && s.outcome !== "Saved") return false;
                } else if (s.outcome !== outcomeVal) {
                    return false;
                }
            }
            return true;
        });

        const goals = filtered.filter(s => s.outcome === "Goal");
        const saves = filtered.filter(s => s.outcome === "Saved");
        const misses = filtered.filter(s => s.outcome === "Missed");
        const blocks = filtered.filter(s => s.outcome === "Blocked");

        const getCoords = (list) => {
            return {
                x: list.map(s => normalize ? s.norm_x : s.raw_x),
                y: list.map(s => normalize ? s.norm_y : s.raw_y),
                size: list.map(s => {
                    const prob = (s.xg !== undefined && s.xg !== null) ? Number(s.xg) : 0.05;
                    return Math.max(7, Math.min(26, Math.round(7 + prob * 28)));
                }),
                text: list.map(s => {
                    const xgFormatted = (s.xg !== undefined && s.xg !== null) ? Number(s.xg).toFixed(3) : "N/A";
                    const distText = (s.distance !== undefined && s.distance !== null) ? `${Math.round(s.distance)} ft` : "N/A";
                    const angleText = (s.angle !== undefined && s.angle !== null) ? `${Math.round(s.angle)}°` : "N/A";
                    const shotType = s.shot_type ? s.shot_type : "Shot";
                    return `<b>${s.shooter_name}</b><br>` +
                           `${shotType} Shot<br>` +
                           `<b>xG:</b> ${xgFormatted}<br>` +
                           `<b>Distance:</b> ${distText}<br>` +
                           `<b>Angle:</b> ${angleText}<br>` +
                           `<b>Result:</b> ${s.outcome}`;
                })
            };
        };

        const gCoords = getCoords(goals);
        const sCoords = getCoords(saves);
        const mCoords = getCoords(misses);
        const bCoords = getCoords(blocks);

        const traces = [
            {
                x: gCoords.x,
                y: gCoords.y,
                text: gCoords.text,
                mode: 'markers',
                name: 'Goal',
                hoverinfo: 'text',
                marker: {
                    symbol: 'star',
                    size: gCoords.size,
                    color: '#10b981',
                    line: { width: 1.5, color: '#ffffff' }
                }
            },
            {
                x: sCoords.x,
                y: sCoords.y,
                text: sCoords.text,
                mode: 'markers',
                name: 'Save',
                hoverinfo: 'text',
                marker: {
                    symbol: 'circle',
                    size: sCoords.size,
                    color: '#38bdf8',
                    opacity: 0.85
                }
            },
            {
                x: mCoords.x,
                y: mCoords.y,
                text: mCoords.text,
                mode: 'markers',
                name: 'Miss',
                hoverinfo: 'text',
                marker: {
                    symbol: 'diamond',
                    size: mCoords.size,
                    color: '#f59e0b',
                    opacity: 0.85
                }
            },
            {
                x: bCoords.x,
                y: bCoords.y,
                text: bCoords.text,
                mode: 'markers',
                name: 'Blocked',
                hoverinfo: 'text',
                marker: {
                    symbol: 'x',
                    size: bCoords.size,
                    color: '#ef4444',
                    opacity: 0.85
                }
            }
        ];

        const shapes = [];

        shapes.push({
            type: 'rect',
            x0: -100, y0: -42.5, x1: 100, y1: 42.5,
            line: { color: 'rgba(255, 255, 255, 0.2)', width: 2 }
        });

        if (!normalize) {
            shapes.push({
                type: 'line',
                x0: 0, y0: -42.5, x1: 0, y1: 42.5,
                line: { color: 'rgba(239, 68, 68, 0.4)', width: 3 }
            });
            shapes.push({
                type: 'line',
                x0: -25, y0: -42.5, x1: -25, y1: 42.5,
                line: { color: 'rgba(56, 189, 248, 0.4)', width: 3 }
            });
            shapes.push({
                type: 'line',
                x0: 25, y0: -42.5, x1: 25, y1: 42.5,
                line: { color: 'rgba(56, 189, 248, 0.4)', width: 3 }
            });
            shapes.push({
                type: 'circle',
                x0: -15, y0: -15, x1: 15, y1: 15,
                line: { color: 'rgba(56, 189, 248, 0.3)', width: 1.5 }
            });
            shapes.push({
                type: 'line',
                x0: -89, y0: -42.5, x1: -89, y1: 42.5,
                line: { color: 'rgba(239, 68, 68, 0.3)', width: 1.5 }
            });
            shapes.push({
                type: 'path',
                path: 'M -89 -4 A 4 4 0 0 1 -89 4 Z',
                line: { color: 'rgba(56, 189, 248, 0.3)', width: 1 },
                fillcolor: 'rgba(56, 189, 248, 0.05)'
            });
            shapes.push({
                type: 'rect',
                x0: -92, y0: -3, x1: -89, y1: 3,
                line: { color: 'rgba(255, 255, 255, 0.3)', width: 1 }
            });
        } else {
            shapes.push({
                type: 'line',
                x0: 0, y0: -42.5, x1: 0, y1: 42.5,
                line: { color: 'rgba(255, 255, 255, 0.2)', width: 1.5 }
            });
        }

        shapes.push({
            type: 'line',
            x0: 89, y0: -42.5, x1: 89, y1: 42.5,
            line: { color: 'rgba(239, 68, 68, 0.4)', width: 1.5 }
        });
        shapes.push({
            type: 'path',
            path: 'M 89 -4 A 4 4 0 0 0 89 4 Z',
            line: { color: 'rgba(56, 189, 248, 0.3)', width: 1 },
            fillcolor: 'rgba(56, 189, 248, 0.05)'
        });
        shapes.push({
            type: 'rect',
            x0: 89, y0: -3, x1: 92, y1: 3,
            line: { color: 'rgba(255, 255, 255, 0.3)', width: 1 }
        });
        const drawFaceoff = (cx, cy) => {
            shapes.push({
                type: 'circle',
                x0: cx - 15, y0: cy - 15, x1: cx + 15, y1: cy + 15,
                line: { color: 'rgba(239, 68, 68, 0.25)', width: 1.5 }
            });
            shapes.push({
                type: 'circle',
                x0: cx - 0.75, y0: cy - 0.75, x1: cx + 0.75, y1: cy + 0.75,
                fillcolor: 'rgba(239, 68, 68, 0.5)',
                line: { width: 0 }
            });
        };
        drawFaceoff(69, 22);
        drawFaceoff(69, -22);

        if (!normalize) {
            drawFaceoff(-69, 22);
            drawFaceoff(-69, -22);
        }

        const layout = {
            title: {
                text: `${normalize ? 'Normalized Right-Attack' : 'Full Rink'} Shot Distribution (${filtered.length} attempts)`,
                font: { color: '#f8fafc', size: 14 }
            },
            plot_bgcolor: '#0f172a',
            paper_bgcolor: '#0b0f19',
            shapes: shapes,
            xaxis: {
                range: normalize ? [0, 100] : [-100, 100],
                showgrid: false,
                zeroline: false,
                showticklabels: false,
                fixedrange: true
            },
            yaxis: {
                range: [-42.5, 42.5],
                showgrid: false,
                zeroline: false,
                showticklabels: false,
                scaleanchor: 'x',
                scaleratio: 1,
                fixedrange: true
            },
            margin: { l: 20, r: 20, t: 40, b: 20 },
            legend: {
                font: { color: '#cbd5e1' },
                orientation: 'h',
                x: 0.5,
                xanchor: 'center',
                y: -0.05
            }
        };

        const config = {
            responsive: true,
            displayModeBar: false
        };

        Plotly.newPlot(plotContainer, traces, layout, config);
    }

    teamFilter.addEventListener("change", renderPlot);
    playerFilter.addEventListener("change", renderPlot);
    periodFilter.addEventListener("change", renderPlot);
    outcomeFilter.addEventListener("change", renderPlot);
    strengthFilter.addEventListener("change", renderPlot);
    normalizeToggle.addEventListener("change", renderPlot);

    renderPlot();
}

// ==========================================
// Milestone 11: Expected Goals Timeline
// ==========================================
async function initXGTimeline() {
    const plotContainer = document.getElementById("xg-timeline-plot");
    if (!plotContainer) return;

    let currentSituation = 'all';

    async function loadAndRender(situation) {
        try {
            const res = await fetch(`/api/games/${GAME_ID}/xg_timeline?situation=${situation}`);
            if (!res.ok) throw new Error("Failed to fetch timeline data");
            const data = await res.json();

            renderTimelinePlot(data);
        } catch (err) {
            console.error("xG Timeline Error:", err);
            plotContainer.innerHTML = `<p style="color: var(--danger); text-align: center; padding: 2rem;">Failed to load xG timeline: ${err.message}</p>`;
        }
    }

    function renderTimelinePlot(data) {
        const homeAbbrev = data.home_team.abbrev;
        const awayAbbrev = data.away_team.abbrev;
        const homeTotal = data.home_team.total_xg;
        const awayTotal = data.away_team.total_xg;

        // Group timeline points
        const times = data.timeline.map(t => (t.seconds / 60.0).toFixed(2));
        const homeXG = data.timeline.map(t => t.home_xg);
        const awayXG = data.timeline.map(t => t.away_xg);
        const hoverTextsHome = data.timeline.map(t => `<b>${homeAbbrev}</b><br>Time: P${t.period} ${t.period_time}<br>Cumulative xG: ${t.home_xg}`);
        const hoverTextsAway = data.timeline.map(t => `<b>${awayAbbrev}</b><br>Time: P${t.period} ${t.period_time}<br>Cumulative xG: ${t.away_xg}`);

        const traces = [
            {
                x: times,
                y: homeXG,
                text: hoverTextsHome,
                hoverinfo: 'text',
                mode: 'lines',
                name: `${homeAbbrev} (Home: ${homeTotal} xG)`,
                line: { shape: 'hv', color: '#38bdf8', width: 3 }
            },
            {
                x: times,
                y: awayXG,
                text: hoverTextsAway,
                hoverinfo: 'text',
                mode: 'lines',
                name: `${awayAbbrev} (Away: ${awayTotal} xG)`,
                line: { shape: 'hv', color: '#f97316', width: 3 }
            }
        ];

        // Add goal markers
        if (data.goals && data.goals.length > 0) {
            const goalTimes = data.goals.map(g => (g.seconds / 60.0).toFixed(2));
            const goalY = data.goals.map(g => g.is_home ? g.home_xg : g.away_xg);
            const goalTexts = data.goals.map(g => `<b>GOAL!</b> ${g.scorer} (${g.team_abbrev})<br>P${g.period} ${g.period_time}`);
            const goalColors = data.goals.map(g => g.is_home ? '#38bdf8' : '#f97316');

            traces.push({
                x: goalTimes,
                y: goalY,
                text: goalTexts,
                hoverinfo: 'text',
                mode: 'markers',
                name: 'Actual Goal',
                marker: {
                    symbol: 'star',
                    size: 14,
                    color: goalColors,
                    line: { width: 2, color: '#ffffff' }
                }
            });
        }

        // Period break markers at 20, 40, 60 minutes
        const maxMinute = Math.max(60, Math.ceil((times[times.length - 1] || 60) / 5) * 5);
        const shapes = [
            { type: 'line', x0: 20, x1: 20, y0: 0, y1: 1, yref: 'paper', line: { color: 'rgba(255,255,255,0.2)', dash: 'dash', width: 1 } },
            { type: 'line', x0: 40, x1: 40, y0: 0, y1: 1, yref: 'paper', line: { color: 'rgba(255,255,255,0.2)', dash: 'dash', width: 1 } },
            { type: 'line', x0: 60, x1: 60, y0: 0, y1: 1, yref: 'paper', line: { color: 'rgba(255,255,255,0.2)', dash: 'dash', width: 1 } }
        ];

        const layout = {
            plot_bgcolor: '#0f172a',
            paper_bgcolor: '#0b0f19',
            shapes: shapes,
            xaxis: {
                title: { text: 'Game Time (Minutes)', font: { color: '#94a3b8', size: 12 } },
                range: [0, maxMinute],
                tickvals: [0, 20, 40, 60],
                ticktext: ['Start', 'End P1', 'End P2', 'End P3'],
                gridcolor: 'rgba(255,255,255,0.05)',
                tickfont: { color: '#cbd5e1' }
            },
            yaxis: {
                title: { text: 'Cumulative Expected Goals (xG)', font: { color: '#94a3b8', size: 12 } },
                gridcolor: 'rgba(255,255,255,0.05)',
                tickfont: { color: '#cbd5e1' }
            },
            margin: { l: 50, r: 20, t: 30, b: 50 },
            legend: {
                font: { color: '#cbd5e1' },
                orientation: 'h',
                x: 0.5,
                xanchor: 'center',
                y: -0.2
            }
        };

        Plotly.newPlot(plotContainer, traces, layout, { responsive: true, displayModeBar: false });
    }

    // Attach situation filter listeners
    const buttons = document.querySelectorAll('[data-xg-situation]');
    buttons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            buttons.forEach(b => b.classList.remove('active'));
            e.currentTarget.classList.add('active');
            currentSituation = e.currentTarget.getAttribute('data-xg-situation');
            loadAndRender(currentSituation);
        });
    });

    loadAndRender(currentSituation);
}
