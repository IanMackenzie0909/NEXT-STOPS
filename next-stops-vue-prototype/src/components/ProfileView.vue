<script setup>
import { computed, reactive, ref, watch } from "vue";
import { isWithinServiceArea, serviceAreaError } from "../utils/serviceArea";

const props = defineProps({
  user: { type: Object, required: true },
  saved: { type: Array, default: () => [] },
  criteria: { type: Object, default: null },
});
const emit = defineEmits(["navigate", "save-profile", "save-preferences", "save-starts", "logout", "delete-account", "toast"]);

const controls = [
  { key: "mood", label: "心情契合" },
  { key: "distance", label: "通勤距離" },
  { key: "weather", label: "天氣影響" },
  { key: "aqi", label: "空氣品質" },
  { key: "budget", label: "預算敏感度" },
  { key: "category", label: "類型偏好" },
  { key: "quality", label: "資料品質" },
  { key: "environment", label: "室內外偏好" },
];

const weights = reactive({});
const editingProfile = ref(false);
const addingStart = ref(false);
const startLabel = ref("");
const profileForm = reactive({ name: "", avatar_url: "" });

const initials = computed(() => String(props.user?.name || props.user?.account || "N").slice(0, 1).toUpperCase());
const providerLabel = computed(() => {
  if (props.user?.provider === "google") return "Google 帳戶";
  if (props.user?.provider === "guest") return "訪客模式";
  return "平台帳戶";
});
const favoriteStarts = computed(() => props.user?.preferences?.favoriteStarts || []);
const canAddStart = computed(() => props.user?.provider !== "guest" && favoriteStarts.value.length < 2);

function syncWeights() {
  const current = props.user?.preferences?.weightAdjustments || {};
  for (const item of controls) weights[item.key] = Number(current[item.key] ?? 1);
}

function syncProfile() {
  profileForm.name = props.user?.name || "";
  profileForm.avatar_url = props.user?.avatar_url || "";
}

function saveProfile() {
  if (props.user?.provider === "guest") {
    emit("toast", "訪客模式不能編輯個人資料");
    return;
  }
  if (!profileForm.name.trim()) {
    emit("toast", "請輸入名稱");
    return;
  }
  emit("save-profile", { name: profileForm.name, avatar_url: profileForm.avatar_url });
  editingProfile.value = false;
}

function cancelProfileEdit() {
  syncProfile();
  editingProfile.value = false;
}

function removeAvatar() {
  profileForm.avatar_url = "";
}

function selectAvatar(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    emit("toast", "請選擇圖片檔");
    return;
  }
  if (file.size > 800000) {
    emit("toast", "頭像圖片請小於 800KB");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    profileForm.avatar_url = String(reader.result || "");
  };
  reader.onerror = () => emit("toast", "頭像讀取失敗");
  reader.readAsDataURL(file);
}

function savePreferences() {
  emit("save-preferences", { weightAdjustments: { ...weights } });
}

function saveStarts(starts) {
  emit("save-starts", starts.slice(0, 2));
}

function removeStart(id) {
  saveStarts(favoriteStarts.value.filter((item) => item.id !== id));
}

function addStartFromCoordinates(label, lat, lon) {
  const cleanLabel = String(label || "").trim().slice(0, 24);
  if (!cleanLabel) {
    emit("toast", "請先為常用起點命名");
    return;
  }
  if (!isWithinServiceArea(lat, lon)) {
    emit("toast", serviceAreaError("favorite"));
    return;
  }
  saveStarts([
    ...favoriteStarts.value,
    {
      id: globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `start-${Date.now()}`,
      label: cleanLabel,
      lat: Number(Number(lat).toFixed(6)),
      lon: Number(Number(lon).toFixed(6)),
    },
  ]);
  startLabel.value = "";
}

function hasUsableCriteriaStart() {
  if (props.criteria?.locationSource === "fallback") return false;
  return props.criteria?.lat !== null
    && props.criteria?.lat !== undefined
    && props.criteria?.lon !== null
    && props.criteria?.lon !== undefined;
}

function addCurrentStart() {
  if (!canAddStart.value) return;
  const label = startLabel.value.trim();
  if (!label) {
    emit("toast", "請先為常用起點命名");
    return;
  }
  if (hasUsableCriteriaStart()) {
    addStartFromCoordinates(label, props.criteria.lat, props.criteria.lon);
    return;
  }
  if (!("geolocation" in navigator)) {
    emit("toast", "瀏覽器不支援定位，無法新增目前起點");
    return;
  }
  addingStart.value = true;
  navigator.geolocation.getCurrentPosition(
    (position) => {
      addingStart.value = false;
      addStartFromCoordinates(label, position.coords.latitude, position.coords.longitude);
    },
    () => {
      addingStart.value = false;
      emit("toast", "定位失敗，請允許定位後再新增常用起點");
    },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 120000 },
  );
}

