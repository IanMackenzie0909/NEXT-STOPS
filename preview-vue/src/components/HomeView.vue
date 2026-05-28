<script setup>
import { MOODS, LOCATION_LABELS, PRESETS } from "../constants";
import { formatTime } from "../utils/formatters";

defineProps({
  criteria: { type: Object, required: true },
  loading: { type: Boolean, default: false },
});

const emit = defineEmits(["update:criteria", "find"]);

function patch(updates) {
  emit("update:criteria", updates);
}

function applyPreset(key) {
  const preset = PRESETS[key];
  if (preset) patch(preset);
}
</script>

<template>
  <section class="hero">
    <p class="eyebrow">用更智慧的方式決定下一站</p>
    <h1 class="hero-title">現在不知道要<em>去哪裡</em>嗎？</h1>
    <p class="hero-sub">
      告訴 NEXT STOPS 你現在的心情，我們會依照時間、天氣、距離與預算，
      推薦適合當下出門的地點，並說清楚推薦原因。
    </p>
  </section>

  <section class="card panel">
    <div class="step">
      <div class="step-head">
        <span class="step-num">1</span>
        <h2 class="step-title">你現在想要什麼樣的感覺？</h2>
      </div>
      <div class="chip-grid">
        <button
          v-for="mood in MOODS"
          :key="mood.id"
          class="chip"
          :class="{ selected: criteria.mood === mood.id }"
          type="button"
          @click="patch({ mood: criteria.mood === mood.id ? null : mood.id })"
        >
          <span class="chip-icon" aria-hidden="true">{{ mood.icon }}</span>
          <span>{{ mood.label }}</span>
        </button>
      </div>
    </div>

    <div class="step">
      <div class="step-head">
        <span class="step-num">2</span>
        <h2 class="step-title">你有多少空檔？</h2>
      </div>
      <div class="slider-row">
        <input
          type="range"
          min="30"
          max="300"
          step="15"
          :value="criteria.time"
          @input="patch({ time: Number($event.target.value) })"
        />
        <div class="slider-value">目前有 <strong>{{ formatTime(criteria.time) }}</strong> 可以安排</div>
      </div>
    </div>

    <div class="step">
      <div class="step-head">
        <span class="step-num">3</span>
        <h2 class="step-title">你願意花多少時間移動？</h2>
      </div>
      <div class="slider-row">
        <input
          type="range"
          min="10"
          max="90"
          step="5"
          :value="criteria.distance"
          @input="patch({ distance: Number($event.target.value) })"
        />
        <div class="slider-value">最多移動 <strong>{{ criteria.distance }} 分鐘</strong></div>
      </div>
    </div>

    <div class="context-grid">
      <label class="context-field">
        <span>出發區域</span>
        <select :value="criteria.location" @change="patch({ location: $event.target.value })">
          <option v-for="(label, value) in LOCATION_LABELS" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label class="context-field">
        <span>天氣舒適度</span>
        <select :value="criteria.weatherPreference" @change="patch({ weatherPreference: $event.target.value })">
          <option value="any">戶外也可以</option>
          <option value="indoor">想待在室內</option>
          <option value="avoid_rain">避開下雨風險</option>
        </select>
      </label>
      <label class="context-field">
        <span>預算</span>
        <select :value="criteria.budget" @change="patch({ budget: $event.target.value })">
          <option value="medium">中等</option>
          <option value="low">低預算</option>
          <option value="flexible">彈性</option>
        </select>
      </label>
    </div>

    <div class="presets">
      <span class="presets-label">快速設定</span>
      <button v-for="(preset, key) in PRESETS" :key="key" class="preset" type="button" @click="applyPreset(key)">
        {{ preset.label }}
      </button>
    </div>

    <button class="cta" type="button" :disabled="!criteria.mood || loading" @click="emit('find')">
      {{ criteria.mood ? (loading ? "正在尋找..." : "尋找我的下一站") : "先選一個心情再繼續" }}
      <span aria-hidden="true">→</span>
    </button>
  </section>

  <section class="how">
    <h3>運作方式</h3>
    <ol class="how-steps">
      <li><strong>選一個心情。</strong>不用先想好去哪，只要描述當下狀態。</li>
      <li><strong>檢查即時情境。</strong>整合天氣、空氣品質、時間與距離。</li>
      <li><strong>取得精簡推薦。</strong>每個地點都附上實際可讀的原因。</li>
    </ol>
  </section>
</template>
