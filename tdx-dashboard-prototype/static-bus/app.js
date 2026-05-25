const state = {
  city: "Taipei",
  station: null,
  stop: null,
  stationSearchTimer: null,
  arrivalsController: null,
};

const elements = {
  currentTime: document.querySelector("#currentTime"),
  stationSearch: document.querySelector("#stationSearch"),
  stationResults: document.querySelector("#stationResults"),
  refreshButton: document.querySelector("#refreshButton"),
  stationId: document.querySelector("#stationId"),
  stationName: document.querySelector("#stationName"),
  stationNameEn: document.querySelector("#stationNameEn"),
  stopSummary: document.querySelector("#stopSummary"),
  stopButtons: document.querySelector("#stopButtons"),
  routeFilter: document.querySelector("#routeFilter"),
  totalCount: document.querySelector("#totalCount"),
  routeCount: document.querySelector("#routeCount"),
  arrivingCount: document.querySelector("#arrivingCount"),
  dataUpdatedAt: document.querySelector("#dataUpdatedAt"),
  systemStatus: document.querySelector("#systemStatus"),
  selectedStopName: document.querySelector("#selectedStopName"),
  boardBadge: document.querySelector("#boardBadge"),
  arrivalRows: document.querySelector("#arrivalRows"),
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
  if (isLoading) {
    elements.systemStatus.textContent = "更新中";
  }
}

function closeStationResults() {
  elements.stationResults.classList.remove("is-open");
  elements.stationResults.innerHTML = "";
}

function renderEmptyArrivalRows(message = "請先選擇站牌") {
  elements.arrivalRows.innerHTML = "";
  const row = document.createElement("tr");
  row.className = "empty-row";
  row.innerHTML = `<td colspan="7">${escapeHtml(message)}</td>`;
  elements.arrivalRows.append(row);
}

function resetArrivals() {
  elements.totalCount.textContent = "0";
  elements.routeCount.textContent = "0";
  elements.arrivingCount.textContent = "0";
  elements.dataUpdatedAt.textContent = "--:--:--";
  elements.boardBadge.textContent = "0 筆";
  renderEmptyArrivalRows();
}

function setStation(station) {
  state.station = station;
  state.stop = null;
  elements.stationId.textContent = station.id || station.uid || "-";
  elements.stationName.textContent = station.name_zh || station.id || "未知站點";
  elements.stationNameEn.textContent = station.name_en || `${station.route_count || 0} 條路線`;
  elements.stationSearch.value = `${station.name_zh || station.id} ${station.id || ""}`.trim();
  closeStationResults();
  resetArrivals();
  renderStops(station.stops || []);
}

function renderStationResults(stations) {
  elements.stationResults.innerHTML = "";

  if (!stations.length) {
    const empty = document.createElement("div");
    empty.className = "station-option empty";
    empty.textContent = "找不到符合的公車站";
    elements.stationResults.append(empty);
    elements.stationResults.classList.add("is-open");
    return;
  }

  for (const station of stations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "station-option";
    button.innerHTML = `
      <code>${escapeHtml(station.id || station.uid || "-")}</code>
      <span>
        ${escapeHtml(station.name_zh || station.id || "未知站點")}
        <small>${escapeHtml((station.route_names || []).slice(0, 5).join("、") || station.name_en || "")}</small>
      </span>
    `;
    button.addEventListener("click", () => loadStation(station.id || station.uid));
    elements.stationResults.append(button);
  }

  elements.stationResults.classList.add("is-open");
}

async function searchStations(query) {
  const response = await fetch(`/api/stations?city=${encodeURIComponent(state.city)}&q=${encodeURIComponent(query)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "station search failed");
  renderStationResults(data);
}

async function loadStation(stationId) {
  setLoading(true);
  try {
    const response = await fetch(`/api/station?city=${encodeURIComponent(state.city)}&station_id=${encodeURIComponent(stationId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "station detail failed");
    setStation(data);
    elements.systemStatus.textContent = "請選擇站牌";
  } catch (error) {
    elements.systemStatus.textContent = error.message.includes("limit") ? "請稍後再試" : "錯誤";
    console.error(error);
  } finally {
    setLoading(false);
  }
}

function renderStops(stops) {
  elements.stopButtons.innerHTML = "";
  elements.stopSummary.textContent = stops.length ? `${stops.length} 個站牌` : "此站目前沒有站牌資料";

  if (!stops.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "沒有可選擇的站牌";
    elements.stopButtons.append(empty);
    return;
  }

  for (const stop of stops) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "stop-button";
    button.dataset.stopUid = stop.uid;
    button.innerHTML = `
      <strong>${escapeHtml(stop.name_zh || stop.id || "站牌")}</strong>
      <span>${escapeHtml((stop.route_names || []).slice(0, 6).join("、") || `${stop.route_count || 0} 條路線`)}</span>
    `;
    button.addEventListener("click", () => {
      state.stop = stop;
      for (const item of elements.stopButtons.querySelectorAll(".stop-button")) {
        item.classList.toggle("is-active", item.dataset.stopUid === stop.uid);
      }
      loadArrivals();
    });
    elements.stopButtons.append(button);
  }
}