function deleteAccount() {
  if (props.user?.provider === "guest") {
    emit("logout");
    return;
  }
  const first = window.confirm("刪除帳號會移除所有收藏、偏好、回饋與推薦紀錄。確定要繼續？");
  if (!first) return;
  const second = window.confirm("這個操作無法復原。再次確認刪除帳號？");
  if (second) emit("delete-account");
}

watch(() => props.user, () => {
  syncWeights();
  syncProfile();
}, { immediate: true, deep: true });
</script>

<template>
  <main class="screen profile-screen">
    <header class="screen-header">
      <div>
        <p class="muted">Account</p>
        <h1>Profile</h1>
      </div>
    </header>

    <section class="profile-card">
      <div class="profile-avatar-wrap">
        <img v-if="profileForm.avatar_url" class="profile-avatar" :src="profileForm.avatar_url" alt="" />
        <div v-else class="profile-avatar fallback">{{ initials }}</div>
      </div>
      <form class="profile-identity" @submit.prevent="saveProfile">
        <template v-if="editingProfile && user.provider !== 'guest'">
          <label class="profile-name-field">
            <span>名稱</span>
            <input v-model="profileForm.name" maxlength="40" autocomplete="name" />
          </label>
          <div class="profile-actions">
            <label class="ghost-action avatar-upload">
              更換頭像
              <input type="file" accept="image/*" @change="selectAvatar" />
            </label>
            <button class="ghost-action" type="button" @click="removeAvatar">移除頭像</button>
          </div>
          <div class="profile-actions">
            <button class="primary-action compact" type="submit">Save profile</button>
            <button class="ghost-action" type="button" @click="cancelProfileEdit">Cancel</button>
          </div>
        </template>
        <template v-else>
          <h2>{{ user.name }}</h2>
          <p>{{ providerLabel }}<span v-if="user.email"> / {{ user.email }}</span></p>
          <button
            v-if="user.provider !== 'guest'"
            class="ghost-action edit-profile-button"
            type="button"
            @click="editingProfile = true"
          >
            編輯個人資料
          </button>
        </template>
      </form>
    </section>

    <section class="profile-grid">
      <article class="profile-section">
        <strong>個人儲存的地點</strong>
        <p>{{ saved.length }} 個地點已儲存到你的清單。</p>
        <button class="ghost-action" type="button" @click="emit('navigate', '/saved')">查看清單</button>
      </article>

      <article v-if="user.provider !== 'guest'" class="profile-section favorite-start-panel">
        <strong>常用起始點</strong>
        <p>最多可儲存 2 個常用出發定位，首頁可直接切換。</p>
        <div v-if="favoriteStarts.length" class="saved-start-list">
          <div v-for="start in favoriteStarts" :key="start.id" class="saved-start-item">
            <div>
              <b>{{ start.label }}</b>
              <span>({{ Number(start.lat).toFixed(4) }}, {{ Number(start.lon).toFixed(4) }})</span>
            </div>
            <button class="ghost-action compact danger" type="button" @click="removeStart(start.id)">移除</button>
          </div>
        </div>
        <div v-if="canAddStart" class="favorite-start-form">
          <input v-model="startLabel" maxlength="24" placeholder="例如：台灣大學" />
          <button class="ghost-action" type="button" :disabled="addingStart" @click="addCurrentStart">
            {{ addingStart ? "定位中..." : "新增目前起點" }}
          </button>
        </div>
      </article>

      <article class="profile-section preference-panel">
        <strong>個人偏好控制台</strong>
        <p>這些權重會送到後端推薦演算法，影響下一次排序。</p>
        <label v-for="item in controls" :key="item.key" class="preference-slider">
          <span>{{ item.label }} <b>{{ weights[item.key].toFixed(2) }}</b></span>
          <input v-model.number="weights[item.key]" type="range" min="0.5" max="1.6" step="0.05" />
        </label>
        <button class="primary-action" type="button" @click="savePreferences">Save preferences</button>
      </article>

      <article class="profile-section danger-zone">
        <strong>{{ user.provider === "guest" ? "訪客模式" : "帳號管理" }}</strong>
        <template v-if="user.provider === 'guest'">
          <p>訪客資料只保存在這台裝置。登入後才會同步收藏與偏好。</p>
          <button class="ghost-action" type="button" @click="emit('logout')">登入或建立帳號</button>
        </template>
        <template v-else>
          <button class="ghost-action" type="button" @click="emit('logout')">登出</button>
          <button class="ghost-action danger" type="button" @click="deleteAccount">刪除帳號</button>
        </template>
      </article>
    </section>
  </main>
</template>
