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
    <g v-else-if="name === 'scooter'">
      <path d="M8 8h8"></path>
      <path d="M9 8l-2 5v4"></path>
      <path d="M15 8l2 5v4"></path>
      <path d="M8 13h8"></path>
      <path d="M10 17h4"></path>
      <path d="M12 5v3"></path>
      <circle cx="9" cy="18" r="1.5"></circle>
      <circle cx="15" cy="18" r="1.5"></circle>
      <path d="M10 11h4"></path>
    </g>
    <g v-else-if="name === 'bicycle'">
      <circle cx="6" cy="17" r="3"></circle>
      <circle cx="18" cy="17" r="3"></circle>
      <path d="M6 17l4-8h4l4 8"></path>
      <path d="M10 9l3 8"></path>
      <path d="M10 13h6"></path>
      <path d="M13 9l2-3"></path>
      <path d="M14 6h3"></path>
      <path d="M9 7h3"></path>
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
    <g v-else-if="name === 'air'">
      <path d="M4 9h9a2.5 2.5 0 1 0-2.5-2.5"></path>
      <path d="M4 14h14a2.5 2.5 0 1 1-2.5 2.5"></path>
      <path d="M4 19h6"></path>
      <path d="M7 5h1"></path>
    </g>
    <g v-else-if="name === 'aqi'">
      <path d="M5 17a7 7 0 1 1 14 0"></path>
      <path d="M8 17h8"></path>
      <path d="M12 17l3-5"></path>
      <path d="M7.8 12.2l-1.4-.8"></path>
      <path d="M12 10V8.4"></path>
      <path d="M16.2 12.2l1.4-.8"></path>
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
    <g v-else-if="name === 'spark'">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"></path>
      <path d="M18 16l.8 2.2L21 19l-2.2.8L18 22l-.8-2.2L15 19l2.2-.8L18 16z"></path>
    </g>
    <g v-else-if="name === 'sound'">
      <path d="M5 15H3V9h2l5-4v14l-5-4z"></path>
      <path d="M14 9.5a4 4 0 0 1 0 5"></path>
      <path d="M17 7a8 8 0 0 1 0 10"></path>
    </g>
    <g v-else>
      <circle cx="12" cy="12" r="8"></circle>
      <path d="M12 8v4"></path>
      <path d="M12 16h.01"></path>
    </g>
  </svg>
</template>
