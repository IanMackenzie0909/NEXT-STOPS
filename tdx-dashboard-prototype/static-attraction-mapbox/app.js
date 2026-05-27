const TAIPEI_CENTER = [121.5319, 25.0478];
const ROUTE_SOURCE_ID = "google-route";
const ROUTE_CASING_LAYER_ID = "google-route-casing";
const ROUTE_LAYER_ID = "google-route-line";
const ROUTE_DASH_LAYER_ID = "google-route-dash";

const state = {
  attractions: [],
  selectedAttraction: null,
  origin: null,
  travelMode: "TRANSIT",
  theme: "light",
  map: null,
  originMarker: null,
  destinationMarker: null,
  searchTimer: null,
};

const elements = {
  panelToggle: document.querySelector("#panelToggle"),
  systemStatus: document.querySelector("#systemStatus"),
  searchInput: document.querySelector("#searchInput"),
  refreshButton: document.querySelector("#refreshButton"),
  locateButton: document.querySelector("#locateButton"),
  setMapCenterButton: document.querySelector("#setMapCenterButton"),
  originLabel: document.querySelector("#originLabel"),
  themeLabel: document.querySelector("#themeLabel"),
  themeButtons: document.querySelectorAll(".theme-button"),
  travelModeLabel: document.querySelector("#travelModeLabel"),
  resultCount: document.querySelector("#resultCount"),
  attractionSelect: document.querySelector("#attractionSelect"),
  routeCard: document.querySelector(".route-card"),
  routeCardToggle: document.querySelector("#routeCardToggle"),
  selectedDestination: document.querySelector("#selectedDestination"),
  routeTitle: document.querySelector("#routeTitle"),
  routeDistance: document.querySelector("#routeDistance"),
  routeDuration: document.querySelector("#routeDuration"),
  routeAddress: document.querySelector("#routeAddress"),
};

function setStatus(message) {
  elements.systemStatus.textContent = message;
}

function setLoading(isLoading) {
  elements.refreshButton.disabled = isLoading;
  elements.locateButton.disabled = isLoading;
  elements.setMapCenterButton.disabled = isLoading;
}

function flattenAttractions(districts) {
  return districts.flatMap((district) =>
    district.attractions.map((name, index) => ({
      id: `${district.id}-${index}`,
      name,
      district: district.district,
      theme: district.theme,
      query: `${name} ${district.district} 臺北市 台灣`,
    }))
  );
}

function formatOriginLabel(position, accuracy, sourceLabel) {
  const accuracyText = Number.isFinite(accuracy) ? `，約 ${Math.round(accuracy)}m` : "";
  return `${sourceLabel}: ${position.lat.toFixed(5)}, ${position.lng.toFixed(5)}${accuracyText}`;
}

function resetRouteSummary() {
  elements.routeTitle.textContent = "等待路線規劃";
  elements.routeDistance.textContent = "--";
  elements.routeDuration.textContent = "--";
  elements.routeAddress.textContent = "--";
  clearRoute();
}

async function loadMapbox() {
  const response = await fetch("/api/mapbox-config");
  const config = await response.json();
  if (!response.ok) throw new Error(config.error || "Cannot load Mapbox config");
  if (!config.access_token) throw new Error("Missing MAPBOX_ACCESS_TOKEN");

  mapboxgl.accessToken = config.access_token;
  state.map = new mapboxgl.Map({
    container: "map",
    style: "mapbox://styles/mapbox/standard",
    center: TAIPEI_CENTER,
    zoom: 13.2,
    pitch: 62,
    bearing: 28,
    antialias: true,
    cooperativeGestures: true,
  });
  state.map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");
  state.map.addControl(new mapboxgl.FullscreenControl(), "top-right");

  await new Promise((resolve) => state.map.on("load", resolve));
  applyMapAppearance();
}

