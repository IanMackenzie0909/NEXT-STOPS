<script setup>
defineProps({
  route: { type: String, required: true },
  savedCount: { type: Number, default: 0 },
});

const emit = defineEmits(["navigate"]);
</script>

<template>
  <header class="topbar">
    <button class="brand" type="button" @click="emit('navigate', '/')">
      <span class="brand-mark">NS</span>
      <span class="brand-name">NEXT STOPS</span>
    </button>
    <nav class="nav" aria-label="主要導覽">
      <button class="nav-link" :class="{ active: route === '/' }" type="button" @click="emit('navigate', '/')">
        首頁
      </button>
      <button class="nav-link" :class="{ active: route === '/saved' }" type="button" @click="emit('navigate', '/saved')">
        收藏 <span class="saved-count">{{ savedCount }}</span>
      </button>
    </nav>
  </header>
</template>
