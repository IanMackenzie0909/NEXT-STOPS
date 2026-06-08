<script setup>
import { computed, reactive, ref } from "vue";

const props = defineProps({
  user: { type: Object, default: null },
  departureLocations: { type: Array, default: () => [] },
  recommendationHistory: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits([
  "login",
  "register",
  "logout",
  "navigate",
  "save-departure-location",
  "delete-departure-location",
  "reuse-recommendation",
]);

const authMode = ref("login");
const loginForm = reactive({ email: "", password: "" });
const registerForm = reactive({ email: "", password: "", displayName: "" });
const locationForm = reactive({
  id: "",
  label: "",
  address: "",
  mapUrl: "",
  lat: "",
  lon: "",
  is_default: false,
});

const signedIn = computed(() => Boolean(props.user));
const authTitle = computed(() => (authMode.value === "register" ? "Create account" : "Sign in"));
const authSubtitle = computed(() => (
  authMode.value === "register"
    ? "Save your stops and trip plans under one account."
    : "Continue to your saved stops and trip plans."
));

function resetLocationForm() {
  Object.assign(locationForm, { id: "", label: "", address: "", mapUrl: "", lat: "", lon: "", is_default: false });
}

function editLocation(location) {
  Object.assign(locationForm, {
    id: location.id,
    label: location.label || "",
    address: location.address || "",
    mapUrl: location.lat !== null && location.lat !== undefined && location.lon !== null && location.lon !== undefined
      ? `https://www.google.com/maps?q=${location.lat},${location.lon}`
      : "",
    lat: location.lat ?? "",
    lon: location.lon ?? "",
    is_default: Boolean(location.is_default),
  });
}

function parseGoogleMapsCoordinates(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const decoded = decodeURIComponent(text);
  const patterns = [
    /@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
    /[?&](?:q|query|ll)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
    /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/,
    /(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
  ];
  for (const pattern of patterns) {
    const match = decoded.match(pattern);
    if (!match) continue;
    const lat = Number(match[1]);
    const lon = Number(match[2]);
    if (Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon };
  }
  return null;
}

function submitLocation() {
  const parsed = parseGoogleMapsCoordinates(locationForm.mapUrl);
  emit("save-departure-location", {
    id: locationForm.id || undefined,
    label: locationForm.label,
    address: locationForm.address,
    lat: parsed ? parsed.lat : (locationForm.lat === "" ? null : Number(locationForm.lat)),
    lon: parsed ? parsed.lon : (locationForm.lon === "" ? null : Number(locationForm.lon)),
    is_default: locationForm.is_default,
  });
  resetLocationForm();
}

function formatDate(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function criteriaSummary(criteria) {
  if (!criteria) return "No saved criteria";
  const parts = [
    criteria.mood,
    criteria.budget,
    criteria.weatherPreference,
    criteria.time ? `${criteria.time} min` : "",
    criteria.distance ? `${criteria.distance} min travel` : "",
  ].filter(Boolean);
  return parts.join(" / ") || "Saved criteria";
}
</script>

<template>
  <main class="screen account-screen">
    <header class="screen-header account-header">
      <button class="back-button account-back-button" type="button" aria-label="Back to home" @click="emit('navigate', '/')">
        <span aria-hidden="true">&lsaquo;</span>
      </button>
      <div class="account-title-block">
        <p class="muted">{{ signedIn ? "Signed in" : "Account" }}</p>
        <h1>{{ signedIn ? user.display_name || user.email : authTitle }}</h1>
        <small v-if="!signedIn">{{ authSubtitle }}</small>
      </div>
    </header>

    <section v-if="!signedIn" class="account-panel">
      <div class="account-mode-switch" role="tablist" aria-label="Account mode">
        <button type="button" role="tab" :aria-selected="authMode === 'login'" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">
          Login
        </button>
        <button type="button" role="tab" :aria-selected="authMode === 'register'" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">
          Register
        </button>
      </div>

      <form v-if="authMode === 'login'" class="account-auth-form" @submit.prevent="emit('login', { ...loginForm })">
        <div class="auth-form-heading">
          <h2>Welcome back</h2>
          <p>Use your email and password to continue.</p>
        </div>
        <label>Email <input v-model="loginForm.email" type="email" autocomplete="email" required /></label>
        <label>Password <input v-model="loginForm.password" type="password" autocomplete="current-password" required /></label>
        <button class="primary-action" type="submit" :disabled="loading">Login</button>
        <p class="account-switch">
          No account yet?
          <button type="button" @click="authMode = 'register'">Register</button>
        </p>
      </form>

      <form v-else class="account-auth-form" @submit.prevent="emit('register', { ...registerForm })">
        <div class="auth-form-heading">
          <h2>Start saving stops</h2>
          <p>Create an account to sync saved stops and planned trips.</p>
        </div>
        <label>Name <input v-model="registerForm.displayName" type="text" autocomplete="name" /></label>
        <label>Email <input v-model="registerForm.email" type="email" autocomplete="email" required /></label>
        <label>Password <input v-model="registerForm.password" type="password" autocomplete="new-password" minlength="8" required /></label>
        <button class="primary-action" type="submit" :disabled="loading">Create account</button>
        <p class="account-switch">
          Already have an account?
          <button type="button" @click="authMode = 'login'">Login</button>
        </p>
      </form>
    </section>

    <template v-else>
      <section class="account-panel">
        <div class="account-headline">
          <div>
            <h2>Account details</h2>
            <p>{{ user.email }}</p>
          </div>
          <button class="ghost-action danger" type="button" :disabled="loading" @click="emit('logout')">Logout</button>
        </div>
        <div class="account-detail-grid">
          <span><strong>Display name</strong><small>{{ user.display_name || "Not set" }}</small></span>
          <span><strong>Last login</strong><small>{{ formatDate(user.last_login_at) }}</small></span>
          <span><strong>Created</strong><small>{{ formatDate(user.created_at) }}</small></span>
          <span><strong>Updated</strong><small>{{ formatDate(user.updated_at) }}</small></span>
        </div>
      </section>

      <section class="account-panel">
        <div class="account-headline">
          <div>
            <h2>Departure locations</h2>
            <p>Name the places you often start from.</p>
          </div>
        </div>
        <form class="departure-form" @submit.prevent="submitLocation">
          <label>Name <input v-model="locationForm.label" type="text" placeholder="Home, Office, Taipei Main" required /></label>
          <label>Address <input v-model="locationForm.address" type="text" placeholder="Optional address or note" /></label>
          <label>Google Maps URL <input v-model="locationForm.mapUrl" type="url" placeholder="Paste a Google Maps link with coordinates" /></label>
          <a class="ghost-action maps-picker-link" href="https://www.google.com/maps" target="_blank" rel="noreferrer">Open Google Maps</a>
          <label class="account-toggle">
            <input v-model="locationForm.is_default" type="checkbox" />
            <span>Use as default departure</span>
          </label>
          <div class="card-footer">
            <button class="primary-action" type="submit" :disabled="loading">{{ locationForm.id ? "Update location" : "Add location" }}</button>
            <button v-if="locationForm.id" class="ghost-action" type="button" @click="resetLocationForm">Cancel edit</button>
          </div>
        </form>

        <div v-if="departureLocations.length" class="departure-list">
          <article v-for="location in departureLocations" :key="location.id" class="departure-item">
            <div>
              <h3>{{ location.label }}</h3>
              <p>{{ location.address || "No address" }}</p>
              <small>
                {{ location.lat ?? "No lat" }}, {{ location.lon ?? "No lon" }}
                <strong v-if="location.is_default">Default</strong>
              </small>
            </div>
            <div class="departure-actions">
              <button class="ghost-action" type="button" @click="editLocation(location)">Edit</button>
              <button class="ghost-action danger" type="button" :disabled="loading" @click="emit('delete-departure-location', location.id)">Delete</button>
            </div>
          </article>
        </div>
        <div v-else class="account-summary">
          <strong>No departure locations yet.</strong>
          <span>Add a named start point so trip planning can reuse it later.</span>
        </div>
      </section>

      <section class="account-panel">
        <div class="account-headline">
          <div>
            <h2>Recommendation history</h2>
            <p>Review recent searches and reuse previous settings.</p>
          </div>
        </div>

        <div v-if="recommendationHistory.length" class="history-list">
          <article v-for="item in recommendationHistory" :key="item.id" class="history-item">
            <div class="history-main">
              <h3>{{ formatDate(item.created_at) }}</h3>
              <p>{{ criteriaSummary(item.criteria) }}</p>
              <small>{{ item.count }} results</small>
            </div>
            <div v-if="item.results?.length" class="history-results">
              <span v-for="place in item.results.slice(0, 3)" :key="place.id">
                {{ place.name }}
              </span>
            </div>
            <div class="card-footer">
              <button class="ghost-action" type="button" @click="emit('reuse-recommendation', item.criteria)">Use settings</button>
              <button class="ghost-action" type="button" @click="emit('navigate', `/results`)">Results</button>
            </div>
          </article>
        </div>
        <div v-else class="account-summary">
          <strong>No recommendation history yet.</strong>
          <span>Generate recommendations while signed in to save them here.</span>
        </div>
      </section>
    </template>
  </main>
</template>
