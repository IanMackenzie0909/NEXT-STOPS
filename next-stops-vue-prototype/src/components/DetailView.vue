<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { getContext, getMapboxConfig, getPlace, getRoute, googleDirectionsUrl } from "../api/nextStopsApi";
import IconGlyph from "./IconGlyph.vue";
import TransportIcon from "./TransportIcon.vue";
import { LOCATION_FALLBACK_LABEL } from "../constants";
import { aqiChip, budgetLabel, commuteParts, openingLabel, weatherChips } from "../utils/formatters";

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
const descriptionExpanded = ref(false);
const travelTime = computed(() => place.value?.matched_travel_time ?? place.value?.travel_time_minutes ?? 0);
const commute = computed(() => routeData.value?.best || place.value?.commute || null);
const commuteInfo = computed(() => commuteParts(commute.value, travelTime.value));
const routeOptions = computed(() => (
  Array.isArray(routeData.value?.options)
    ? routeData.value.options.filter((option) => option?.mode)
    : []
));
const openingSourceText = computed(() => {
  const source = place.value?.opening_status_source;
  if (place.value?.open_now === true || place.value?.open_now === false) {
    if (source === "google_places") return "Google Places 已確認";
    if (source === "opening_hours") return "景點資料已確認";
    return "即時資料已確認";
  }
  return "資料來源不足，請以 Google Maps 為準";
});
const transitSummary = computed(() => {
  const transit = commute.value?.transit;
  if (!transit) return "";
  const parts = [];
  if (transit.board_count) parts.push(`${transit.board_count} 段搭乘`);
  if (transit.transfer_count) parts.push(`${transit.transfer_count} 次轉乘`);
  if (transit.walking_duration_text) parts.push(`步行約 ${transit.walking_duration_text}`);
  return parts.join(" / ");
});
const detailWeatherChips = computed(() => weatherChips(context.value, place.value?.weather_summary));
const detailAqiChip = computed(() => aqiChip(context.value, place.value?.aqi_value, place.value?.aqi_status));
const backupOptions = computed(() => Array.isArray(place.value?.backup_options) ? place.value.backup_options.filter(Boolean).slice(0, 3) : []);
const descriptionShouldCollapse = computed(() => String(place.value?.description || "").length > 220);
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
const mapsUrl = computed(() => googleDirectionsUrl(origin.value, place.value || destination.value || {}, commute.value?.mode || "TRANSIT"));

let map;
let originMarker;
let destinationMarker;
let mapResizeObserver;

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

function ensureMarkers(startLngLat, endLngLat) {
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
}

function markerElement(label, kind) {
  const el = document.createElement("div");
  el.className = `route-marker ${kind}`;
  el.innerHTML = `<span>${label}</span>`;
  return el;
}

function renderMapRoute(route) {
  if (!map || !route) {
    mapStatus.value = "路線資料尚未就緒";
    return;
  }
  map.resize();
  const start = route.origin;
  const end = route.destination;
  const startLngLat = lngLatFromPoint(start);
  const endLngLat = lngLatFromPoint(end);
  if (!startLngLat || !endLngLat) {
    mapStatus.value = "路線座標格式錯誤";
    return;
  }
  clearMapRoute();

  if (route?.available === false || !route?.geometry?.coordinates?.length) {
    ensureMarkers(startLngLat, endLngLat);
    const bounds = new globalThis.mapboxgl.LngLatBounds();
    bounds.extend(startLngLat);
    bounds.extend(endLngLat);
    map.fitBounds(bounds, { padding: 64, maxZoom: 14.5, pitch: 0, bearing: 0 });
    mapStatus.value = route?.available === false
      ? "所選交通方式沒有有效路線，請調整交通方式或用 Google Maps 查看替代方案"
      : "尚未取得路線線段，已標示起點與目的地";
    return;
  }

  const coordinates = route.geometry.coordinates.map(lngLatFromCoordinate).filter(Boolean);
  if (coordinates.length < 2) {
    mapStatus.value = "路線 geometry 格式錯誤";
    return;
  }

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

  ensureMarkers(startLngLat, endLngLat);

  const bounds = new globalThis.mapboxgl.LngLatBounds();
  for (const coord of coordinates) bounds.extend(coord);
  bounds.extend(startLngLat);
  bounds.extend(endLngLat);
  map.fitBounds(bounds, { padding: 58, maxZoom: 15.5, pitch: 0, bearing: 0 });
  mapStatus.value = "已依最短通勤時間繪製路線";
}

