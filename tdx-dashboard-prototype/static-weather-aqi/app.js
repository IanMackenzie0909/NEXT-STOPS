const state = {
  presets: [],
  loading: false,
};

const elements = {
  systemStatus: document.querySelector("#systemStatus"),
  locationLabel: document.querySelector("#locationLabel"),
  latInput: document.querySelector("#latInput"),
  lonInput: document.querySelector("#lonInput"),
  queryButton: document.querySelector("#queryButton"),
  locateButton: document.querySelector("#locateButton"),
  presetList: document.querySelector("#presetList"),
  presetCount: document.querySelector("#presetCount"),
  realOnlyToggle: document.querySelector("#realOnlyToggle"),
  sourceMode: document.querySelector("#sourceMode"),
  weatherSummary: document.querySelector("#weatherSummary"),
  comfortLabel: document.querySelector("#comfortLabel"),
  temperatureValue: document.querySelector("#temperatureValue"),
  humidityValue: document.querySelector("#humidityValue"),
  rainValue: document.querySelector("#rainValue"),
  rainStationValue: document.querySelector("#rainStationValue"),
  windValue: document.querySelector("#windValue"),
  windDirectionValue: document.querySelector("#windDirectionValue"),
  uvValue: document.querySelector("#uvValue"),
  uvStationValue: document.querySelector("#uvStationValue"),
  aqiValue: document.querySelector("#aqiValue"),
  aqiSiteValue: document.querySelector("#aqiSiteValue"),
  pmValue: document.querySelector("#pmValue"),
  pollutantValue: document.querySelector("#pollutantValue"),
  generatedAt: document.querySelector("#generatedAt"),
  weatherStation: document.querySelector("#weatherStation"),
  forecastLocation: document.querySelector("#forecastLocation"),
  aqiStatus: document.querySelector("#aqiStatus"),
  errorCount: document.querySelector("#errorCount"),
  errorOutput: document.querySelector("#errorOutput"),
  rawOutput: document.querySelector("#rawOutput"),
  payloadSize: document.querySelector("#payloadSize"),
};

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits).replace(/\.0$/, "");
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatText(value, fallback = "--") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-TW", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setStatus(message) {
  elements.systemStatus.textContent = message;
}

function setLoading(isLoading) {
  state.loading = isLoading;
  elements.queryButton.disabled = isLoading;
  elements.locateButton.disabled = isLoading;
  for (const button of elements.presetList.querySelectorAll("button")) {
    button.disabled = isLoading;
  }
}

function getCoordinates() {
  const lat = Number(elements.latInput.value);
  const lon = Number(elements.lonInput.value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error("請輸入有效的緯度與經度");
  }
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw new Error("座標超出有效範圍");
  }
  return { lat, lon };
}

function setCoordinates(location) {
  elements.latInput.value = Number(location.lat).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  elements.lonInput.value = Number(location.lon).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  elements.locationLabel.textContent = location.name || "自訂座標";
}

function renderPresets() {
  elements.presetList.innerHTML = "";
  elements.presetCount.textContent = `${state.presets.length} 筆`;

  for (const preset of state.presets) {
    const button = document.createElement("button");
    button.className = "preset-button";
    button.type = "button";
    button.textContent = preset.name;
    button.addEventListener("click", () => {
      setCoordinates(preset);
      queryWeatherAQI();
    });
    elements.presetList.append(button);
  }
}

function renderError(error) {
  setStatus("查詢失敗");
  elements.sourceMode.textContent = "錯誤";
  elements.weatherSummary.textContent = error.message;
  elements.comfortLabel.textContent = "--";
  elements.errorCount.textContent = "1 筆";
  elements.errorOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
}

