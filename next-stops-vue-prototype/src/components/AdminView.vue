<script setup>
import { computed, onMounted, ref } from "vue";
import {
  clearStoredAdminToken,
  deleteAdminUser,
  getAdminOverview,
  getStoredAdminToken,
  rebuildAdminPlaces,
  verifyAdminToken,
} from "../api/nextStopsApi";

const emit = defineEmits(["navigate", "toast"]);

const token = ref("");
const loading = ref(false);
const adminReady = ref(false);
const activeTab = ref("overview");
const overview = ref(null);

const tabs = [
  { id: "overview", label: "總覽" },
  { id: "users", label: "使用者脈絡" },
  { id: "requests", label: "推薦脈絡" },
  { id: "places", label: "地點脈絡" },
  { id: "system", label: "系統資料" },
];

const counts = computed(() => overview.value?.counts || {});
const health = computed(() => overview.value?.health || {});
const users = computed(() => overview.value?.users || []);
const requests = computed(() => overview.value?.requests || []);
const feedback = computed(() => overview.value?.feedback || []);
const saved = computed(() => overview.value?.saved || []);
const places = computed(() => overview.value?.places || []);
const placeCache = computed(() => overview.value?.place_cache || {});
const providerBreakdown = computed(() => overview.value?.breakdowns?.providers || []);
const feedbackBreakdown = computed(() => overview.value?.breakdowns?.feedback_types || []);

const relationScore = computed(() => {
  const issues = Number(health.value.orphan_user_sessions || 0) + Number(health.value.orphan_feedback || 0);
  if (issues === 0) return "正常";
  if (issues < 3) return "需留意";
  return "需整理";
});

async function loadOverview() {
  loading.value = true;
  try {
    overview.value = await getAdminOverview();
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
    await verifyAdminToken(token.value);
    adminReady.value = true;
    activeTab.value = "overview";
    await loadOverview();
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
  overview.value = null;
}

async function removeUser(user) {
  const ok = window.confirm(`刪除 ${user.name || user.account || user.id} 的所有資料？`);
  if (!ok) return;
  try {
    await deleteAdminUser(user.id);
    emit("toast", "使用者已刪除");
    await loadOverview();
  } catch (error) {
    emit("toast", error.message);
  }
}

async function rebuildPlaces() {
  loading.value = true;
  try {
    const report = await rebuildAdminPlaces();
    emit("toast", `景點 cache 已重建：${report.final_count || 0} 筆`);
    await loadOverview();
  } catch (error) {
    emit("toast", error.message);
  } finally {
    loading.value = false;
  }
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 14) return text || "unknown";
  return `${text.slice(0, 8)}…${text.slice(-4)}`;
}

function userLabel(user, sessionId = "") {
  if (user?.name) return user.name;
  if (sessionId?.startsWith("user:")) return `User ${shortId(sessionId.replace("user:", ""))}`;
  return sessionId ? `Guest ${shortId(sessionId)}` : "Unknown session";
}

function transportLabel(modes) {
  if (!Array.isArray(modes) || !modes.length) return "最短時間";
  return modes.join(" / ");
}

function formatScore(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) return "--";
  return `${Math.round(value)}%`;
}

onMounted(async () => {
  token.value = getStoredAdminToken();
  if (!token.value) return;
  try {
    await verifyAdminToken(token.value);
    adminReady.value = true;
    await loadOverview();
  } catch {
    clearStoredAdminToken();
    token.value = "";
  }
});
</script>

