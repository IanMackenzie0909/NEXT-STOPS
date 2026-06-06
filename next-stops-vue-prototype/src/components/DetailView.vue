<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { getContext, getMapboxConfig, getPlace, getRoute, googleDirectionsUrl } from "../api/nextStopsApi";
import IconGlyph from "./IconGlyph.vue";
import { LOCATION_FALLBACK_LABEL } from "../constants";
import { budgetLabel, commuteParts, weatherChips } from "../utils/formatters";

const props = defineProps({
  placeId: { type: String, required: true },
  fallbackPlace: { type: Object, default: null },
  criteria: { type: Object, required: true },
  saved: { type: Boolean, default: false },
});
const emit = defineEmits(["navigate", "toggle-save", "toast"]);

const place = ref(props.fallbackPlace);
const context = ref(null);
const routeData = ref(null);
const mapStatus = ref("地圖準備中");
const mapContainer = ref(null);
const loading = ref(true);
const travelTime = computed(() => place.value?.matched_travel_time ?? place.value?.travel_time_minutes ?? 0);
const commute = computed(() => routeData.value?.best || place.value?.commute || null);
const commuteInfo = computed(() => commuteParts(commute.value, travelTime.value));
const detailWeatherChips = computed(() => weatherChips(context.value, place.value?.weather_summary));
const origin = computed(() => (
  props.criteria.lat !== null && props.criteria.lat !== undefined && props.criteria.lon !== null && props.criteria.lon !== undefined
    ? { lat: props.criteria.lat, lon: props.criteria.lon }
    : null
));
const destination = computed(() => (
  place.value?.lat !== null && place.value?.lat !== undefined && (place.value?.lon !== null && place.value?.lon !== undefined || place.value?.lng !== null && place.value?.lng !== undefined)
    ? { lat: place.value.lat, lon: place.value.lon ?? place.value.lng }
    : null
));
const mapsUrl = computed(() => googleDirectionsUrl(origin.value, destination.value || {}, commute.value?.mode || "TRANSIT"));

let map;
let originMarker;
let destinationMarker;

function lngLatFromPoint(point) {
  if (!point) return null;
  const lat = Number(point.lat);
  const lon = Number(point.lon ?? point.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lon, lat];
}

function lngLatFromCoordinate(coord) {
  if (!Array.isArray(coord) || coord.length < 2) return null;
  const lon = Number(coord[0]);
  const lat = Number(coord[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lon, lat];
}

function clearMapRoute() {
  if (!map?.isStyleLoaded()) return;
  for (const layer of ["route-dash", "route-line", "route-casing"]) {
    if (map.getLayer(layer)) map.removeLayer(layer);
  }
  if (map.getSource("route")) map.removeSource("route");
}

function markerElement(label, kind) {
  const el = document.createElement("div");
  el.className = `route-marker ${kind}`;
  el.innerHTML = `<span>${label}</span>`;
  return el;
}

function renderMapRoute(route) {
  if (!map || !route?.geometry?.coordinates?.length) return;
  const start = route.origin;
  const end = route.destination;
  const startLngLat = lngLatFromPoint(start);
  const endLngLat = lngLatFromPoint(end);
  const coordinates = route.geometry.coordinates.map(lngLatFromCoordinate).filter(Boolean);
  if (!startLngLat || !endLngLat) {
    mapStatus.value = "路線座標格式錯誤";
    return;
  }
  if (coordinates.length < 2) {
    mapStatus.value = "路線 geometry 格式錯誤";
    return;
  }

  clearMapRoute();
  map.addSource("route", {
    type: "geojson",
    data: {
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates },
    },
  });
  map.addLayer({
    id: "route-casing",
    type: "line",
    source: "route",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 12, "line-opacity": 0.92 },
  });
  map.addLayer({
    id: "route-line",
    type: "line",
    source: "route",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#5f9278", "line-width": 7, "line-opacity": 0.96 },
  });
  map.addLayer({
    id: "route-dash",
    type: "line",
    source: "route",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#d49a3a", "line-width": 2.5, "line-dasharray": [0.4, 2.4] },
  });

  if (!originMarker) {
    originMarker = new globalThis.mapboxgl.Marker({ element: markerElement("你", "origin"), anchor: "bottom" })
      .setLngLat(startLngLat)
      .addTo(map);
  } else {
    originMarker.setLngLat(startLngLat);
  }
  if (!destinationMarker) {
    destinationMarker = new globalThis.mapboxgl.Marker({ element: markerElement("到", "destination"), anchor: "bottom" })
      .setLngLat(endLngLat)
      .addTo(map);
  } else {
    destinationMarker.setLngLat(endLngLat);
  }

  const bounds = new globalThis.mapboxgl.LngLatBounds();
  for (const coord of coordinates) bounds.extend(coord);
  bounds.extend(startLngLat);
  bounds.extend(endLngLat);
  map.fitBounds(bounds, { padding: 58, maxZoom: 15.5 });
}

