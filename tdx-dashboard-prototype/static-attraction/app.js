const TAIPEI_CENTER = { lat: 25.0478, lng: 121.5319 };

const state = {
  attractions: [],
  selectedAttraction: null,
  origin: null,
  travelMode: "TRANSIT",
  map: null,
  geocoder: null,
  directionsService: null,
  directionsRenderer: null,
  originMarker: null,
  destinationMarker: null,
  searchTimer: null,
};

const elements = {
  systemStatus: document.querySelector("#systemStatus"),
  searchInput: document.querySelector("#searchInput"),
  refreshButton: document.querySelector("#refreshButton"),
  locateButton: document.querySelector("#locateButton"),
  setMapCenterButton: document.querySelector("#setMapCenterButton"),
  originLabel: document.querySelector("#originLabel"),
  travelModeLabel: document.querySelector("#travelModeLabel"),
  resultCount: document.querySelector("#resultCount"),
  attractionSelect: document.querySelector("#attractionSelect"),
  selectedDestination: document.querySelector("#selectedDestination"),
  routeTitle: document.querySelector("#routeTitle"),
  routeDistance: document.querySelector("#routeDistance"),
  routeDuration: document.querySelector("#routeDuration"),
  routeAddress: document.querySelector("#routeAddress"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

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

function normalizePlaces(data) {
  if (Array.isArray(data.places)) {
    return data.places.map((place) => ({
      id: place.id,
      name: place.name,
      district: place.district || "未標示行政區",
      theme: place.category || place.theme || place.type_label || "",
      type: place.type || "attraction",
      typeLabel: place.type_label || "景點",
      address: place.address || "",
      lat: Number.isFinite(Number(place.lat)) ? Number(place.lat) : null,
      lng: Number.isFinite(Number(place.lng)) ? Number(place.lng) : null,
      begin: place.begin || "",
      end: place.end || "",
      url: place.url || "",
      query: place.query || `${place.name} ${place.address || place.district || ""} 台北市`,
    }));
  }

  return flattenAttractions(data.districts || []).map((place) => ({
    ...place,
    type: "attraction",
    typeLabel: "景點",
    address: "",
    lat: null,
    lng: null,
    begin: "",
    end: "",
    url: "",
  }));
}

function resetRouteSummary() {
  elements.routeTitle.textContent = "等待路線規劃";
  elements.routeDistance.textContent = "--";
  elements.routeDuration.textContent = "--";
  elements.routeAddress.textContent = "--";
}

function formatOriginLabel(position, accuracy, sourceLabel) {
  const accuracyText = Number.isFinite(accuracy) ? `，約 ${Math.round(accuracy)}m` : "";
  return `${sourceLabel}: ${position.lat.toFixed(5)}, ${position.lng.toFixed(5)}${accuracyText}`;
}

async function loadGoogleMaps() {
  const response = await fetch("/api/maps-config");
  const config = await response.json();
  if (!response.ok) throw new Error(config.error || "Cannot load Google Maps config");
  if (!config.api_key) {
    throw new Error("Missing GOOGLE_MAPS_BROWSER_KEY or GOOGLE_MAPS_API_KEY");
  }

  await new Promise((resolve, reject) => {
    window.initGoogleRoutePlanner = resolve;
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(config.api_key)}&callback=initGoogleRoutePlanner`;
    script.async = true;
    script.defer = true;
    script.onerror = () => reject(new Error("Google Maps JavaScript API failed to load"));
    document.head.append(script);
  });

  state.map = new google.maps.Map(document.querySelector("#map"), {
    center: TAIPEI_CENTER,
    zoom: 13,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: true,
  });
  state.geocoder = new google.maps.Geocoder();
  state.directionsService = new google.maps.DirectionsService();
  state.directionsRenderer = new google.maps.DirectionsRenderer({
    map: state.map,
    suppressMarkers: true,
    preserveViewport: false,
  });
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

    state.attractions = normalizePlaces(data);
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

  if (!state.attractions.length) {
    return;
  }

  for (const attraction of state.attractions) {
    const option = document.createElement("option");
    option.value = attraction.id;
    const meta = [attraction.typeLabel, attraction.district, attraction.theme].filter(Boolean).join(" / ");
    option.textContent = `${attraction.name} / ${meta}`;
    option.selected = state.selectedAttraction?.id === attraction.id;
    elements.attractionSelect.append(option);
  }
}

function selectAttraction(attraction) {
  state.selectedAttraction = attraction;
  elements.selectedDestination.textContent = `${attraction.name} / ${attraction.typeLabel} / ${attraction.district}`;
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

  if (!state.originMarker) {
    state.originMarker = new google.maps.Marker({
      map: state.map,
      label: "你",
      title: "目前位置",
      draggable: true,
    });
    state.originMarker.addListener("dragend", () => {
      const position = state.originMarker.getPosition();
      setOrigin(
        { lat: position.lat(), lng: position.lng() },
        null,
        "手動修正"
      );
    });
  }
  state.originMarker.setPosition(state.origin);
  state.map.panTo(state.origin);
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
    if (watchId !== null) {
      navigator.geolocation.clearWatch(watchId);
    }
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
        elements.originLabel.textContent = formatOriginLabel(
          candidate.position,
          candidate.accuracy,
          "定位中"
        );
      }

      if (candidate.accuracy <= 50) {
        finish();
      }
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
  setOrigin(
    {
      lat: center.lat(),
      lng: center.lng(),
    },
    null,
    "地圖中心"
  );
  setStatus("已設定出發點");
}

function setDestinationMarker(location, title) {
  if (!state.destinationMarker) {
    state.destinationMarker = new google.maps.Marker({
      map: state.map,
      label: "終",
    });
  }
  state.destinationMarker.setPosition(location);
  state.destinationMarker.setTitle(title);
}

async function geocodeDestination(attraction) {
  if (Number.isFinite(attraction.lat) && Number.isFinite(attraction.lng)) {
    return {
      formatted_address: attraction.address || attraction.query,
      geometry: {
        location: new google.maps.LatLng(attraction.lat, attraction.lng),
      },
    };
  }

  const response = await state.geocoder.geocode({
    address: attraction.query,
    region: "TW",
  });

  if (!response.results.length) {
    throw new Error(`Cannot geocode ${attraction.name}`);
  }

  return response.results[0];
}

async function planRoute() {
  if (!state.map || !state.selectedAttraction) return;
  if (!state.origin) {
    setStatus("請先取得目前位置");
    return;
  }

  setStatus("規劃路線中");
  try {
    const destinationResult = await geocodeDestination(state.selectedAttraction);
    const destinationLocation = destinationResult.geometry.location;
    setDestinationMarker(destinationLocation, state.selectedAttraction.name);

    const result = await state.directionsService.route({
      origin: state.origin,
      destination: destinationLocation,
      travelMode: google.maps.TravelMode[state.travelMode],
      region: "TW",
      provideRouteAlternatives: false,
    });

    state.directionsRenderer.setDirections(result);
    const route = result.routes[0];
    const leg = route.legs[0];
    elements.routeTitle.textContent = route.summary || state.selectedAttraction.name;
    elements.routeDistance.textContent = leg.distance?.text || "--";
    elements.routeDuration.textContent = leg.duration?.text || "--";
    elements.routeAddress.textContent = leg.end_address || destinationResult.formatted_address;
    setStatus("路線完成");
  } catch (error) {
    setStatus("路線失敗");
    console.error(error);
  }
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
    await loadGoogleMaps();
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
