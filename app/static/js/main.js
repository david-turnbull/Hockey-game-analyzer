document.addEventListener("DOMContentLoaded", () => {
    const seasonSelect = document.getElementById("season-select");
    const teamSelect = document.getElementById("team-select");
    const gamesTableBody = document.getElementById("games-table-body");
    const gamesCount = document.getElementById("games-count");

    if (!seasonSelect || !teamSelect || !gamesTableBody) {
        return; // Diagnostics page or empty DB view
    }

    async function loadGames() {
        const season = seasonSelect.value;
        const teamId = teamSelect.value;

        if (!season || !teamId) {
            return;
        }

        // Show loading state
        gamesTableBody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">
                    Fetching games schedule...
                </td>
            </tr>
        `;
        gamesCount.textContent = "Loading...";

        try {
            const response = await fetch(`/api/games?team_id=${teamId}&season=${season}`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const games = await response.json();
            
            // Clear table
            gamesTableBody.innerHTML = "";
            gamesCount.textContent = `${games.length} Games`;

            if (games.length === 0) {
                gamesTableBody.innerHTML = `
                    <tr>
                        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">
                            No games ingested in the database for this team/season.
                        </td>
                    </tr>
                `;
                return;
            }

            // Populate table rows
            games.forEach(game => {
                const tr = document.createElement("tr");

                // Date
                const tdDate = document.createElement("td");
                tdDate.textContent = game.date;
                tdDate.className = "font-mono";
                tr.appendChild(tdDate);

                // Type
                const tdType = document.createElement("td");
                tdType.textContent = game.game_type === 'R' ? 'Regular' : (game.game_type === 'P' ? 'Playoffs' : game.game_type);
                tr.appendChild(tdType);

                // Matchup
                const tdMatchup = document.createElement("td");
                const homeSpan = game.is_home ? `<strong>${game.home_team_abbrev}</strong>` : game.home_team_abbrev;
                const awaySpan = !game.is_home ? `<strong>${game.away_team_abbrev}</strong>` : game.away_team_abbrev;
                tdMatchup.innerHTML = `${awaySpan} @ ${homeSpan}`;
                tr.appendChild(tdMatchup);

                // Result
                const tdResult = document.createElement("td");
                tdResult.className = "font-mono";
                
                const isWinner = (game.is_home && game.home_score > game.away_score) || 
                                 (!game.is_home && game.away_score > game.home_score);
                const isTie = game.home_score === game.away_score;
                
                let outcomeBadge = "";
                if (isTie) {
                    outcomeBadge = `<span class="status-indicator" style="background: rgba(148, 163, 184, 0.1); color: var(--text-secondary); padding: 0.15rem 0.35rem; font-size: 0.75rem; border-radius: 3px;">T</span>`;
                } else if (isWinner) {
                    outcomeBadge = `<span class="status-indicator status-connected" style="padding: 0.15rem 0.35rem; font-size: 0.75rem; border-radius: 3px;">W</span>`;
                } else {
                    outcomeBadge = `<span class="status-indicator status-failed" style="padding: 0.15rem 0.35rem; font-size: 0.75rem; border-radius: 3px;">L</span>`;
                }
                
                const scoreDisplay = `${game.away_score} - ${game.home_score}`;
                tdResult.innerHTML = `<div style="display: flex; align-items: center; gap: 0.5rem;">${outcomeBadge} ${scoreDisplay}</div>`;
                tr.appendChild(tdResult);

                // Status
                const tdStatus = document.createElement("td");
                const statusClass = game.game_status.toLowerCase() === 'final' || game.game_status.toLowerCase() === 'off' 
                                    ? 'status-connected' : 'status-failed';
                tdStatus.innerHTML = `<span class="status-indicator ${statusClass}">${game.game_status}</span>`;
                tr.appendChild(tdStatus);

                // Action
                const tdAction = document.createElement("td");
                tdAction.style.textAlign = "right";
                tdAction.innerHTML = `
                    <a href="/game/${game.game_id}" class="btn-analyze">
                        Analyze
                    </a>
                `;
                tr.appendChild(tdAction);

                gamesTableBody.appendChild(tr);
            });
        } catch (error) {
            console.error("Failed to load games list:", error);
            gamesTableBody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: var(--danger); padding: 2rem;">
                        Failed to load games. Check server logs.
                    </td>
                </tr>
            `;
            gamesCount.textContent = "Error";
        }
    }

    // Bind event listeners
    seasonSelect.addEventListener("change", loadGames);
    teamSelect.addEventListener("change", loadGames);

    // Initial load
    loadGames();
});

