<script setup>
import { computed } from "vue";
import { BUDGET_LABELS, LOCATION_LABELS, MOODS, WEATHER_LABELS } from "../constants";
import { formatTime } from "../utils/formatters";
import PlaceCard from "./PlaceCard.vue";

const props = defineProps({
  criteria: { type: Object, required: true },
  results: { type: Array, required: true },
  savedIds: { type: Array, required: true },
});

const emit = defineEmits(["navigate", "view", "toggle-save"]);

const moodLabel = computed(() => {
  return MOODS.find((mood) => mood.id === props.criteria.mood)?.label || "適合出門";
});
</script>

<template>
  <div class="results-head">
    <button class="back-btn" type="button" @click="emit('navigate', '/')">返回</button>
    <div class="results-summary">
      依照 <em>{{ moodLabel }}</em>、<em>{{ formatTime(criteria.time) }}</em> 的空檔、
      從 <em>{{ LOCATION_LABELS[criteria.location] }}</em> 出發、<em>{{ WEATHER_LABELS[criteria.weatherPreference] }}</em>，
      以及 <em>{{ BUDGET_LABELS[criteria.budget] }}</em>，找到 {{ results.length }} 個適合的地點。
    </div>
  </div>

  <div class="results-list">
    <PlaceCard
      v-for="(place, index) in results"
      :key="place.id"
      :place="place"
      :rank="index + 1"
      :total="results.length"
      :saved="savedIds.includes(place.id)"
      @view="emit('view', $event)"
      @toggle-save="emit('toggle-save', $event)"
    />
  </div>

  <p class="results-footnote">
    不喜歡這些結果？
    <button class="link-button" type="button" @click="emit('navigate', '/')">調整心情或時間</button>
    後再試一次。
  </p>
</template>
