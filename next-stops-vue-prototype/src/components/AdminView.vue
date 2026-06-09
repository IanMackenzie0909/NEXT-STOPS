<script setup>
import { computed, onMounted, ref } from "vue";
import {
  clearStoredAdminToken,
  deleteAdminUser,
  getAdminFeedback,
  getAdminPlaces,
  getAdminRecommendations,
  getAdminSummary,
  getAdminUsers,
  getStoredAdminToken,
  rebuildAdminPlaces,
  verifyAdminToken,
} from "../api/nextStopsApi";

const emit = defineEmits(["navigate", "toast"]);

const token = ref("");
const loading = ref(false);
const adminReady = ref(false);
const activeTab = ref("dashboard");
const summary = ref(null);
const users = ref([]);
const recommendations = ref([]);
const feedback = ref([]);
const places = ref(null);

const tabs = [
  { id: "dashboard", label: "Dashboard" },
  { id: "users", label: "Users" },
  { id: "recommendations", label: "Recommendations" },
  { id: "feedback", label: "Feedback" },
  { id: "places", label: "Places" },
];

const counts = computed(() => summary.value?.counts || {});

async function loadDashboard() {
  summary.value = await getAdminSummary();
}

async function loadTab(tab = activeTab.value) {
  loading.value = true;
  try {
    if (tab === "dashboard") await loadDashboard();
    if (tab === "users") users.value = (await getAdminUsers()).users || [];
    if (tab === "recommendations") recommendations.value = (await getAdminRecommendations()).requests || [];
    if (tab === "feedback") feedback.value = (await getAdminFeedback()).feedback || [];
    if (tab === "places") places.value = await getAdminPlaces();
  } catch (error) {
    emit("toast", error.message);
  } finally {
    loading.value = false;
  }
}

async function loginAdmin() {
  if (!token.value.trim()) {
    emit("toast", "請輸入 Admin token");
    return;
  }
  loading.value = true;
  try {
    summary.value = await verifyAdminToken(token.value);
    adminReady.value = true;
    activeTab.value = "dashboard";
  } catch (error) {
    clearStoredAdminToken();
    emit("toast", error.message);
  } finally {
    loading.value = false;
  }
}

function logoutAdmin() {
  clearStoredAdminToken();
  token.value = "";
  adminReady.value = false;
}

async function switchTab(tab) {
  activeTab.value = tab;
  await loadTab(tab);
}

async function removeUser(user) {
  const ok = window.confirm(`刪除 ${user.name || user.account || user.id} 的所有資料？`);
  if (!ok) return;
  try {
    await deleteAdminUser(user.id);
    users.value = users.value.filter((item) => item.id !== user.id);
    emit("toast", "使用者已刪除");
    loadDashboard();
  } catch (error) {
    emit("toast", error.message);
  }
}

async function rebuildPlaces() {
  loading.value = true;
  try {
    const report = await rebuildAdminPlaces();
    emit("toast", `景點 cache 已重建：${report.final_count || 0} 筆`);
    places.value = await getAdminPlaces();
  } catch (error) {
    emit("toast", error.message);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  token.value = getStoredAdminToken();
  if (!token.value) return;
  try {
    summary.value = await getAdminSummary();
    adminReady.value = true;
  } catch {
    clearStoredAdminToken();
    token.value = "";
  }
});
</script>

<template>
  <main class="screen admin-screen">
    <header class="screen-header">
      <button class="back-button" type="button" @click="emit('navigate', '/')">‹</button>
      <div>
        <p class="muted">Internal ops</p>
        <h1>Admin</h1>
      </div>
    </header>

    <section v-if="!adminReady" class="admin-login-card">
      <h2>Admin token</h2>
      <p>輸入後台 token 才能查看營運資料。</p>
      <form class="admin-login-form" @submit.prevent="loginAdmin">
        <input v-model="token" type="password" autocomplete="current-password" placeholder="ADMIN_TOKEN" />
        <button class="primary-action" type="submit" :disabled="loading">{{ loading ? "Checking..." : "Enter admin" }}</button>
      </form>
    </section>

    <template v-else>
      <nav class="admin-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          :class="{ active: activeTab === tab.id }"
          type="button"
          @click="switchTab(tab.id)"
        >
          {{ tab.label }}
        </button>
        <button type="button" @click="logoutAdmin">Logout</button>
      </nav>

      <section v-if="activeTab === 'dashboard'" class="admin-grid">
        <article v-for="(value, key) in counts" :key="key" class="admin-stat">
          <span>{{ key }}</span>
          <strong>{{ value }}</strong>
        </article>
        <article class="admin-panel wide">
          <strong>System</strong>
          <p>DB：{{ summary?.database?.backend }}</p>
          <p>Places：{{ summary?.places?.count || 0 }} / {{ summary?.places?.cache }}</p>
        </article>
      </section>

      <section v-if="activeTab === 'users'" class="admin-panel">
        <div class="admin-panel-head">
          <strong>Users</strong>
          <button class="ghost-action compact" type="button" @click="loadTab()">Refresh</button>
        </div>
        <div class="admin-table">
          <div v-for="user in users" :key="user.id" class="admin-row">
            <div>
              <b>{{ user.name }}</b>
              <span>{{ user.provider }} / {{ user.email || user.account || user.id }}</span>
            </div>
            <small>{{ user.created_at }}</small>
            <button class="ghost-action compact danger" type="button" @click="removeUser(user)">Delete</button>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'recommendations'" class="admin-panel">
        <div class="admin-panel-head">
          <strong>Recommendation requests</strong>
          <button class="ghost-action compact" type="button" @click="loadTab()">Refresh</button>
        </div>
        <div class="admin-table">
          <div v-for="request in recommendations" :key="request.id" class="admin-row">
            <div>
              <b>{{ request.mood || "unknown" }} / {{ request.location || "unknown" }}</b>
              <span>{{ request.id }}</span>
            </div>
            <small>{{ request.result_count }} results / {{ request.created_at }}</small>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'feedback'" class="admin-panel">
        <div class="admin-panel-head">
          <strong>Feedback</strong>
          <button class="ghost-action compact" type="button" @click="loadTab()">Refresh</button>
        </div>
        <div class="admin-table">
          <div v-for="item in feedback" :key="`${item.created_at}-${item.place_id}`" class="admin-row">
            <div>
              <b>{{ item.feedback_type }}</b>
              <span>{{ item.place_id }} / {{ item.session_id }}</span>
            </div>
            <small>{{ item.created_at }}</small>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'places'" class="admin-panel">
        <div class="admin-panel-head">
          <strong>Places ops</strong>
          <button class="ghost-action compact" type="button" :disabled="loading" @click="rebuildPlaces">
            {{ loading ? "Building..." : "Rebuild cache" }}
          </button>
        </div>
        <p>Cache：{{ places?.cache }}</p>
        <p>Count：{{ places?.count || 0 }}</p>
        <div class="admin-category-list">
          <span v-for="item in places?.top_categories || []" :key="item.category">
            {{ item.category }} {{ item.count }}
          </span>
        </div>
      </section>
    </template>
  </main>
</template>
