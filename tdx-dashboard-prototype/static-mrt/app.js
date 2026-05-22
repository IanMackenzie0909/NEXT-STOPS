const state = {
  station: {
    id: "BL03",
    name_zh: "土城",
    name_en: "Tucheng",
    line_id: "BL",
  },
  liveboardController: null,
  searchTimer: null,
};

const elements = {
  currentTime: document.querySelector("#currentTime"),
  dataUpdatedAt: document.querySelector("#dataUpdatedAt"),
  stationSearch: document.querySelector("#stationSearch"),
  stationResults: document.querySelector("#stationResults"),
  refreshButton: document.querySelector("#refreshButton"),
  stationId: document.querySelector("#stationId"),
  stationName: document.querySelector("#stationName"),
  stationNameEn: document.querySelector("#stationNameEn"),
  totalCount: document.querySelector("#totalCount"),
  normalCount: document.querySelector("#normalCount"),
  directionCount: document.querySelector("#directionCount"),
  arrivingCount: document.querySelector("#arrivingCount"),
  systemStatus: document.querySelector("#systemStatus"),
  directionBoards: document.querySelector("#directionBoards"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatClockTime(date) {
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return new Intl.DateTimeFormat("zh-TW", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatUpdateTime(value) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 19) || value;
  return formatClockTime(date);
}

function updateCurrentTime() {
  elements.currentTime.textContent = formatClockTime(new Date());
}

function setLoading(isLoading) {
  elements.refreshButton.disabled = isLoading;
  elements.systemStatus.textContent = isLoading ? "更新中" : elements.systemStatus.textContent;
}

function setStation(station) {
  state.station = station;
  elements.stationId.textContent = station.id;
  elements.stationName.textContent = station.name_zh || station.id;
  elements.stationNameEn.textContent = station.name_en || "";
  elements.stationSearch.value = `${station.name_zh || station.id} ${station.id}`;
  closeStationResults();
}

function closeStationResults() {
  elements.stationResults.classList.remove("is-open");
  elements.stationResults.innerHTML = "";
}

function renderStationResults(stations) {
  elements.stationResults.innerHTML = "";

  if (!stations.length) {
    const empty = document.createElement("div");
    empty.className = "station-option empty";
    empty.textContent = "找不到符合的捷運站";
    elements.stationResults.append(empty);
    elements.stationResults.classList.add("is-open");
    return;
  }

  for (const station of stations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "station-option";
    button.innerHTML = `
      <code>${escapeHtml(station.id)}</code>
      <span>${escapeHtml(station.name_zh || station.id)}<small>${escapeHtml(station.name_en || "")}</small></span>
    `;
    button.addEventListener("click", () => {
      setStation(station);
      loadLiveboard();
    });
    elements.stationResults.append(button);
  }

  elements.stationResults.classList.add("is-open");
}

async function searchStations(query) {
  const response = await fetch(`/api/stations?q=${encodeURIComponent(query)}`);
  const stations = await response.json();
  if (!response.ok) throw new Error(stations.error || "station search failed");
  renderStationResults(stations);
}

function renderRows(tbody, items) {
  if (!items.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    row.innerHTML = `<td colspan="5">目前沒有捷運到站資訊</td>`;
    tbody.append(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="line-badge">${escapeHtml(item.line_id || "-")}</span><strong>${escapeHtml(item.line_name || "")}</strong></td>
      <td>${escapeHtml(item.destination || "-")}<small>${escapeHtml(item.destination_en || "")}</small></td>
      <td class="estimate">${escapeHtml(item.estimate_label || "-")}</td>
      <td><span class="status ${escapeHtml(item.status_kind)}">${escapeHtml(item.service_status || item.status || "-")}</span></td>
      <td>${escapeHtml(formatUpdateTime(item.update_time))}</td>
    `;
    tbody.append(row);
  }
}

function renderDirectionBoards(groups) {
  elements.directionBoards.innerHTML = "";

  if (!groups.length) {
    const board = document.createElement("section");
    board.className = "board direction-board empty-board";
    board.innerHTML = `
      <div class="board-header">
        <div>
          <h2>即時電子看板</h2>
          <small>0 個方向</small>
        </div>
        <span>0 筆</span>
      </div>
      <div class="empty-state">目前沒有捷運到站資訊</div>
    `;
    elements.directionBoards.append(board);
    return;
  }

  for (const group of groups) {
    const board = document.createElement("section");
    board.className = "board direction-board";
    const title = group.label || (group.destination ? `往${group.destination}` : "未知方向");
    const subtitle = group.destination_en || group.destination || group.line_name || "";
    board.innerHTML = `
      <div class="board-header">
        <div>
          <h2>${escapeHtml(title)}</h2>
          <small>${escapeHtml(subtitle)}</small>
        </div>
        <span>${group.items.length} 筆</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>路線</th>
              <th>目的地</th>
              <th>預估到站</th>
              <th>服務狀態</th>
              <th>更新</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    `;
    renderRows(board.querySelector("tbody"), group.items);
    elements.directionBoards.append(board);
  }
}

function renderLiveboard(data) {
  setStation(data.station);
  elements.dataUpdatedAt.textContent = formatUpdateTime(data.update_time);
  elements.totalCount.textContent = data.counts.total;
  elements.normalCount.textContent = data.counts.normal;
  elements.directionCount.textContent = data.counts.directions;
  elements.arrivingCount.textContent = data.counts.arriving;
  renderDirectionBoards(data.direction_groups || []);
}

async function loadLiveboard() {
  if (state.liveboardController) {
    state.liveboardController.abort();
  }

  const controller = new AbortController();
  const stationId = state.station.id;
  state.liveboardController = controller;
  setLoading(true);
  try {
    const response = await fetch(`/api/liveboard?station_id=${encodeURIComponent(stationId)}`, {
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "liveboard request failed");
    if (stationId !== state.station.id) return;
    renderLiveboard(data);
    elements.systemStatus.textContent = data.counts.service_issue ? "部分異常" : "正常";
  } catch (error) {
    if (error.name === "AbortError") return;
    elements.systemStatus.textContent = error.message.includes("limit") ? "請稍後再試" : "錯誤";
    console.error(error);
  } finally {
    if (state.liveboardController === controller) {
      state.liveboardController = null;
      setLoading(false);
    }
  }
}

elements.stationSearch.addEventListener("input", (event) => {
  const query = event.target.value.trim();
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => {
    searchStations(query).catch(console.error);
  }, 180);
});

elements.stationSearch.addEventListener("focus", () => {
  searchStations(elements.stationSearch.value.trim()).catch(console.error);
});

elements.refreshButton.addEventListener("click", loadLiveboard);

document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-block")) {
    closeStationResults();
  }
});

setStation(state.station);
updateCurrentTime();
setInterval(updateCurrentTime, 1000);
loadLiveboard();
setInterval(() => {
  if (!document.hidden) {
    loadLiveboard();
  }
}, 30000);