function observeMapSize() {
  if (!mapContainer.value || mapResizeObserver || !globalThis.ResizeObserver) return;
  mapResizeObserver = new globalThis.ResizeObserver(() => {
    if (!map) return;
    requestAnimationFrame(() => map?.resize());
  });
  mapResizeObserver.observe(mapContainer.value);
}

async function loadRouteMap() {
  routeData.value = null;
  if (!origin.value || !destination.value) {
    mapStatus.value = "需要目前定位與目的地座標才能顯示路線";
    return;
  }

  try {
    routeData.value = await getRoute(origin.value, destination.value, props.criteria.transportModes || []);
  } catch (error) {
    mapStatus.value = `路線資料無法取得：${error.message}`;
    return;
  }

  await nextTick();
  if (!mapContainer.value) return;
  observeMapSize();
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
        pitch: 0,
        bearing: 0,
        dragRotate: false,
        pitchWithRotate: false,
        antialias: false,
        cooperativeGestures: true,
      });
      map.touchZoomRotate.disableRotation();
      map.addControl(new globalThis.mapboxgl.NavigationControl({ visualizePitch: false, showCompass: false }), "top-right");
      await new Promise((resolve) => map.on("load", resolve));
      if (typeof map.setConfigProperty === "function") {
        try {
          map.setConfigProperty("basemap", "show3dObjects", false);
          map.setConfigProperty("basemap", "showTransitLabels", true);
          map.setConfigProperty("basemap", "showPointOfInterestLabels", true);
        } catch {
          // Older Mapbox styles can render routes without these optional label toggles.
        }
      }
    }
    renderMapRoute(routeData.value.best);
  } catch (error) {
    mapStatus.value = `地圖無法載入：${error.message}`;
  }
}

