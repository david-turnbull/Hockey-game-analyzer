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
    
    // If we switched to shotmap tab, resize Plotly plot to fit container correctly
    if (tabId === 'tab-shotmap') {
        const plotEl = document.getElementById('shot-map-plot');
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

// Interactive Shot Map Logic
document.addEventListener("DOMContentLoaded", () => {
    if (typeof GAME_ID !== 'undefined') {
        initShotMap();
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
                text: list.map(s => {
                    const goalDetail = s.outcome === "Goal" ? `<b>GOAL!</b><br>` : "";
                    const goalieText = s.goalie_name !== "None" ? `<br>Goalie: ${s.goalie_name}` : "";
                    const xgText = s.xg !== undefined && s.xg !== null ? `<br>xG: ${s.xg.toFixed(4)}` : "";
                    return `${goalDetail}Shooter: ${s.shooter_name} (${s.team_abbrev})` +
                           `${goalieText}<br>Shot: ${s.shot_type}` +
                           `<br>Dist: ${Math.round(s.distance)} ft &nbsp; Angle: ${Math.round(s.angle)}°` +
                           `<br>P${s.period} - ${s.period_time} &nbsp; Strength: ${s.strength_state}` +
                           `${xgText}`;
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
                    size: 13,
                    color: '#10b981',
                    line: { width: 1, color: '#ffffff' }
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
                    size: 8,
                    color: '#38bdf8'
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
                    size: 8,
                    color: '#f59e0b'
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
                    size: 8,
                    color: '#ef4444'
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