function renderArrivalRows(arrivals) {
  elements.arrivalRows.innerHTML = "";

  if (!arrivals.length) {
    renderEmptyArrivalRows("目前沒有公車到站資訊");
    return;
  }

  for (const item of arrivals) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="route-badge">${escapeHtml(item.route_name || "-")}</span><small>${escapeHtml(item.subroute_name || "")}</small></td>
      <td>${escapeHtml(item.direction_label || "-")}</td>
      <td>${escapeHtml(item.stop_sequence || "-")}</td>
      <td class="estimate">${escapeHtml(item.estimate_label || "-")}</td>
      <td><span class="status ${escapeHtml(item.status_kind)}">${escapeHtml(item.stop_status || "-")}</span></td>
      <td>${escapeHtml(item.plate_number || "-")}</td>
      <td>${escapeHtml(formatUpdateTime(item.update_time))}</td>
    `;
    elements.arrivalRows.append(row);
  }
}

function renderArrivals(data) {
  elements.dataUpdatedAt.textContent = formatUpdateTime(data.update_time);
  elements.totalCount.textContent = data.counts.total;
  elements.routeCount.textContent = data.counts.routes;
  elements.arrivingCount.textContent = data.counts.arriving;
  elements.boardBadge.textContent = `${data.counts.total} 筆`;
  elements.selectedStopName.textContent = state.stop ? `${state.stop.name_zh || state.stop.id} ${state.stop.id || ""}`.trim() : "尚未選擇站牌";
  renderArrivalRows(data.arrivals);
}

async function loadArrivals() {
  if (!state.stop?.uid) {
    resetArrivals();
    elements.systemStatus.textContent = "請選擇站牌";
    return;
  }

  if (state.arrivalsController) {
    state.arrivalsController.abort();
  }

  const controller = new AbortController();
  state.arrivalsController = controller;
  const routeName = elements.routeFilter.value.trim();
  setLoading(true);

  try {
    const params = new URLSearchParams({
      city: state.city,
      stop_uid: state.stop.uid,
    });
    if (routeName) {
      params.set("route_name", routeName);
    }
    const response = await fetch(`/api/arrivals?${params.toString()}`, { signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "arrival request failed");
    renderArrivals(data);
    elements.systemStatus.textContent = data.counts.service_issue ? "部分異常" : "正常";
  } catch (error) {
    if (error.name === "AbortError") return;
    elements.systemStatus.textContent = error.message.includes("limit") ? "請稍後再試" : "錯誤";
    console.error(error);
  } finally {
    if (state.arrivalsController === controller) {
      state.arrivalsController = null;
      setLoading(false);
    }
  }
}

elements.stationSearch.addEventListener("input", (event) => {
  const query = event.target.value.trim();
  clearTimeout(state.stationSearchTimer);
  state.stationSearchTimer = setTimeout(() => {
    searchStations(query).catch(console.error);
  }, 180);
});

elements.stationSearch.addEventListener("focus", () => {
  searchStations(elements.stationSearch.value.trim()).catch(console.error);
});

elements.routeFilter.addEventListener("input", () => {
  clearTimeout(state.stationSearchTimer);
  state.stationSearchTimer = setTimeout(loadArrivals, 220);
});

elements.refreshButton.addEventListener("click", loadArrivals);

document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-block")) {
    closeStationResults();
  }
});

updateCurrentTime();
renderEmptyArrivalRows();
setInterval(updateCurrentTime, 1000);
setInterval(() => {
  if (!document.hidden && state.stop?.uid) {
    loadArrivals();
  }
}, 30000);