<template>
  <main class="screen admin-screen">
    <header class="screen-header">
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
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
        <button class="ghost-action compact" type="button" :disabled="loading" @click="loadOverview">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </button>
        <button class="admin-logout-button" type="button" @click="logoutAdmin">Admin Log out</button>
      </nav>

      <section v-if="activeTab === 'overview'" class="admin-stack">
        <div class="admin-grid">
          <article class="admin-stat">
            <span>Users</span>
            <strong>{{ counts.users || 0 }}</strong>
          </article>
          <article class="admin-stat">
            <span>Requests</span>
            <strong>{{ counts.recommendation_requests || 0 }}</strong>
          </article>
          <article class="admin-stat">
            <span>Results</span>
            <strong>{{ counts.recommendation_results || 0 }}</strong>
          </article>
          <article class="admin-stat">
            <span>Saved</span>
            <strong>{{ counts.saved_places || 0 }}</strong>
          </article>
          <article class="admin-stat">
            <span>Feedback</span>
            <strong>{{ counts.recommendation_feedback || 0 }}</strong>
          </article>
        </div>

        <section class="admin-relationship-grid">
          <article class="admin-panel">
            <div class="admin-panel-head">
              <strong>資料關聯狀態</strong>
              <span class="admin-status-pill">{{ relationScore }}</span>
            </div>
            <div class="admin-metric-list">
              <span><b>{{ health.linked_user_sessions || 0 }}</b><small>已連到使用者的推薦 session</small></span>
              <span><b>{{ health.guest_sessions || 0 }}</b><small>訪客 session</small></span>
              <span><b>{{ health.orphan_user_sessions || 0 }}</b><small>找不到 user 的 session</small></span>
              <span><b>{{ health.orphan_feedback || 0 }}</b><small>找不到 request 的 feedback</small></span>
            </div>
          </article>

          <article class="admin-panel">
            <div class="admin-panel-head">
              <strong>帳號來源</strong>
            </div>
            <div class="admin-category-list">
              <span v-for="item in providerBreakdown" :key="item.label">{{ item.label }} {{ item.count }}</span>
            </div>
          </article>

          <article class="admin-panel">
            <div class="admin-panel-head">
              <strong>回饋類型</strong>
            </div>
            <div class="admin-category-list">
              <span v-for="item in feedbackBreakdown" :key="item.label">{{ item.label }} {{ item.count }}</span>
              <p v-if="!feedbackBreakdown.length">尚無回饋資料。</p>
            </div>
          </article>
        </section>
      </section>

      <section v-if="activeTab === 'users'" class="admin-panel">
        <div class="admin-panel-head">
          <strong>使用者與行為關聯</strong>
          <small>users → sessions → recommendations / saved / feedback</small>
        </div>
        <div class="admin-table">
          <div v-for="user in users" :key="user.id" class="admin-row admin-row-rich">
            <div>
              <b>{{ user.name }}</b>
              <span>{{ user.provider }} / {{ user.email || user.account || user.id }}</span>
              <small>{{ user.session_id }}</small>
            </div>
            <div class="admin-row-metrics">
              <span>{{ user.auth_sessions }} sessions</span>
              <span>{{ user.recommendations }} requests</span>
              <span>{{ user.saved_places }} saved</span>
              <span>{{ user.feedback }} feedback</span>
              <span>{{ user.favorite_starts_count }} starts</span>
            </div>
            <small>{{ user.last_recommendation_at || user.updated_at || user.created_at }}</small>
            <button class="ghost-action compact danger" type="button" @click="removeUser(user)">Delete</button>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'requests'" class="admin-panel">
        <div class="admin-panel-head">
          <strong>推薦請求與結果關聯</strong>
          <small>requests → results → feedback</small>
        </div>
        <div class="admin-table">
          <div v-for="request in requests" :key="request.id" class="admin-row admin-row-rich">
            <div>
              <b>{{ request.mood || "unknown" }} / {{ request.location || "unknown" }}</b>
              <span>{{ shortId(request.id) }} / {{ userLabel(request.user, request.session_id) }}</span>
              <small>{{ transportLabel(request.transport_modes) }} / {{ request.time || "--" }} min / {{ request.distance || "--" }} min commute</small>
            </div>
            <div class="admin-row-metrics">
              <span>{{ request.result_count }} results</span>
              <span>{{ request.feedback_count }} feedback</span>
              <span>AQI {{ Math.round(request.aqi || 0) }}</span>
              <span>Rain {{ Math.round((request.rain_probability || 0) * 100) }}%</span>
            </div>
            <div>
              <b>{{ request.top_result?.place_name || "No top result" }}</b>
              <span>{{ formatScore((request.top_result?.score || 0) * 100) }}</span>
            </div>
            <small>{{ request.created_at }}</small>
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'places'" class="admin-stack">
        <section class="admin-panel">
          <div class="admin-panel-head">
            <strong>地點被推薦 / 收藏 / 回饋關聯</strong>
            <button class="ghost-action compact" type="button" :disabled="loading" @click="rebuildPlaces">
              {{ loading ? "Building..." : "Rebuild cache" }}
            </button>
          </div>
          <div class="admin-table">
            <div v-for="place in places" :key="place.place_id" class="admin-row admin-row-rich">
              <div>
                <b>{{ place.name || place.place_id }}</b>
                <span>{{ place.place_id }}</span>
              </div>
              <div class="admin-row-metrics">
                <span>{{ place.recommended_count }} recommended</span>
                <span>{{ place.saved_count }} saved</span>
                <span>{{ place.feedback_count }} feedback</span>
                <span>{{ place.avg_score }} avg</span>
              </div>
            </div>
          </div>
        </section>

        <section class="admin-panel">
          <div class="admin-panel-head">
            <strong>最新收藏</strong>
          </div>
          <div class="admin-table">
            <div v-for="item in saved" :key="`${item.session_id}-${item.place_id}`" class="admin-row">
              <div>
                <b>{{ item.name }}</b>
                <span>{{ item.category || "unknown" }} / {{ userLabel(item.user, item.session_id) }}</span>
              </div>
              <small>{{ item.updated_at }}</small>
            </div>
          </div>
        </section>
      </section>

      <section v-if="activeTab === 'system'" class="admin-stack">
        <section class="admin-panel">
          <div class="admin-panel-head">
            <strong>資料庫</strong>
          </div>
          <p>Backend：{{ overview?.database?.backend }}</p>
          <p v-if="overview?.database?.path">Path：{{ overview.database.path }}</p>
          <div class="admin-category-list">
            <span v-for="(value, key) in counts" :key="key">{{ key }} {{ value }}</span>
          </div>
        </section>

        <section class="admin-panel">
          <div class="admin-panel-head">
            <strong>景點 cache</strong>
            <button class="ghost-action compact" type="button" :disabled="loading" @click="rebuildPlaces">
              {{ loading ? "Building..." : "Rebuild cache" }}
            </button>
          </div>
          <p>Cache：{{ placeCache.cache }}</p>
          <p>Count：{{ placeCache.count || 0 }}</p>
          <p>Status：{{ placeCache.cache_exists ? "exists" : "missing" }}</p>
          <div class="admin-category-list">
            <span v-for="item in placeCache.top_categories || []" :key="item.category">
              {{ item.category }} {{ item.count }}
            </span>
          </div>
        </section>

        <section class="admin-panel">
          <div class="admin-panel-head">
            <strong>最新回饋</strong>
          </div>
          <div class="admin-table">
            <div v-for="item in feedback" :key="`${item.created_at}-${item.place_id}`" class="admin-row">
              <div>
                <b>{{ item.feedback_type }}</b>
                <span>{{ item.place_id }} / {{ userLabel(item.user, item.session_id) }}</span>
                <small>{{ item.request_id || "no request" }}</small>
              </div>
              <small>{{ item.created_at }}</small>
            </div>
          </div>
        </section>
      </section>
    </template>
  </main>
</template>