function renderData(data) {
  const weather = data.weather || {};
  const uv = data.uv || {};
  const air = data.air_quality || {};
  const sourceStatus = data.source_status || {};
  const errors = sourceStatus.errors || (sourceStatus.error ? { fallback: sourceStatus.error } : {});
  const errorKeys = Object.keys(errors);
  const rawText = JSON.stringify(data, null, 2);

  setStatus(sourceStatus.mode === "heuristic_fallback" ? "Fallback 資料" : "查詢完成");
  elements.sourceMode.textContent = `${formatText(sourceStatus.mode, "unknown")} / ${formatText(weather.source, "--")}`;
  elements.weatherSummary.textContent = formatText(weather.summary, "沒有摘要資料");
  elements.comfortLabel.textContent = formatText(data.outdoor_comfort, "--");

  elements.temperatureValue.textContent = `${formatNumber(weather.temperature_c)} °C`;
  elements.humidityValue.textContent = `濕度 ${formatNumber(weather.relative_humidity, 0)}%`;
  elements.rainValue.textContent = formatPercent(weather.rain_probability);
  elements.rainStationValue.textContent = `測站 ${formatText(weather.rain_station)}`;
  elements.windValue.textContent = `${formatNumber(weather.wind_speed_mps)} m/s`;
  elements.windDirectionValue.textContent = `風向 ${formatNumber(weather.wind_direction_degrees, 0)}°`;
  elements.uvValue.textContent = formatText(uv.uv_index);
  elements.uvStationValue.textContent = `測站 ${formatText(uv.station)}`;
  elements.aqiValue.textContent = formatText(air.aqi);
  elements.aqiSiteValue.textContent = `${formatText(air.site)} ${formatText(air.county, "")}`.trim() || "測站 --";
  elements.pmValue.textContent = `${formatText(air.pm25)} / ${formatText(air.pm10)}`;
  elements.pollutantValue.textContent = `污染物 ${formatText(air.pollutant)}`;
  elements.generatedAt.textContent = formatDateTime(data.generated_at);
  elements.weatherStation.textContent = formatText(weather.station);
  elements.forecastLocation.textContent = formatText(weather.forecast_location);
  elements.aqiStatus.textContent = `${formatText(air.status)} ${formatText(air.status_kind, "")}`.trim();
  elements.errorCount.textContent = `${errorKeys.length} 筆`;
  elements.errorOutput.textContent = JSON.stringify(errors, null, 2);
  elements.rawOutput.textContent = rawText;
  elements.payloadSize.textContent = `${new Blob([rawText]).size} bytes`;
}

async function queryWeatherAQI() {
  setLoading(true);
  try {
    const { lat, lon } = getCoordinates();
    const params = new URLSearchParams({
      lat: String(lat),
      lon: String(lon),
    });
    if (elements.realOnlyToggle.checked) {
      params.set("real", "1");
    }

    setStatus("查詢中");
    const response = await fetch(`/api/weather-aqi?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Weather/AQI API 查詢失敗");
    renderData(data);
  } catch (error) {
    renderError(error);
    console.error(error);
  } finally {
    setLoading(false);
  }
}

function locateUser() {
  if (!navigator.geolocation) {
    renderError(new Error("瀏覽器不支援定位"));
    return;
  }

  setLoading(true);
  setStatus("定位中");
  navigator.geolocation.getCurrentPosition(
    (position) => {
      setCoordinates({
        name: "目前位置",
        lat: position.coords.latitude,
        lon: position.coords.longitude,
      });
      queryWeatherAQI();
    },
    (error) => {
      setLoading(false);
      renderError(new Error(error.message || "定位失敗"));
    },
    {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 0,
    }
  );
}

async function loadPresets() {
  const response = await fetch("/api/sample-locations");
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "無法載入快速地點");
  state.presets = data.locations || [];
  renderPresets();
}

elements.queryButton.addEventListener("click", queryWeatherAQI);
elements.locateButton.addEventListener("click", locateUser);
elements.realOnlyToggle.addEventListener("change", queryWeatherAQI);

(async function init() {
  try {
    await loadPresets();
    await queryWeatherAQI();
  } catch (error) {
    renderError(error);
  }
})();
