<script setup>
import { computed } from "vue";
import { aqiClass, budgetLabel, uvLevelLabel, weatherClass } from "../utils/formatters";

const props = defineProps({
  place: { type: Object, required: true },
  rank: { type: Number, required: true },
  total: { type: Number, required: true },
  saved: { type: Boolean, default: false },
});

const emit = defineEmits(["view", "toggle-save"]);

function weatherLabel(place) {
  const summary = place.weather_summary || place.context?.weather?.summary || "天氣資料尚未取得";
  return place.weather_status === "watch" ? `天氣需留意：${summary}` : `天氣：${summary}`;
}

function uvBadge(place) {
  const uvIndex = place.uv_index ?? place.context?.uv?.uv_index;
  if (uvIndex === undefined || uvIndex === null || uvIndex === "") return null;
  const level = place.uv_exposure_level || place.context?.uv?.exposure_level || "";
  const className = level === "extreme" || level === "very_high" ? "warn" : level === "high" ? "cool" : "ok";
  return { text: `UV ${uvIndex}${level ? ` / ${uvLevelLabel(level)}` : ""}`, className };
}

function placeTag(place, rank) {
  if (rank === 1) return "最符合";
  if (place.indoor) return "室內選項";
  if (place.budget === "low") return "低預算友善";
  return "容易安排";
}

const uv = computed(() => uvBadge(props.place));
</script>

<template>
  <article class="place-card">
    <div>
      <div class="place-rank"><span class="dot"></span>第 {{ rank }} 個推薦 / 共 {{ total }} 個</div>
      <h3 class="place-name">{{ place.name }}</h3>
      <p class="place-meta">{{ place.category }} / {{ place.address?.split(",")[0] }}</p>
      <div class="badge-row">
        <span class="badge primary">{{ place.matched_travel_time ?? place.travel_time_minutes }} 分鐘可到</span>
        <span class="badge cool">{{ placeTag(place, rank) }}</span>
        <span class="badge" :class="weatherClass(place.weather_status)">{{ weatherLabel(place) }}</span>
        <span v-if="uv" class="badge" :class="uv.className">{{ uv.text }}</span>
        <span class="badge" :class="aqiClass(place.aqi_status)">AQI {{ place.aqi_value }} / {{ place.aqi_status }}</span>
        <span class="badge">{{ budgetLabel(place.budget) }}</span>
        <span class="badge" :class="place.open_now ? 'ok' : 'warn'">{{ place.open_now ? "營業中" : "未營業" }}</span>
      </div>
      <p class="place-reason">{{ place.reason }}</p>
      <p v-if="place.backup_options?.[0]" class="place-backup">
        <strong>附近備案：</strong>{{ place.backup_options[0].name }} / {{ place.backup_options[0].category }}
      </p>
    </div>

    <div class="score-dial" :style="{ '--score': place.score || 0 }">
      <div class="score-inner">
        <div class="score-value">{{ place.score || "--" }}</div>
        <div class="score-label">適合度</div>
      </div>
    </div>

    <div class="card-actions">
      <button class="btn-ghost" type="button" @click="emit('view', place.id)">查看詳情</button>
      <button class="btn-primary" :class="{ saved }" type="button" @click="emit('toggle-save', place)">
        {{ saved ? "已收藏" : "收藏地點" }}
      </button>
    </div>
  </article>
</template>
