<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 16 },
});
</script>

<template>
  <svg class="icon-glyph" :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true">
    <g v-if="name === 'walk'">
      <circle cx="13" cy="5" r="2"></circle>
      <path d="M11 8l-2 5 4 2 1 5"></path>
      <path d="M12 10l4 2"></path>
      <path d="M9 13l-3 6"></path>
    </g>
    <g v-else-if="name === 'bus'">
      <path d="M6 4h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"></path>
      <path d="M4 10h16"></path>
      <path d="M7 17v2"></path>
      <path d="M17 17v2"></path>
      <circle cx="8" cy="14" r="1"></circle>
      <circle cx="16" cy="14" r="1"></circle>
    </g>
    <g v-else-if="name === 'train'">
      <path d="M7 3h10a2 2 0 0 1 2 2v9a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V5a2 2 0 0 1 2-2z"></path>
      <path d="M8 8h8"></path>
      <path d="M8 13h.01"></path>
      <path d="M16 13h.01"></path>
      <path d="M9 18l-2 3"></path>
      <path d="M15 18l2 3"></path>
    </g>
    <g v-else-if="name === 'car'">
      <path d="M5 12l2-5h10l2 5"></path>
      <path d="M4 12h16v5H4z"></path>
      <circle cx="7" cy="17" r="1"></circle>
      <circle cx="17" cy="17" r="1"></circle>
    </g>
    <g v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="4"></circle>
      <path d="M12 2v2"></path>
      <path d="M12 20v2"></path>
      <path d="M4.9 4.9l1.4 1.4"></path>
      <path d="M17.7 17.7l1.4 1.4"></path>
      <path d="M2 12h2"></path>
      <path d="M20 12h2"></path>
      <path d="M4.9 19.1l1.4-1.4"></path>
      <path d="M17.7 6.3l1.4-1.4"></path>
    </g>
    <g v-else-if="name === 'cloud'">
      <path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.8A3.2 3.2 0 0 0 7 18z"></path>
    </g>
    <g v-else-if="name === 'rain'">
      <path d="M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.8A3.2 3.2 0 0 0 7 15z"></path>
      <path d="M8 19l-1 2"></path>
      <path d="M13 19l-1 2"></path>
      <path d="M18 19l-1 2"></path>
    </g>
    <g v-else-if="name === 'wind'">
      <path d="M4 8h10a3 3 0 1 0-3-3"></path>
      <path d="M4 13h14a3 3 0 1 1-3 3"></path>
      <path d="M4 18h7"></path>
    </g>
    <g v-else-if="name === 'thermometer'">
      <path d="M14 14.8V5a2 2 0 1 0-4 0v9.8a4 4 0 1 0 4 0z"></path>
      <path d="M12 9v7"></path>
    </g>
    <g v-else-if="name === 'map'">
      <path d="M9 18l-6 3V6l6-3 6 3 6-3v15l-6 3-6-3z"></path>
      <path d="M9 3v15"></path>
      <path d="M15 6v15"></path>
    </g>
    <g v-else-if="name === 'plus'">
      <path d="M12 5v14"></path>
      <path d="M5 12h14"></path>
    </g>
    <g v-else>
      <circle cx="12" cy="12" r="8"></circle>
      <path d="M12 8v4"></path>
      <path d="M12 16h.01"></path>
    </g>
  </svg>
</template>
