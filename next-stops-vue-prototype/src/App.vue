<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import AdminView from "./components/AdminView.vue";
import AuthView from "./components/AuthView.vue";
import BottomNav from "./components/BottomNav.vue";
import DetailView from "./components/DetailView.vue";
import HomeView from "./components/HomeView.vue";
import ProfileView from "./components/ProfileView.vue";
import ResultsView from "./components/ResultsView.vue";
import SavedView from "./components/SavedView.vue";
import Toast from "./components/Toast.vue";
import IconGlyph from "./components/IconGlyph.vue";
import {
  clearStoredAuth,
  deleteAccount,
  deleteSavedPlace,
  getCurrentUser,
  getRecommendations,
  getSavedPlaces,
  getStoredAuth,
  logoutOnPageClose,
  logoutAccount,
  savePlace,
  submitRecommendationFeedback,
  updateFavoriteStarts,
  updateSavedPlace,
  updateUserProfile,
  updateUserPreferences,
} from "./api/nextStopsApi";
import { LOCATION_FALLBACK_LABEL } from "./constants";
import appIconImage from "./assets/APP_ICON.png";
import bgmTimeToTime from "../BGM/ES_Time to Time - Helmut Schenker.mp3";
import bgmSoftWeight from "../BGM/ES_Soft Weight of Slow Desire - Jay Taylor.mp3";

const AMBIENT_VOLUME = 0.34;
const AMBIENT_FADE_MS = 1400;
const ambientTracks = [bgmTimeToTime, bgmSoftWeight];

const criteria = reactive({
  mood: "relaxing_walk",
  time: 120,
  distance: 30,
  location: "taipei_main",
  locationLabel: LOCATION_FALLBACK_LABEL,
  locationSource: "fallback",
  lat: null,
  lon: null,
  weatherPreference: "any",
  budget: "medium",
  transportModes: [],
  weightAdjustments: {},
});

const route = ref(window.location.hash.replace(/^#/, "") || "/");
const results = ref([]);
const saved = ref([]);
const loading = ref(false);
const locating = ref(false);
const recommendationError = ref("");
const latestRequestId = ref("");
const feedbackByPlace = ref({});
const toastMessage = ref("");
const ambientEnabled = ref(false);
const booting = ref(true);
const authUser = ref(null);
let toastTimer;
let ambientAudio;
let ambientTrackIndex = 0;
let ambientFadeFrame;
let ambientFadeStartedAt = 0;
let ambientFadeFrom = 0;
let ambientFadeTo = 0;
let ambientGestureArmed = false;
let ambientGestureStartHandler;

watch(booting, (isBooting) => {
  document.body.classList.toggle("startup-active", isBooting);
  if (!isBooting) {
    startAmbientIfPossible(true).then((started) => {
      if (!started) armAmbientGestureStart();
    });
  }
}, { immediate: true });

const routeName = computed(() => {
  if (route.value.startsWith("/admin")) return "admin";
  if (!authUser.value) return "auth";
  if (route.value.startsWith("/place/")) return "detail";
  if (route.value === "/results") return "results";
  if (route.value === "/saved") return "saved";
  if (route.value === "/profile") return "profile";
  return "home";
});
const activePlaceId = computed(() => route.value.startsWith("/place/") ? decodeURIComponent(route.value.replace("/place/", "")) : "");
const savedIds = computed(() => saved.value.map((item) => item.id));

function navigate(path) {
  const target = path || "/";
  if (!authUser.value && target !== "/" && !target.startsWith("/admin")) return;
  if (window.location.hash.replace(/^#/, "") === target) route.value = target;
  else window.location.hash = target;
}

function handleNavigate(path) {
  if (path === "/results" && !results.value.length && !loading.value) {
    navigate("/");
    showToast("請先選擇情境，再按 Find my next stop");
    return;
  }
  navigate(path);
}

function updateCriteria(updates) {
  Object.assign(criteria, updates);
}

function useFavoriteStart(start) {
  if (start?.lat === undefined || start?.lon === undefined) return;
  updateCriteria({
    location: `favorite:${start.id}`,
    locationLabel: start.label,
    locationSource: "favorite",
    lat: Number(start.lat),
    lon: Number(start.lon),
  });
}

function applyUserPreferences(user) {
  criteria.weightAdjustments = { ...(user?.preferences?.weightAdjustments || {}) };
}

async function setAuthenticated(auth) {
  authUser.value = auth?.user || null;
  applyUserPreferences(authUser.value);
  route.value = "/";
  window.location.hash = "/";
  await syncSaved();
}

function locateUser() {
  if (!("geolocation" in navigator)) {
    showToast("瀏覽器不支援定位，先使用台北車站作為起點");
    updateCriteria({
      location: "taipei_main",
      locationLabel: LOCATION_FALLBACK_LABEL,
      locationSource: "fallback",
      lat: null,
      lon: null,
    });
    return Promise.resolve(false);
  }

  locating.value = true;
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = Number(position.coords.latitude.toFixed(6));
        const lon = Number(position.coords.longitude.toFixed(6));
        updateCriteria({
          location: "current",
          locationLabel: "你的位置",
          locationSource: "gps",
          lat,
          lon,
        });
        locating.value = false;
        showToast("已更新目前定位");
        resolve(true);
      },
      (error) => {
        locating.value = false;
        showToast(error.code === 1 ? "定位權限未開啟，先使用台北車站作為起點" : "定位失敗，先使用台北車站作為起點");
        updateCriteria({
          location: "taipei_main",
          locationLabel: LOCATION_FALLBACK_LABEL,
          locationSource: "fallback",
          lat: null,
          lon: null,
        });
        resolve(false);
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 120000 },
    );
  });
}