// Window-scoped tab switcher function for Game overview layout
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

    // 1. Fetch all shots for this game
    try {
        const res = await fetch(`/api/shots?game_id=${GAME_ID}`);
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

        // Filter shots list
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

        // Split shots into outcomes for mapping different shapes/colors
        const goals = filtered.filter(s => s.outcome === "Goal");
        const saves = filtered.filter(s => s.outcome === "Saved");
        const misses = filtered.filter(s => s.outcome === "Missed");
        const blocks = filtered.filter(s => s.outcome === "Blocked");

        // Helper to extract x/y based on raw/normalized toggle
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

        // Build Traces
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
                    color: '#10b981', // green success
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
                    color: '#38bdf8' // blue accent
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
                    color: '#f59e0b' // orange warning
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
                    color: '#ef4444' // red danger
                }
            }
        ];

        // Draw Rink Programmatic Layout Shapes
        const shapes = [];

        // 1. Rink outer boundary
        shapes.push({
            type: 'rect',
            x0: -100, y0: -42.5, x1: 100, y1: 42.5,
            line: { color: 'rgba(255, 255, 255, 0.2)', width: 2 }
        });

        if (!normalize) {
            // Draw full rink elements
            // Center red line
            shapes.push({
                type: 'line',
                x0: 0, y0: -42.5, x1: 0, y1: 42.5,
                line: { color: 'rgba(239, 68, 68, 0.4)', width: 3 }
            });
            // Neutral zone blue lines
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
            // Center ice circle
            shapes.push({
                type: 'circle',
                x0: -15, y0: -15, x1: 15, y1: 15,
                line: { color: 'rgba(56, 189, 248, 0.3)', width: 1.5 }
            });
            // Left goal line
            shapes.push({
                type: 'line',
                x0: -89, y0: -42.5, x1: -89, y1: 42.5,
                line: { color: 'rgba(239, 68, 68, 0.3)', width: 1.5 }
            });
            // Left net crease semicircle (using path)
            shapes.push({
                type: 'path',
                path: 'M -89 -4 A 4 4 0 0 1 -89 4 Z',
                line: { color: 'rgba(56, 189, 248, 0.3)', width: 1 },
                fillcolor: 'rgba(56, 189, 248, 0.05)'
            });
            // Left net backing
            shapes.push({
                type: 'rect',
                x0: -92, y0: -3, x1: -89, y1: 3,
                line: { color: 'rgba(255, 255, 255, 0.3)', width: 1 }
            });
        } else {
            // Draw vertical dividing line at neutral zone edge (x=0)
            shapes.push({
                type: 'line',
                x0: 0, y0: -42.5, x1: 0, y1: 42.5,
                line: { color: 'rgba(255, 255, 255, 0.2)', width: 1.5 }
            });
        }

        // Draw Right Zone elements (always visible, both raw and normalized)
        // Right goal line
        shapes.push({
            type: 'line',
            x0: 89, y0: -42.5, x1: 89, y1: 42.5,
            line: { color: 'rgba(239, 68, 68, 0.4)', width: 1.5 }
        });
        // Right net crease
        shapes.push({
            type: 'path',
            path: 'M 89 -4 A 4 4 0 0 0 89 4 Z',
            line: { color: 'rgba(56, 189, 248, 0.3)', width: 1 },
            fillcolor: 'rgba(56, 189, 248, 0.05)'
        });
        // Right net backing
        shapes.push({
            type: 'rect',
            x0: 89, y0: -3, x1: 92, y1: 3,
            line: { color: 'rgba(255, 255, 255, 0.3)', width: 1 }
        });
        // Right faceoff dots & circles (centered at x=69, y=22 and y=-22)
        const drawFaceoff = (cx, cy) => {
            // Circle radius 15
            shapes.push({
                type: 'circle',
                x0: cx - 15, y0: cy - 15, x1: cx + 15, y1: cy + 15,
                line: { color: 'rgba(239, 68, 68, 0.25)', width: 1.5 }
            });
            // Dot
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

    // Attach listeners
    teamFilter.addEventListener("change", renderPlot);
    playerFilter.addEventListener("change", renderPlot);
    periodFilter.addEventListener("change", renderPlot);
    outcomeFilter.addEventListener("change", renderPlot);
    strengthFilter.addEventListener("change", renderPlot);
    normalizeToggle.addEventListener("change", renderPlot);

    // Initial render
    renderPlot();
}