async function loadRouteMap() {
  routeData.value = null;
  if (!origin.value || !destination.value) {
    mapStatus.value = "需要目前定位與目的地座標才能顯示路線";
    return;
  }

  try {
    routeData.value = await getRoute(origin.value, destination.value);
  } catch (error) {
    mapStatus.value = `路線資料無法取得：${error.message}`;
    return;
  }

  await nextTick();
  if (!mapContainer.value) return;
  try {
    const config = await getMapboxConfig();
    if (!config.configured || !config.access_token) {
      mapStatus.value = "Mapbox token 尚未設定，請使用 Google Maps 開啟路線";
      return;
    }
    if (!globalThis.mapboxgl) {
      mapStatus.value = "Mapbox GL 載入失敗";
      return;
    }
    globalThis.mapboxgl.accessToken = config.access_token;
    if (!map) {
      map = new globalThis.mapboxgl.Map({
        container: mapContainer.value,
        style: "mapbox://styles/mapbox/standard",
        center: [destination.value.lon, destination.value.lat],
        zoom: 13,
        pitch: 46,
        bearing: 18,
        antialias: true,
        cooperativeGestures: true,
      });
      map.addControl(new globalThis.mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");
      await new Promise((resolve) => map.on("load", resolve));
      if (typeof map.setConfigProperty === "function") {
        try {
          map.setConfigProperty("basemap", "showTransitLabels", true);
          map.setConfigProperty("basemap", "showPointOfInterestLabels", true);
        } catch {
          // Older Mapbox styles can render routes without these optional label toggles.
        }
      }
    }
    renderMapRoute(routeData.value.best);
    mapStatus.value = `${routeData.value.best.duration_text} ${routeData.value.best.mode_label}`;
  } catch (error) {
    mapStatus.value = `地圖無法載入：${error.message}`;
  }
}

async function loadPlace() {
  loading.value = true;
  try {
    place.value = await getPlace(props.placeId);
    if (destination.value) context.value = await getContext(destination.value.lat, destination.value.lon).catch(() => null);
    await loadRouteMap();
  } catch (error) {
    emit("toast", error.message);
    if (!place.value) emit("navigate", "/results");
  } finally {
    loading.value = false;
  }
}

onMounted(loadPlace);
watch(() => props.placeId, () => {
  place.value = props.fallbackPlace;
  context.value = null;
  routeData.value = null;
  loadPlace();
});
</script>

<template>
  <main class="screen detail-screen">
    <div v-if="loading && !place" class="empty-state">
      <h2>Loading...</h2>
    </div>

    <template v-else-if="place">
      <header class="screen-header">
        <button class="back-button" type="button" @click="emit('navigate', '/results')">‹</button>
        <div>
          <p class="muted">MATCH SCORE {{ place.score }}%</p>
          <h1>{{ place.name }}</h1>
        </div>
      </header>

      <section class="detail-map-card">
        <div ref="mapContainer" class="mapbox-route" role="img" :aria-label="`${place.name} 路線地圖`"></div>
        <div class="map-route-status">
          <span class="commute-inline">
            <IconGlyph :name="commuteInfo.icon" />
            <strong>{{ commuteInfo.duration }}</strong>
            <span>{{ commuteInfo.mode }}</span>
          </span>
          <small>{{ mapStatus }}</small>
        </div>
      </section>

      <aside class="detail-sidebar">
        <section class="detail-copy">
          <p>{{ place.description }}</p>
          <div class="detail-info-grid">
            <span class="info-chip commute-chip">
              <IconGlyph :name="commuteInfo.icon" />
              <strong>{{ commuteInfo.duration }}</strong>
              <small>{{ commuteInfo.mode }}</small>
            </span>
            <span><strong>{{ budgetLabel(place.budget) }}</strong><small>預算</small></span>
            <span><strong>{{ place.score }}%</strong><small>Match</small></span>
          </div>
          <div class="weather-chip-grid" aria-label="即時天氣">
            <span v-for="item in detailWeatherChips" :key="item.key" class="weather-chip" :class="item.className">
              <IconGlyph :name="item.icon" />
              <strong>{{ item.label }}</strong>
            </span>
          </div>
        </section>

        <section class="reason-list">
          <div><strong>Why now</strong><span>{{ place.reason }}</span></div>
          <div><strong>Route</strong><span>{{ place.route_hint }}</span></div>
          <div><strong>Start</strong><span>{{ criteria.locationLabel || LOCATION_FALLBACK_LABEL }}</span></div>
        </section>

        <div class="action-row">
          <button class="primary-action" type="button" @click="emit('toggle-save', place)">
            <IconGlyph name="plus" />
            <span>{{ saved ? "Saved today" : "Add to today" }}</span>
          </button>
          <a class="ghost-action map-action" target="_blank" rel="noreferrer" :href="mapsUrl">
            <IconGlyph name="map" />
            <span>Google Maps</span>
          </a>
        </div>
      </aside>
    </template>
  </main>
</template>
