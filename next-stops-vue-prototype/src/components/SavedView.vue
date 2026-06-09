<script setup>
defineProps({ saved: { type: Array, required: true } });
const emit = defineEmits(["navigate", "remove", "update-note"]);
</script>

<template>
  <main class="screen saved-screen">
    <header class="screen-header">
      <div>
        <p class="muted">Today plan</p>
        <h1>Saved stops</h1>
      </div>
    </header>

    <section v-if="saved.length" class="result-list">
      <article v-for="place in saved" :key="place.id" class="saved-card">
        <h2>{{ place.name }}</h2>
        <p>{{ place.category }} / {{ place.address }}</p>
        <textarea :value="place.note" placeholder="Add a small note..." @change="emit('update-note', place.id, $event.target.value)"></textarea>
        <div class="card-footer">
          <button class="ghost-action" type="button" @click="emit('navigate', `/place/${place.id}`)">Detail</button>
          <button class="ghost-action danger" type="button" @click="emit('remove', place.id)">Remove</button>
        </div>
      </article>
    </section>

    <section v-else class="empty-state">
      <h2>No stops saved</h2>
      <p>把推薦加入今天清單後，會在這裡整理。</p>
      <button class="primary-action" type="button" @click="emit('navigate', '/')">Find stops</button>
    </section>
  </main>
</template>
