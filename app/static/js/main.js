document.addEventListener("DOMContentLoaded", () => {
    const seasonSelect = document.getElementById("season-select");
    const teamSelect = document.getElementById("team-select");
    const gamesTableBody = document.getElementById("games-table-body");
    const gamesCount = document.getElementById("games-count");

    if (!seasonSelect || !teamSelect || !gamesTableBody) {
        return; // Diagnostics page or empty DB view
    }

    window.importGame = async function(gameId, btn) {
        btn.disabled = true;
        btn.textContent = "Importing...";
        
        const tr = btn.closest('tr');
        const statusSpan = tr.querySelector('.status-indicator');
        if (statusSpan) {
            statusSpan.style.background = "rgba(56, 189, 248, 0.1)";
            statusSpan.style.color = "var(--accent-color)";
            statusSpan.textContent = "Importing...";
        }
        
        try {
            const res = await fetch(`/api/game/${gameId}/ingest`, { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.success) {
                // Successfully ingested! Reload the table
                await loadGames();
            } else {
                throw new Error(data.error || "Unknown error occurred during ingestion");
            }
        } catch (error) {
            console.error("Failed to import game:", error);
            alert("Failed to import game: " + error.message);
            if (statusSpan) {
                statusSpan.style.background = "rgba(239, 68, 68, 0.1)";
                statusSpan.style.color = "#ef4444";
                statusSpan.textContent = "Failed";
            }
            btn.disabled = false;
            btn.textContent = "Import";
        }
    };

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
            const response = await fetch(`/api/schedule?team_id=${teamId}&season=${season}`);
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
                            No games found in schedule for this team/season.
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
                tdType.textContent = game.game_type;
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

                // Status & Action
                const tdStatus = document.createElement("td");
                const tdAction = document.createElement("td");
                tdAction.style.textAlign = "right";

                if (game.is_ingested) {
                    tdStatus.innerHTML = `<span class="status-indicator status-connected">Ingested</span>`;
                    tdAction.innerHTML = `
                        <a href="/game/${game.game_id}?team_id=${teamId}" class="btn-analyze">
                            Analyze
                        </a>
                    `;
                } else if (game.game_status === 'FINAL' || game.game_status === 'OFF') {
                    tdStatus.innerHTML = `<span class="status-indicator" style="background: rgba(245, 158, 11, 0.1); color: #f59e0b; padding: 0.15rem 0.35rem; font-size: 0.75rem; border-radius: 3px;">Ready to Import</span>`;
                    tdAction.innerHTML = `
                        <button class="btn-analyze" style="background: var(--accent-color); border: none; cursor: pointer;" onclick="importGame(${game.game_id}, this)">
                            Import
                        </button>
                    `;
                } else {
                    tdStatus.innerHTML = `<span class="status-indicator" style="background: rgba(148, 163, 184, 0.1); color: var(--text-secondary); padding: 0.15rem 0.35rem; font-size: 0.75rem; border-radius: 3px;">Scheduled</span>`;
                    tdAction.innerHTML = `
                        <button class="btn-analyze" style="opacity: 0.4; cursor: not-allowed;" disabled>
                            Future
                        </button>
                    `;
                }
                
                tr.appendChild(tdStatus);
                tr.appendChild(tdAction);

                gamesTableBody.appendChild(tr);
            });
        } catch (error) {
            console.error("Failed to load games list:", error);
            gamesTableBody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: var(--danger); padding: 2rem;">
                        Failed to load schedule. Check server logs.
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
