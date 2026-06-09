<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import appIconImage from "../assets/APP_ICON.png";
import { getAuthConfig, loginAccount, loginWithGoogleCredential, registerAccount, startGuestSession } from "../api/nextStopsApi";

const emit = defineEmits(["authenticated", "toast"]);

const mode = ref("login");
const loading = ref(false);
const googleSlot = ref(null);
const googleConfig = ref({ google_enabled: false, google_client_id: "" });
const loginForm = reactive({ account: "", password: "" });
const registerForm = reactive({ name: "", account: "", password: "", confirm_password: "" });

const title = computed(() => (mode.value === "register" ? "Create account" : "Welcome back"));
const subtitle = computed(() => (mode.value === "register" ? "建立你的 NEXT STOPS 帳戶" : "登入後同步收藏與偏好"));

function cleanRegisterPassword() {
  registerForm.password = registerForm.password.replace(/\s+$/, "");
  registerForm.confirm_password = registerForm.confirm_password.replace(/\s+$/, "");
}

function validateRegister() {
  cleanRegisterPassword();
  if (!registerForm.name.trim()) return "請輸入名稱";
  if (!registerForm.account.trim()) return "請輸入帳號";
  if (registerForm.account.trim() === registerForm.password) return "帳號與密碼不可相同";
  if (registerForm.password !== registerForm.confirm_password) return "兩次輸入的密碼不一致";
  if (/\s/.test(registerForm.password)) return "密碼開頭與中間不得包含空白";
  if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$_-])[A-Za-z\d@$_-]{8,16}$/.test(registerForm.password)) {
    return "密碼需 8-16 字元，含大小寫、數字與特殊符號（限定：@ $ _ -）";
  }
  return "";
}

async function submitLogin() {
  loading.value = true;
  try {
    const auth = await loginAccount({ account: loginForm.account, password: loginForm.password });
    emit("authenticated", auth);
  } catch (error) {
    emit("toast", error.message);
  } finally {
    loading.value = false;
  }
}

async function submitRegister() {
  const error = validateRegister();
  if (error) {
    emit("toast", error);
    return;
  }
  loading.value = true;
  try {
    await registerAccount({ ...registerForm });
    emit("toast", "註冊完成，請登入");
    mode.value = "login";
    loginForm.account = registerForm.account;
    loginForm.password = "";
  } catch (err) {
    emit("toast", err.message);
  } finally {
    loading.value = false;
  }
}

function continueAsGuest() {
  emit("authenticated", startGuestSession());
}

function loadGoogleScript() {
  return new Promise((resolve, reject) => {
    if (globalThis.google?.accounts?.id) {
      resolve();
      return;
    }
    const existing = document.querySelector("script[data-google-identity]");
    if (existing) {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", reject, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.googleIdentity = "true";
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function renderGoogleButton() {
  await nextTick();
  if (!googleSlot.value || !googleConfig.value.google_enabled) return;
  try {
    await loadGoogleScript();
    googleSlot.value.innerHTML = "";
    globalThis.google.accounts.id.initialize({
      client_id: googleConfig.value.google_client_id,
      callback: async (response) => {
        loading.value = true;
        try {
          const auth = await loginWithGoogleCredential(response.credential);
          emit("authenticated", auth);
        } catch (error) {
          emit("toast", error.message);
        } finally {
          loading.value = false;
        }
      },
    });
    globalThis.google.accounts.id.renderButton(googleSlot.value, {
      theme: "outline",
      size: "large",
      shape: "pill",
      text: mode.value === "register" ? "signup_with" : "signin_with",
      width: 320,
    });
  } catch {
    emit("toast", "Google 登入元件載入失敗");
  }
}

onMounted(async () => {
  try {
    googleConfig.value = await getAuthConfig();
  } catch {
    googleConfig.value = { google_enabled: false, google_client_id: "" };
  }
  renderGoogleButton();
});

watch(mode, renderGoogleButton);
</script>

<template>
  <main class="auth-screen">
    <section class="auth-panel">
      <div class="auth-brand">
        <img :src="appIconImage" alt="NEXT STOPS" />
        <strong>NEXT STOPS</strong>
        <span>{{ subtitle }}</span>
      </div>

      <Transition name="screen-fade" mode="out-in">
        <form v-if="mode === 'login'" key="login" class="auth-form" @submit.prevent="submitLogin">
          <h1>{{ title }}</h1>
          <label>
            <span>帳號</span>
            <input v-model.trim="loginForm.account" autocomplete="username" required />
          </label>
          <label>
            <span>密碼</span>
            <input v-model="loginForm.password" type="password" autocomplete="current-password" required />
          </label>
          <button class="primary-action" type="submit" :disabled="loading">{{ loading ? "Signing in..." : "Log in" }}</button>
          <button class="link-action" type="button" @click="mode = 'register'">註冊帳戶</button>
        </form>

        <form v-else key="register" class="auth-form" @submit.prevent="submitRegister">
          <h1>{{ title }}</h1>
          <label>
            <span>名稱</span>
            <input v-model.trim="registerForm.name" autocomplete="name" required />
          </label>
          <label>
            <span>帳號</span>
            <input v-model.trim="registerForm.account" autocomplete="username" required />
          </label>
          <label>
            <span>密碼</span>
            <input v-model="registerForm.password" type="password" autocomplete="new-password" required @blur="cleanRegisterPassword" />
          </label>
          <label>
            <span>再次輸入密碼</span>
            <input v-model="registerForm.confirm_password" type="password" autocomplete="new-password" required @blur="cleanRegisterPassword" />
          </label>
          <button class="primary-action" type="submit" :disabled="loading">{{ loading ? "Creating..." : "Create account" }}</button>
          <button class="link-action" type="button" @click="mode = 'login'">回到登入</button>
        </form>
      </Transition>

      <div class="auth-divider"><span>or</span></div>
      <div v-if="googleConfig.google_enabled" ref="googleSlot" class="google-slot"></div>
      <button v-else class="ghost-action google-fallback" type="button" disabled>Google 登入尚未設定</button>
      <button class="link-action guest-link" type="button" @click="continueAsGuest">以訪客模式進入</button>
    </section>
  </main>
</template>
