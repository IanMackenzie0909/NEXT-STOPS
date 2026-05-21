const state = {
  station: {
    id: "3300",
    name_zh: "臺中",
    name_en: "Taichung",
  },
  loading: false,
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
  northCount: document.querySelector("#northCount"),
  southCount: document.querySelector("#southCount"),
  systemStatus: document.querySelector("#systemStatus"),
  northRows: document.querySelector("#northRows"),
  southRows: document.querySelector("#southRows"),
  northBadge: document.querySelector("#northBadge"),
  southBadge: document.querySelector("#southBadge"),
};

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
  state.loading = isLoading;
  elements.refreshButton.disabled = isLoading;
  if (isLoading) {
    elements.systemStatus.textContent = "更新中";
  }
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
    empty.className = "station-option";
    empty.textContent = "找不到符合的車站";
    elements.stationResults.append(empty);
    elements.stationResults.classList.add("is-open");
    return;
  }

  for (const station of stations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "station-option";
    button.innerHTML = `
      <code>${station.id}</code>
      <span>${station.name_zh || station.id}<small>${station.name_en || ""}</small></span>
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
  if (!response.ok) throw new Error("station search failed");
  const stations = await response.json();
  renderStationResults(stations);
}

function renderRows(target, trains) {
  target.innerHTML = "";

  if (!trains.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    row.innerHTML = `<td colspan="7">目前沒有列車動態</td>`;
    target.append(row);
    return;
  }

  for (const train of trains) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="train-no">${train.train_no}</td>
      <td>${train.train_type_name || train.train_type_id}</td>
      <td>${train.ending_station || "-"}</td>
      <td>${train.arrival_time || "-"}</td>
      <td>${train.departure_time || "-"}</td>
      <td class="delay">${train.delay}</td>
      <td><span class="status ${train.status_kind}">${train.status}</span></td>
    `;
    target.append(row);
  }
}

function renderLiveboard(data) {
  setStation(data.station);
  elements.dataUpdatedAt.textContent = formatUpdateTime(data.update_time);
  elements.totalCount.textContent = data.counts.total;
  elements.northCount.textContent = data.counts.northbound;
  elements.southCount.textContent = data.counts.southbound;
  elements.northBadge.textContent = `${data.counts.northbound} 班`;
  elements.southBadge.textContent = `${data.counts.southbound} 班`;
  renderRows(elements.northRows, data.northbound);
  renderRows(elements.southRows, data.southbound);
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
    elements.systemStatus.textContent = "正常";
  } catch (error) {
    if (error.name === "AbortError") return;
    elements.systemStatus.textContent = "錯誤";
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
