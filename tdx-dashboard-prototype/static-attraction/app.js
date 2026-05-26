const state = {
  districts: [],
  selectedDistrictId: null,
  searchTimer: null,
};

const elements = {
  sourceLabel: document.querySelector("#sourceLabel"),
  searchInput: document.querySelector("#searchInput"),
  refreshButton: document.querySelector("#refreshButton"),
  systemStatus: document.querySelector("#systemStatus"),
  districtCount: document.querySelector("#districtCount"),
  attractionCount: document.querySelector("#attractionCount"),
  themeCount: document.querySelector("#themeCount"),
  latestImport: document.querySelector("#latestImport"),
  resultCount: document.querySelector("#resultCount"),
  districtList: document.querySelector("#districtList"),
  detailTheme: document.querySelector("#detailTheme"),
  detailTitle: document.querySelector("#detailTitle"),
  detailCount: document.querySelector("#detailCount"),
  attractionList: document.querySelector("#attractionList"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatImportTime(value) {
  if (!value) return "--";
  const [date, time] = value.split(" ");
  return time ? `${date} ${time.slice(0, 5)}` : value;
}

function setLoading(isLoading) {
  elements.refreshButton.disabled = isLoading;
  if (isLoading) {
    elements.systemStatus.textContent = "載入中";
  }
}

function renderSummary(summary) {
  elements.districtCount.textContent = summary.district_count;
  elements.attractionCount.textContent = summary.attraction_count;
  elements.themeCount.textContent = summary.theme_count;
  elements.latestImport.textContent = formatImportTime(summary.latest_import);
}

function renderDistricts(districts) {
  elements.districtList.innerHTML = "";
  elements.resultCount.textContent = `${districts.length} 筆`;

  if (!districts.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "找不到符合的景點資料";
    elements.districtList.append(empty);
    renderDetail(null);
    return;
  }

  if (!districts.some((district) => district.id === state.selectedDistrictId)) {
    state.selectedDistrictId = districts[0].id;
  }

  for (const district of districts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "district-button";
    button.classList.toggle("is-active", district.id === state.selectedDistrictId);
    button.innerHTML = `
      <strong>${escapeHtml(district.district || "未分類")}</strong>
      <span>${escapeHtml(district.theme || "")}</span>
      <small>${district.attraction_count} 景點</small>
    `;
    button.addEventListener("click", () => {
      state.selectedDistrictId = district.id;
      renderDistricts(state.districts);
      renderDetail(district);
    });
    elements.districtList.append(button);
  }

  renderDetail(districts.find((district) => district.id === state.selectedDistrictId) || districts[0]);
}

function renderDetail(district) {
  elements.attractionList.innerHTML = "";

  if (!district) {
    elements.detailTheme.textContent = "無資料";
    elements.detailTitle.textContent = "沒有符合結果";
    elements.detailCount.textContent = "0 景點";
    return;
  }

  elements.detailTheme.textContent = district.theme || "主題未分類";
  elements.detailTitle.textContent = district.district || "未分類";
  elements.detailCount.textContent = `${district.attraction_count} 景點`;

  for (const [index, attraction] of district.attractions.entries()) {
    const item = document.createElement("article");
    item.className = "attraction-item";
    item.innerHTML = `
      <span>${String(index + 1).padStart(2, "0")}</span>
      <strong>${escapeHtml(attraction)}</strong>
    `;
    elements.attractionList.append(item);
  }
}

async function loadAttractions({ refresh = false } = {}) {
  const params = new URLSearchParams();
  const query = elements.searchInput.value.trim();
  if (query) params.set("q", query);
  if (refresh) params.set("refresh", "1");

  setLoading(true);
  try {
    const response = await fetch(`/api/attractions?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "attraction request failed");

    state.districts = data.districts;
    elements.sourceLabel.textContent = data.source;
    renderSummary(data.summary);
    renderDistricts(data.districts);
    elements.systemStatus.textContent = "正常";
  } catch (error) {
    elements.systemStatus.textContent = "錯誤";
    console.error(error);
  } finally {
    setLoading(false);
  }
}

elements.searchInput.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => loadAttractions(), 180);
});

elements.refreshButton.addEventListener("click", () => loadAttractions({ refresh: true }));

loadAttractions();