function applyMapAppearance() {
  const dark = state.theme === "dark";
  state.map.setConfigProperty("basemap", "lightPreset", dark ? "dusk" : "day");
  state.map.setConfigProperty("basemap", "showPointOfInterestLabels", true);
  state.map.setConfigProperty("basemap", "showRoadLabels", true);
  state.map.setConfigProperty("basemap", "showTransitLabels", true);
  state.map.setFog({
    color: dark ? "#172522" : "#eef4f0",
    "high-color": dark ? "#385348" : "#cde6dc",
    "space-color": dark ? "#101716" : "#f8fbf6",
    "horizon-blend": dark ? 0.2 : 0.08,
  });

  const layers = state.map.getStyle().layers || [];
  const labelLayer = layers.find((layer) => layer.type === "symbol" && layer.layout?.["text-field"]);

  if (!state.map.getLayer("soft-3d-buildings")) {
    state.map.addLayer(
      {
        id: "soft-3d-buildings",
        source: "composite",
        "source-layer": "building",
        filter: ["==", ["get", "extrude"], "true"],
        type: "fill-extrusion",
        minzoom: 14,
        paint: {
          "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 14, 0, 16, ["get", "height"]],
          "fill-extrusion-base": ["interpolate", ["linear"], ["zoom"], 14, 0, 16, ["get", "min_height"]],
        },
      },
      labelLayer?.id
    );
  }

  state.map.setPaintProperty("soft-3d-buildings", "fill-extrusion-color", dark ? "#30453d" : "#d7ded8");
  state.map.setPaintProperty("soft-3d-buildings", "fill-extrusion-opacity", dark ? 0.62 : 0.42);
  updateRouteAppearance();
}

function getRoutePaint() {
  if (state.theme === "dark") {
    return {
      casing: "#0f1715",
      route: "#39d8a3",
      dash: "#e9c769",
    };
  }

  return {
    casing: "#fffdf8",
    route: "#237b5c",
    dash: "#b7832d",
  };
}

function updateRouteAppearance() {
  if (!state.map?.isStyleLoaded()) return;
  const colors = getRoutePaint();
  if (state.map.getLayer(ROUTE_CASING_LAYER_ID)) {
    state.map.setPaintProperty(ROUTE_CASING_LAYER_ID, "line-color", colors.casing);
    state.map.setPaintProperty(ROUTE_CASING_LAYER_ID, "line-opacity", state.theme === "dark" ? 0.85 : 0.94);
  }
  if (state.map.getLayer(ROUTE_LAYER_ID)) {
    state.map.setPaintProperty(ROUTE_LAYER_ID, "line-color", colors.route);
  }
  if (state.map.getLayer(ROUTE_DASH_LAYER_ID)) {
    state.map.setPaintProperty(ROUTE_DASH_LAYER_ID, "line-color", colors.dash);
  }
}

function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = state.theme;
  elements.themeLabel.textContent = state.theme === "dark" ? "Dark" : "Light";
  for (const button of elements.themeButtons) {
    button.classList.toggle("is-active", button.dataset.theme === state.theme);
  }
  if (state.map?.isStyleLoaded()) applyMapAppearance();
}

function setControlsCollapsed(isCollapsed) {
  document.body.classList.toggle("controls-collapsed", isCollapsed);
  elements.panelToggle.textContent = isCollapsed ? "設定" : "收合";
  elements.panelToggle.setAttribute("aria-expanded", String(!isCollapsed));
}

function setRouteCardCollapsed(isCollapsed) {
  elements.routeCard.classList.toggle("is-collapsed", isCollapsed);
  elements.routeCardToggle.setAttribute("aria-expanded", String(!isCollapsed));
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
    if (!response.ok) throw new Error(data.error || "Cannot load attractions");

    state.attractions = flattenAttractions(data.districts);
    if (!state.attractions.some((item) => item.id === state.selectedAttraction?.id)) {
      state.selectedAttraction = null;
      elements.selectedDestination.textContent = "尚未選擇目的地";
      resetRouteSummary();
    }
    renderAttractions();
    setStatus("正常");
  } catch (error) {
    setStatus("資料錯誤");
    console.error(error);
  } finally {
    setLoading(false);
  }
}

function renderAttractions() {
  elements.attractionSelect.innerHTML = "";
  elements.resultCount.textContent = `${state.attractions.length} 筆`;

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = state.attractions.length ? "請選擇目的地" : "找不到符合的景點";
  elements.attractionSelect.append(placeholder);
  elements.attractionSelect.disabled = !state.attractions.length;

  for (const attraction of state.attractions) {
    const option = document.createElement("option");
    option.value = attraction.id;
    option.textContent = `${attraction.name} / ${attraction.district}`;
    option.selected = state.selectedAttraction?.id === attraction.id;
    elements.attractionSelect.append(option);
  }
}

function selectAttraction(attraction) {
  state.selectedAttraction = attraction;
  elements.selectedDestination.textContent = `${attraction.name} / ${attraction.district}`;
  resetRouteSummary();
  renderAttractions();
  planRoute();
}

