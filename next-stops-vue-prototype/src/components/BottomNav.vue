<script setup>
const props = defineProps({
  route: { type: String, required: true },
  savedCount: { type: Number, default: 0 },
  user: { type: Object, default: null },
});
const emit = defineEmits(["navigate"]);

function active(target) {
  if (target === "/") return props.route === "/";
  return props.route.startsWith(target);
}

function initial(value) {
  return String(value || "N").slice(0, 1).toUpperCase();
}
</script>

<template>
  <nav class="bottom-nav" aria-label="主要導覽">
    <button :class="{ active: active('/') }" type="button" title="Home" @click="emit('navigate', '/')">
      <span class="nav-icon">⌂</span><span>Home</span>
    </button>
    <button :class="{ active: active('/results') }" type="button" title="Explore" @click="emit('navigate', '/results')">
      <span class="nav-icon">⌕</span><span>Explore</span>
    </button>
    <button :class="{ active: active('/saved') }" type="button" title="Plan" @click="emit('navigate', '/saved')">
      <span class="nav-icon">✓</span><span>Plan</span><i v-if="savedCount">{{ savedCount }}</i>
    </button>
    <button :class="{ active: active('/profile') }" type="button" title="Profile" @click="emit('navigate', '/profile')">
      <span class="nav-avatar" aria-hidden="true">
        <img v-if="user?.avatar_url" :src="user.avatar_url" alt="" />
        <span v-else>{{ initial(user?.name || user?.account) }}</span>
      </span>
      <span>Profile</span>
    </button>
  </nav>
</template>