async function findStops() {
  if (loading.value) return;
  if (!criteria.mood) return;
  loading.value = true;
  recommendationError.value = "";
  results.value = [];
  navigate("/results");
  try {
    if (criteria.locationSource === "fallback") await locateUser();
    const data = await getRecommendations({ ...criteria });
    latestRequestId.value = data.request_id || "";
    results.value = data.results || [];
    if (!results.value.length) {
      recommendationError.value = data.request_id
        ? `後端已完成推薦請求 ${data.request_id}，但沒有回傳任何地點。請檢查景點資料 cache 或推薦篩選條件。`
        : "後端已回應，但沒有回傳任何推薦地點。請檢查景點資料 cache 或推薦篩選條件。";
    }
  } catch (error) {
    recommendationError.value = error.message || "推薦資料無法取得";
    console.error("NEXT STOPS recommendation failed:", error);
    showToast(`推薦資料無法取得：${recommendationError.value}`);
  } finally {
    loading.value = false;
  }
}

async function syncSaved() {
  saved.value = await getSavedPlaces();
}

async function toggleSave(place) {
  if (!place?.id) return;
  if (savedIds.value.includes(place.id)) {
    saved.value = saved.value.filter((item) => item.id !== place.id);
    await deleteSavedPlace(place.id);
    showToast("已從今天清單移除");
    return;
  }
  const item = {
    ...place,
    id: place.id,
    name: place.name,
    category: place.category,
    address: place.address,
    lat: place.lat,
    lng: place.lng,
    lon: place.lon ?? place.lng,
    score: place.score,
    note: place.note || "",
    created_at: new Date().toISOString(),
  };
  const savedItem = await savePlace(item);
  saved.value = [savedItem, ...saved.value.filter((entry) => entry.id !== savedItem.id)];
  showToast("已加入今天清單");
}

async function removeSaved(id) {
  saved.value = saved.value.filter((item) => item.id !== id);
  await deleteSavedPlace(id);
}

async function updateNote(id, note) {
  saved.value = saved.value.map((item) => item.id === id ? { ...item, note } : item);
  await updateSavedPlace(id, { note });
}

async function submitFeedback(placeId, feedbackType) {
  feedbackByPlace.value = { ...feedbackByPlace.value, [placeId]: feedbackType };
  try {
    await submitRecommendationFeedback(placeId, feedbackType, latestRequestId.value);
    showToast("已記錄你的偏好");
  } catch (error) {
    showToast(`偏好暫時無法送出：${error.message}`);
  }
}

async function savePreferences(preferences) {
  try {
    const user = await updateUserPreferences(preferences);
    authUser.value = user;
    applyUserPreferences(user);
    showToast("偏好已更新");
  } catch (error) {
    showToast(`偏好無法儲存：${error.message}`);
  }
}

async function saveProfile(profile) {
  try {
    const user = await updateUserProfile(profile);
    authUser.value = user;
    showToast("個人資料已更新");
  } catch (error) {
    showToast(`個人資料無法儲存：${error.message}`);
  }
}

async function saveFavoriteStarts(favoriteStarts) {
  try {
    const user = await updateFavoriteStarts(favoriteStarts);
    authUser.value = user;
    showToast("常用起始點已更新");
  } catch (error) {
    showToast(`常用起始點無法儲存：${error.message}`);
  }
}

async function logout() {
  await logoutAccount();
  authUser.value = null;
  saved.value = [];
  results.value = [];
  navigate("/");
}

async function removeAccount() {
  try {
    if (authUser.value?.provider === "guest") {
      clearStoredAuth();
    } else {
      await deleteAccount();
    }
    authUser.value = null;
    saved.value = [];
    results.value = [];
    showToast("帳號資料已移除");
    navigate("/");
  } catch (error) {
    showToast(`帳號刪除失敗：${error.message}`);
  }
}