function setOrigin(position, accuracy, sourceLabel) {
  state.origin = position;
  elements.originLabel.textContent = formatOriginLabel(position, accuracy, sourceLabel);
  setOriginMarker();
  planRoute();
}

function setOriginMarker() {
  if (!state.origin || !state.map) return;

  const lngLat = [state.origin.lng, state.origin.lat];
  if (!state.originMarker) {
    state.originMarker = new mapboxgl.Marker({
      element: createMarkerElement("origin"),
      draggable: true,
      anchor: "bottom",
    })
      .setLngLat(lngLat)
      .setPopup(new mapboxgl.Popup().setText("目前位置"))
      .addTo(state.map);
    state.originMarker.on("dragend", () => {
      const position = state.originMarker.getLngLat();
      setOrigin({ lat: position.lat, lng: position.lng }, null, "手動修正");
    });
  } else {
    state.originMarker.setLngLat(lngLat);
  }
  state.map.easeTo({ center: lngLat, zoom: Math.max(state.map.getZoom(), 14) });
}

function locateUser() {
  if (!navigator.geolocation) {
    setStatus("瀏覽器不支援定位");
    return;
  }

  setStatus("高精度定位中");
  let bestPosition = null;
  let watchId = null;
  let finished = false;

  const finish = () => {
    if (finished) return;
    finished = true;
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    if (!bestPosition) {
      setStatus("定位失敗");
      return;
    }
    setOrigin(bestPosition.position, bestPosition.accuracy, "目前位置");
    setStatus("已取得位置");
  };

  watchId = navigator.geolocation.watchPosition(
    (position) => {
      const candidate = {
        position: {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        },
        accuracy: position.coords.accuracy,
      };
      if (!bestPosition || candidate.accuracy < bestPosition.accuracy) {
        bestPosition = candidate;
        elements.originLabel.textContent = formatOriginLabel(candidate.position, candidate.accuracy, "定位中");
      }
      if (candidate.accuracy <= 50) finish();
    },
    (error) => {
      setStatus("定位失敗");
      console.error(error);
    },
    {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 0,
    }
  );

  setTimeout(finish, 8000);
}

function setOriginFromMapCenter() {
  if (!state.map) return;
  const center = state.map.getCenter();
  setOrigin({ lat: center.lat, lng: center.lng }, null, "地圖中心");
  setStatus("已設定出發點");
}

function setDestinationMarker(destination) {
  const lngLat = [destination.lng, destination.lat];
  if (!state.destinationMarker) {
    state.destinationMarker = new mapboxgl.Marker({
      element: createMarkerElement("destination"),
      anchor: "bottom",
    })
      .setLngLat(lngLat)
      .setPopup(new mapboxgl.Popup().setText("目的地"))
      .addTo(state.map);
  } else {
    state.destinationMarker.setLngLat(lngLat);
  }
}

function createMarkerElement(kind) {
  const marker = document.createElement("div");
  marker.className = `route-marker ${kind}`;
  marker.innerHTML = `<span>${kind === "origin" ? "你" : "終"}</span>`;
  return marker;
}

function clearRoute() {
  if (!state.map?.isStyleLoaded()) return;
  if (state.map.getLayer(ROUTE_DASH_LAYER_ID)) state.map.removeLayer(ROUTE_DASH_LAYER_ID);
  if (state.map.getLayer(ROUTE_LAYER_ID)) state.map.removeLayer(ROUTE_LAYER_ID);
  if (state.map.getLayer(ROUTE_CASING_LAYER_ID)) state.map.removeLayer(ROUTE_CASING_LAYER_ID);
  if (state.map.getSource(ROUTE_SOURCE_ID)) state.map.removeSource(ROUTE_SOURCE_ID);
}

