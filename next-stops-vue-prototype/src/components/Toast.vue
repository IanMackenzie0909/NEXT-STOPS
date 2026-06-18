<script setup>
import { computed } from "vue";

const props = defineProps({ message: { type: [String, Object], default: "" } });

const normalized = computed(() => {
  if (!props.message) return null;
  if (typeof props.message === "string") {
    return { text: props.message, tone: "default" };
  }
  return {
    title: props.message.title || "",
    text: props.message.message || props.message.text || "",
    meta: props.message.meta || "",
    tone: props.message.tone || "default",
  };
});
</script>

<template>
  <div class="toast" :class="[{ show: normalized }, normalized?.tone ? `tone-${normalized.tone}` : '']">
    <span v-if="normalized?.title" class="toast-icon" aria-hidden="true">!</span>
    <span class="toast-copy">
      <strong v-if="normalized?.title">{{ normalized.title }}</strong>
      <span>{{ normalized?.text }}</span>
      <small v-if="normalized?.meta">{{ normalized.meta }}</small>
    </span>
  </div>
</template>
