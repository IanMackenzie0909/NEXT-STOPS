<script setup>
defineProps({ message: { type: String, default: "" } });
</script>

<template>
  <div class="toast" :class="{ show: message }">{{ message }}</div>
</template>
