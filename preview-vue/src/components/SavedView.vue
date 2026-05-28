<script setup>
defineProps({
  saved: { type: Array, required: true },
});

const emit = defineEmits(["navigate", "remove", "update-note", "toast"]);
</script>

<template>
  <section class="saved-head">
    <h1>你的收藏地點</h1>
    <p class="saved-sub">把想再回來看的地點先放在這裡。</p>
  </section>

  <div class="saved-list">
    <div v-if="saved.length === 0" class="empty">
      <h3>目前還沒有收藏</h3>
      <p>看到想保留的地點時，按下收藏，它就會出現在這裡。</p>
      <button class="btn-primary" type="button" @click="emit('navigate', '/')">尋找地點</button>
    </div>

    <article v-for="place in saved" :key="place.id" class="saved-card">
      <h3>{{ place.name }}</h3>
      <p class="saved-meta">{{ place.category }} / {{ place.address?.split(",")[0] }}</p>
      <p class="saved-meta muted">收藏於 {{ place.created_at ? new Date(place.created_at).toLocaleDateString() : "最近" }}</p>
      <label class="note-field">
        <span>備註</span>
        <textarea
          rows="2"
          placeholder="為什麼想收藏這個地點？"
          :value="place.note || ''"
          @input="emit('update-note', place.id, $event.target.value)"
        ></textarea>
      </label>
      <div class="saved-actions">
        <button class="btn-ghost" type="button" @click="emit('navigate', `/place/${place.id}`)">查看</button>
        <button class="btn-primary" type="button" @click="emit('toast', `${place.name} 已加入今日測試計畫`)">加入計畫</button>
        <button class="btn-ghost" type="button" @click="emit('remove', place.id)">移除</button>
      </div>
    </article>
  </div>
</template>