function renderRoute(route) {
  const routePaint = getRoutePaint();
  clearRoute();
  state.map.addSource(ROUTE_SOURCE_ID, {
    type: "geojson",
    data: {
      type: "Feature",
      properties: {},
      geometry: route.geometry,
    },
  });
  state.map.addLayer({
    id: ROUTE_CASING_LAYER_ID,
    type: "line",
    source: ROUTE_SOURCE_ID,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": routePaint.casing,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 10, 16, 17],
      "line-opacity": state.theme === "dark" ? 0.85 : 0.94,
    },
  });
  state.map.addLayer({
    id: ROUTE_LAYER_ID,
    type: "line",
    source: ROUTE_SOURCE_ID,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": routePaint.route,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 5, 16, 10],
      "line-opacity": 0.95,
    },
  });
  state.map.addLayer({
    id: ROUTE_DASH_LAYER_ID,
    type: "line",
    source: ROUTE_SOURCE_ID,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": routePaint.dash,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.8, 16, 3.6],
      "line-dasharray": [0.2, 2.8],
      "line-opacity": 0.95,
    },
  });

  setDestinationMarker(route.destination);
  const bounds = new mapboxgl.LngLatBounds();
  for (const coordinate of route.geometry.coordinates) bounds.extend(coordinate);
  bounds.extend([route.origin.lng, route.origin.lat]);
  bounds.extend([route.destination.lng, route.destination.lat]);
  state.map.fitBounds(bounds, {
    padding: {
      top: 90,
      bottom: 170,
      left: 90,
      right: 90,
    },
    maxZoom: 16,
    pitch: 62,
    bearing: 28,
  });
}

async function planRoute() {
  if (!state.map || !state.selectedAttraction) return;
  if (!state.origin) {
    setStatus("請先取得目前位置");
    return;
  }

  setStatus("Google 後端規劃中");
  try {
    const response = await fetch("/api/route", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        origin: state.origin,
        destination_query: state.selectedAttraction.query,
        mode: state.travelMode,
      }),
    });
    const route = await response.json();
    if (!response.ok) throw new Error(route.error || "Cannot calculate route");

    renderRoute(route);
    elements.routeTitle.textContent = route.summary || state.selectedAttraction.name;
    elements.routeDistance.textContent = route.distance_text || "--";
    elements.routeDuration.textContent = route.duration_text || "--";
    elements.routeAddress.textContent = route.destination.address || "--";
    setStatus("路線完成");
  } catch (error) {
    setStatus("路線失敗");
    console.error(error);
  }
}

elements.panelToggle.addEventListener("click", () => {
  setControlsCollapsed(!document.body.classList.contains("controls-collapsed"));
});

elements.routeCardToggle.addEventListener("click", () => {
  setRouteCardCollapsed(!elements.routeCard.classList.contains("is-collapsed"));
});

let routeTouchStartY = null;
elements.routeCard.addEventListener("touchstart", (event) => {
  routeTouchStartY = event.touches[0]?.clientY ?? null;
});

elements.routeCard.addEventListener("touchend", (event) => {
  if (routeTouchStartY === null) return;
  const endY = event.changedTouches[0]?.clientY ?? routeTouchStartY;
  const deltaY = endY - routeTouchStartY;
  routeTouchStartY = null;
  if (Math.abs(deltaY) < 34) return;
  setRouteCardCollapsed(deltaY > 0);
});

for (const button of elements.themeButtons) {
  button.addEventListener("click", () => setTheme(button.dataset.theme));
}

for (const button of document.querySelectorAll(".mode-button")) {
  button.addEventListener("click", () => {
    state.travelMode = button.dataset.mode;
    elements.travelModeLabel.textContent = button.textContent;
    for (const item of document.querySelectorAll(".mode-button")) {
      item.classList.toggle("is-active", item === button);
    }
    planRoute();
  });
}

elements.searchInput.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => loadAttractions(), 180);
});

elements.refreshButton.addEventListener("click", () => loadAttractions({ refresh: true }));
elements.locateButton.addEventListener("click", locateUser);
elements.setMapCenterButton.addEventListener("click", setOriginFromMapCenter);
elements.attractionSelect.addEventListener("change", () => {
  const attraction = state.attractions.find((item) => item.id === elements.attractionSelect.value);
  if (attraction) {
    selectAttraction(attraction);
  } else {
    state.selectedAttraction = null;
    elements.selectedDestination.textContent = "尚未選擇目的地";
    resetRouteSummary();
  }
});

(async function init() {
  setLoading(true);
  try {
    setTheme("light");
    setControlsCollapsed(window.matchMedia("(max-width: 980px)").matches);
    setRouteCardCollapsed(false);
    await loadMapbox();
    await loadAttractions();
    setStatus("請取得位置");
  } catch (error) {
    setStatus("設定錯誤");
    elements.attractionSelect.innerHTML = "";
    const option = document.createElement("option");
    option.textContent = error.message;
    elements.attractionSelect.append(option);
    console.error(error);
  } finally {
    setLoading(false);
  }
})();
