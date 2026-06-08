<script setup>
const props = defineProps({
  route: { type: String, required: true },
  savedCount: { type: Number, default: 0 },
});
const emit = defineEmits(["navigate"]);

function active(target) {
  if (target === "/") return props.route === "/";
  return props.route.startsWith(target);
}
</script>

<template>
  <nav class="bottom-nav" aria-label="Main navigation">
    <button :class="{ active: active('/') }" type="button" title="Home" @click="emit('navigate', '/')">
      <span class="nav-icon">H</span><span>Home</span>
    </button>
    <button :class="{ active: active('/results') }" type="button" title="Explore" @click="emit('navigate', '/results')">
      <span class="nav-icon">E</span><span>Explore</span>
    </button>
    <button :class="{ active: active('/saved') }" type="button" title="Plan" @click="emit('navigate', '/saved')">
      <span class="nav-icon">P</span><span>Plan</span><i v-if="savedCount">{{ savedCount }}</i>
    </button>
    <button :class="{ active: active('/account') }" type="button" title="Account" @click="emit('navigate', '/account')">
      <span class="nav-icon">@</span><span>Account</span>
    </button>
  </nav>
</template>