async function loadPlace() {
  loading.value = true;
  try {
    place.value = await getPlace(props.placeId, props.criteria);
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
onBeforeUnmount(() => {
  mapResizeObserver?.disconnect();
  mapResizeObserver = null;
  originMarker?.remove();
  destinationMarker?.remove();
  map?.remove();
  originMarker = null;
  destinationMarker = null;
  map = null;
});

watch(descriptionExpanded, async () => {
  await nextTick();
  map?.resize();
});

watch(() => props.placeId, () => {
  place.value = props.fallbackPlace;
  context.value = null;
  routeData.value = null;
  descriptionExpanded.value = false;
  loadPlace();
});
</script>

<template>
  <main class="screen detail-screen">
    <div v-if="loading && !place" class="loading-state detail-loading-state" role="status" aria-live="polite">
      <div class="loading-visual" aria-hidden="true">
        <div class="loader-calm">
          <span class="calm-ring one"></span>
          <span class="calm-ring two"></span>
          <span class="calm-dot main"></span>
          <span class="calm-dot drift"></span>
          <span class="calm-path"></span>
        </div>
        <div class="route-preview">
          <span class="route-thread"></span>
          <span class="node start"></span>
          <span class="node mid"></span>
          <span class="node end"></span>
        </div>
        <div class="loading-card-stack">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
      <h2>正在整理地點細節</h2>
      <p>載入路線、營業狀態與即時環境資料。</p>
      <div class="loading-steps">
        <span>地點資料</span>
        <span>通勤路線</span>
        <span>即時狀態</span>
      </div>
    </div>

    <template v-else-if="place">
      <header class="screen-header">
        <div>
          <p class="muted">MATCH SCORE {{ place.score }}%</p>
          <h1>{{ place.name }}</h1>
        </div>
      </header>

      <section class="detail-map-card">
        <div ref="mapContainer" class="mapbox-route" role="img" :aria-label="`${place.name} 路線地圖`"></div>
        <div class="map-route-status">
          <span class="commute-inline">
            <TransportIcon :name="commuteInfo.icon" :label="commuteInfo.mode" />
            <strong>{{ commuteInfo.duration }}</strong>
          </span>
          <small>{{ mapStatus }}</small>
        </div>
      </section>

      <aside class="detail-sidebar">
        <section class="detail-copy">
          <div class="description-block" :class="{ collapsed: descriptionShouldCollapse && !descriptionExpanded }">
            <p>{{ place.description }}</p>
          </div>
          <button
            v-if="descriptionShouldCollapse"
            class="description-toggle"
            type="button"
            @click="descriptionExpanded = !descriptionExpanded"
          >
            {{ descriptionExpanded ? "收合說明" : "展開完整說明" }}
          </button>
          <div class="detail-info-grid">
            <span class="info-chip commute-chip" :class="{ unavailable: commuteInfo.unavailable }">
              <TransportIcon :name="commuteInfo.icon" :label="commuteInfo.mode" />
              <strong>{{ commuteInfo.duration }}</strong>
              <small>通勤時間</small>
            </span>
            <span><strong>{{ budgetLabel(place.budget) }}</strong><small>預算</small></span>
            <span class="info-chip status-chip">
              <IconGlyph name="spark" />
              <strong>{{ openingLabel(place) }}</strong>
              <small>{{ openingSourceText }}</small>
            </span>
            <span><strong>{{ place.score }}%</strong><small>Match</small></span>
          </div>
          <div class="weather-chip-grid" aria-label="即時天氣">
            <span v-for="item in detailWeatherChips" :key="item.key" class="weather-chip" :class="item.className">
              <IconGlyph :name="item.icon" />
              <strong>{{ item.label }}</strong>
            </span>
            <span class="weather-chip aqi-chip" :class="detailAqiChip.className">
              <IconGlyph :name="detailAqiChip.icon" />
              <strong>{{ detailAqiChip.label }}</strong>
              <small>{{ detailAqiChip.detail }}</small>
            </span>
          </div>
        </section>

        <section class="reason-list">
          <div><strong>Why now</strong><span>{{ place.reason }}</span></div>
          <div>
            <strong>Route</strong>
            <span>{{ place.route_hint }}</span>
            <small v-if="transitSummary" class="route-subhint">{{ transitSummary }}</small>
            <div v-if="routeOptions.length > 1" class="route-option-list" aria-label="交通方式比較">
              <span
                v-for="option in routeOptions"
                :key="option.mode"
                class="route-option-chip"
                :class="{ unavailable: option.available === false, selected: option.mode === commute?.mode }"
              >
                <TransportIcon :name="option.mode" :label="option.mode_label" />
                <strong>{{ option.mode_label }}</strong>
                <small>{{ option.available === false ? "不可用" : option.duration_text }}</small>
              </span>
            </div>
          </div>
          <div><strong>Start</strong><span>{{ criteria.locationLabel || LOCATION_FALLBACK_LABEL }}</span></div>
        </section>

        <section class="backup-list">
          <strong>Nearby backups</strong>
          <template v-if="backupOptions.length">
            <button
              v-for="option in backupOptions"
              :key="option.id || option.name"
              class="backup-item"
              type="button"
              @click="option.id && emit('navigate', `/place/${option.id}`)"
            >
              <span>{{ option.name }}</span>
              <small>{{ option.category || "備案" }}</small>
            </button>
          </template>
          <p v-else>目前沒有足夠資料產生附近備案；可先用 Google Maps 查看周邊。</p>
        </section>

        <div class="action-row">
          <button class="primary-action save-today-action" :class="{ saved }" type="button" @click="emit('toggle-save', place)">
            <IconGlyph :name="saved ? 'check' : 'plus'" />
            <span>{{ saved ? "In today plan" : "Add to today" }}</span>
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
