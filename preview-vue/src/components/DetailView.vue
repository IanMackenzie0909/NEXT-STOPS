<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { LOCATION_LABELS } from "../constants";
import { getContext, getPlace } from "../api/nextStopsApi";
import {
  aqiClass,
  budgetLabel,
  formatAqi,
  formatComfort,
  formatPercent,
  formatRainfall,
  formatUv,
  formatWeatherNow,
  formatWind,
  weatherClass,
} from "../utils/formatters";

const props = defineProps({
  placeId: { type: String, required: true },
  fallbackPlace: { type: Object, default: null },
  criteria: { type: Object, required: true },
  saved: { type: Boolean, default: false },
});

const emit = defineEmits(["navigate", "toggle-save", "toast"]);

const place = ref(props.fallbackPlace);
const context = ref(null);
const loading = ref(true);
const contextLoading = ref(false);

const travelTime = computed(() => place.value?.matched_travel_time ?? place.value?.travel_time_minutes ?? 0);
const reason = computed(() => {
  const template = place.value?.reason || place.value?.reasonTemplate || "";
  return template.replace("${time}", travelTime.value);
});
const directionsUrl = computed(() => {
  if (!place.value) return "#";
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${place.value.name} ${place.value.address}`)}`;
});

const detailBadges = computed(() => {
  if (!place.value) return [];
  return [
    { text: `${travelTime.value} 分鐘可到`, className: "primary" },
    { text: place.value.weather_summary || "即時天氣見右側資訊", className: weatherClass(place.value.weather_status) },
    { text: `AQI ${place.value.aqi_value ?? "?"}`, className: aqiClass(place.value.aqi_status) },
    { text: budgetLabel(place.value.budget), className: "" },
    { text: place.value.open_now ? "營業中" : "未營業", className: place.value.open_now ? "ok" : "warn" },
  ];
});

async function loadPlace() {
  loading.value = true;
  try {
    place.value = await getPlace(props.placeId);
  } catch (error) {
    if (!place.value) {
      emit("toast", error.message);
      emit("navigate", "/");
    }
  } finally {
    loading.value = false;
  }
}

async function loadContext() {
  if (!place.value?.lat || !place.value?.lng) return;
  contextLoading.value = true;
  try {
    context.value = await getContext(place.value.lat, place.value.lng);
  } catch (error) {
    emit("toast", `即時情境資料無法取得：${error.message}`);
  } finally {
    contextLoading.value = false;
  }
}

function openBackup(name) {
  emit("toast", `${name} 之後可以延伸成備案詳情頁`);
}

onMounted(async () => {
  await loadPlace();
  await loadContext();
});

watch(() => props.placeId, async () => {
  place.value = props.fallbackPlace;
  context.value = null;
  await loadPlace();
  await loadContext();
});
</script>

<template>
  <div v-if="loading && !place" class="empty">
    <h3>正在載入地點...</h3>
  </div>

  <template v-else-if="place">
    <div class="detail-head">
      <button class="back-btn" type="button" @click="emit('navigate', '/results')">返回結果</button>
    </div>

    <section class="detail-hero">
      <div class="detail-hero-text">
        <span class="category-tag">{{ place.category }}</span>
        <h1>{{ place.name }}</h1>
        <p class="detail-address">{{ place.address }}</p>
        <div class="badge-row">
          <span v-for="badge in detailBadges" :key="badge.text" class="badge" :class="badge.className">{{ badge.text }}</span>
        </div>
        <div class="detail-actions">
          <button class="btn-primary" :class="{ saved }" type="button" @click="emit('toggle-save', place)">
            {{ saved ? "已收藏" : "收藏這個地點" }}
          </button>
          <a
            class="btn-ghost"
            target="_blank"
            rel="noreferrer"
            :href="directionsUrl"
          >
            開啟地圖導航
          </a>
        </div>
      </div>
      <div class="detail-map">
        <div class="map-shell">
          <div class="map-grid"></div>
          <div class="map-pin">位置</div>
          <div class="map-caption">{{ place.address }} / 地圖預覽</div>
        </div>
      </div>
    </section>

    <section class="detail-grid">
      <div class="card route-card">
        <h3>行程預覽</h3>
        <ul class="kv-list">
          <li><span>出發地</span><span class="kv-val">{{ LOCATION_LABELS[criteria.location] }}</span></li>
          <li><span>移動預估</span><span class="kv-val">{{ travelTime }} 分鐘</span></li>
          <li><span>路線感受</span><span class="kv-val">{{ place.route_hint }}</span></li>
          <li><span>時間適配</span><span class="kv-val">{{ criteria.time - travelTime * 2 >= 45 ? "符合你的時間空檔" : "時間偏緊但可行" }}</span></li>
        </ul>
      </div>

      <div class="card">
        <h3>為什麼適合你</h3>
        <p class="reason">{{ reason }}</p>
      </div>

      <div class="card">
        <h3>現在狀況</h3>
        <ul v-if="context" class="kv-list">
          <li><span>天氣</span><span class="kv-val">{{ formatWeatherNow(context) }}</span></li>
          <li><span>降雨機率</span><span class="kv-val">{{ formatPercent(context.weather?.rain_probability) }}</span></li>
          <li><span>10 分鐘雨量</span><span class="kv-val">{{ formatRainfall(context.weather?.precipitation_10min_mm) }}</span></li>
          <li><span>紫外線</span><span class="kv-val">{{ formatUv(context.uv) }}</span></li>
          <li><span>風速風向</span><span class="kv-val">{{ formatWind(context.weather?.wind_speed_mps, context.weather?.wind_direction_degrees) }}</span></li>
          <li><span>空氣品質</span><span class="kv-val">{{ formatAqi(context.air_quality) }}</span></li>
          <li><span>戶外舒適度</span><span class="kv-val">{{ formatComfort(context.outdoor_comfort) }}</span></li>
          <li><span>營業狀態</span><span class="kv-val">{{ place.open_now ? "營業中" : "未營業" }}</span></li>
          <li><span>評分</span><span class="kv-val">{{ Number(place.rating || 0).toFixed(1) }} / 5</span></li>
        </ul>
        <p v-else class="muted">{{ contextLoading ? "正在載入即時情境..." : "目前無法取得即時情境。" }}</p>
      </div>

      <div class="card">
        <h3>地點介紹</h3>
        <p>{{ place.description }}</p>
      </div>

      <div class="card">
        <h3>如果不太符合期待</h3>
        <ul class="backup-list">
          <li v-for="backup in place.backup_options || []" :key="backup.name" @click="openBackup(backup.name)">
            <span class="backup-name">{{ backup.name }}</span>
            <span class="backup-cat">{{ backup.category }}</span>
          </li>
        </ul>
      </div>
    </section>
  </template>
</template>