function fallbackPlace(id) {
  return results.value.find((place) => place.id === id) || saved.value.find((place) => place.id === id) || null;
}

function showToast(message) {
  toastMessage.value = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastMessage.value = "";
  }, 2200);
}

async function toggleAmbient() {
  if (ambientEnabled.value) {
    stopAmbient();
    return;
  }
  const started = await startAmbientIfPossible(false);
  if (!started) armAmbientGestureStart();
}

function ensureAmbientAudio() {
  if (ambientAudio) return ambientAudio;
  ambientAudio = new Audio(ambientTracks[ambientTrackIndex]);
  ambientAudio.preload = "auto";
  ambientAudio.loop = false;
  ambientAudio.volume = 0;
  ambientAudio.autoplay = true;
  ambientAudio.addEventListener("ended", playNextAmbientTrack);
  return ambientAudio;
}

async function startAmbient() {
  const audio = ensureAmbientAudio();
  if (!ambientTracks.length) throw new Error("找不到背景音樂檔案");
  if (audio.paused) await audio.play();
  fadeAmbientVolume(AMBIENT_VOLUME, AMBIENT_FADE_MS);
}

async function startAmbientIfPossible(silent = true) {
  if (ambientEnabled.value) return true;
  try {
    await startAmbient();
    ambientEnabled.value = true;
    ambientGestureArmed = false;
    removeAmbientGestureStart();
    return true;
  } catch (error) {
    if (!silent) showToast(`音景無法啟用：${error.message}`);
    return false;
  }
}

function armAmbientGestureStart() {
  if (ambientGestureArmed || ambientEnabled.value) return;
  ambientGestureArmed = true;
  ambientGestureStartHandler = async () => {
    ambientGestureArmed = false;
    removeAmbientGestureStart();
    await startAmbientIfPossible(true);
  };
  document.addEventListener("pointerdown", ambientGestureStartHandler, { once: true, passive: true });
  document.addEventListener("touchstart", ambientGestureStartHandler, { once: true, passive: true });
  document.addEventListener("keydown", ambientGestureStartHandler, { once: true });
}

function removeAmbientGestureStart() {
  if (!ambientGestureStartHandler) return;
  document.removeEventListener("pointerdown", ambientGestureStartHandler);
  document.removeEventListener("touchstart", ambientGestureStartHandler);
  document.removeEventListener("keydown", ambientGestureStartHandler);
  ambientGestureStartHandler = null;
  ambientGestureArmed = false;
}

function playNextAmbientTrack() {
  if (!ambientEnabled.value || !ambientAudio) return;
  ambientTrackIndex = (ambientTrackIndex + 1) % ambientTracks.length;
  ambientAudio.src = ambientTracks[ambientTrackIndex];
  ambientAudio.currentTime = 0;
  ambientAudio.volume = AMBIENT_VOLUME;
  ambientAudio.play().catch((error) => {
    ambientEnabled.value = false;
    showToast(`背景音樂無法播放：${error.message}`);
  });
}

function fadeAmbientVolume(targetVolume, durationMs, onDone) {
  const audio = ensureAmbientAudio();
  cancelAnimationFrame(ambientFadeFrame);
  ambientFadeStartedAt = performance.now();
  ambientFadeFrom = audio.volume;
  ambientFadeTo = targetVolume;

  const tick = (now) => {
    const progress = Math.min((now - ambientFadeStartedAt) / durationMs, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    audio.volume = ambientFadeFrom + ((ambientFadeTo - ambientFadeFrom) * eased);
    if (progress < 1) {
      ambientFadeFrame = requestAnimationFrame(tick);
      return;
    }
    ambientFadeFrame = null;
    onDone?.();
  };
  ambientFadeFrame = requestAnimationFrame(tick);
}

function stopAmbient(options = {}) {
  ambientEnabled.value = false;
  if (!ambientAudio) return;
  cancelAnimationFrame(ambientFadeFrame);
  const pauseAudio = () => {
    ambientAudio.pause();
    ambientAudio.volume = 0;
  };
  if (options.immediate) pauseAudio();
  else fadeAmbientVolume(0, 900, pauseAudio);
}

onMounted(() => {
  window.addEventListener("hashchange", () => {
    route.value = window.location.hash.replace(/^#/, "") || "/";
  });
  ensureAmbientAudio();
  startAmbientIfPossible(true).then((started) => {
    if (!started) armAmbientGestureStart();
  });
  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("pagehide", handlePageHide);
  const storedAuth = getStoredAuth();
  if (storedAuth?.user) {
    authUser.value = storedAuth.user;
    applyUserPreferences(storedAuth.user);
    getCurrentUser()
      .then((data) => {
        if (data?.user) {
          authUser.value = data.user;
          applyUserPreferences(data.user);
        }
      })
      .catch(() => {
        clearStoredAuth();
        authUser.value = null;
      })
      .finally(() => {
        if (authUser.value) syncSaved();
      });
  }
  setTimeout(() => {
    if (authUser.value) navigate("/");
    booting.value = false;
  }, 1800);
});

onBeforeUnmount(() => {
  document.removeEventListener("visibilitychange", handleVisibilityChange);
  window.removeEventListener("pagehide", handlePageHide);
  removeAmbientGestureStart();
  stopAmbient({ immediate: true });
  document.body.classList.remove("startup-active");
});

function handlePageHide() {
  logoutOnPageClose();
}

function handleVisibilityChange() {
  if (document.visibilityState !== "visible" || booting.value || ambientEnabled.value) return;
  startAmbientIfPossible(true).then((started) => {
    if (!started) armAmbientGestureStart();
  });
}
</script>

<template>
  <div class="app-shell" :class="{ booting }">
    <div class="app-surface">
      <div class="journey-background" aria-hidden="true">
        <span class="journey-grid"></span>
        <span class="journey-route one"></span>
        <span class="journey-route two"></span>
        <span class="journey-node a"></span>
        <span class="journey-node b"></span>
        <span class="journey-node c"></span>
        <span class="journey-compass"></span>
        <span class="journey-ticket"></span>
      </div>
      <Transition name="screen-fade" mode="out-in">
        <AuthView
          v-if="!booting && routeName === 'auth'"
          key="auth"
          @authenticated="setAuthenticated"
          @toast="showToast"
        />
        <AdminView
          v-else-if="!booting && routeName === 'admin'"
          key="admin"
          @navigate="navigate"
          @toast="showToast"
        />
        <HomeView
          v-else-if="routeName === 'home'"
          key="home"
          :criteria="criteria"
          :favorite-starts="authUser?.preferences?.favoriteStarts || []"
          :user="authUser"
          :loading="loading"
          :locating="locating"
          :saved-count="saved.length"
          @update:criteria="updateCriteria"
          @locate="locateUser"
          @use-favorite-start="useFavoriteStart"
          @find="findStops"
          @navigate="handleNavigate"
        />
        <ResultsView
          v-else-if="routeName === 'results'"
          key="results"
          :criteria="criteria"
          :results="results"
          :saved-ids="savedIds"
          :feedback-by-place="feedbackByPlace"
          :loading="loading || locating"
          :error="recommendationError"
          @navigate="handleNavigate"
          @find="findStops"
          @view="(id) => navigate(`/place/${id}`)"
          @toggle-save="toggleSave"
          @feedback="submitFeedback"
        />
        <DetailView
          v-else-if="routeName === 'detail'"
          :key="`detail-${activePlaceId}`"
          :place-id="activePlaceId"
          :fallback-place="fallbackPlace(activePlaceId)"
          :criteria="criteria"
          :saved="savedIds.includes(activePlaceId)"
          @navigate="navigate"
          @toggle-save="toggleSave"
          @toast="showToast"
        />
        <SavedView
          v-else-if="routeName === 'saved'"
          key="saved"
          :saved="saved"
          @navigate="navigate"
          @remove="removeSaved"
          @update-note="updateNote"
        />
        <ProfileView
          v-else-if="routeName === 'profile'"
          key="profile"
          :user="authUser"
          :saved="saved"
          :criteria="criteria"
          @navigate="navigate"
          @save-profile="saveProfile"
          @save-starts="saveFavoriteStarts"
          @save-preferences="savePreferences"
          @logout="logout"
          @delete-account="removeAccount"
          @toast="showToast"
        />
      </Transition>
    </div>
    <button
      v-if="!booting"
      class="ambient-toggle"
      :class="{ active: ambientEnabled }"
      type="button"
      title="Ambient sound"
      @click="toggleAmbient"
    >
      <IconGlyph name="sound" />
      <span>{{ ambientEnabled ? "Sound on" : "Sound" }}</span>
    </button>
    <BottomNav v-if="!booting && authUser && routeName !== 'admin'" :route="route" :saved-count="saved.length" :user="authUser" @navigate="handleNavigate" />
    <Toast :message="toastMessage" />

    <Transition name="splash-fade">
      <section v-if="booting" class="startup-splash" aria-live="polite">
        <div class="startup-orbit" aria-hidden="true">
          <span class="startup-ring one"></span>
          <span class="startup-ring two"></span>
          <span class="startup-route"></span>
          <span class="startup-node a"></span>
          <span class="startup-node b"></span>
        </div>
        <img class="startup-icon" :src="appIconImage" alt="NEXT STOPS" />
        <div class="startup-copy">
          <strong :style="{ fontSize: '30px' }">NEXT STOPS</strong>
        </div>
      </section>
    </Transition>
  </div>
</template>
