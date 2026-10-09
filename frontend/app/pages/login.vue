<script setup lang="ts">
definePageMeta({ layout: 'public' })

const api = useApi()
const auth = useAuth()
const email = ref('owner@kara.example')
const password = ref('demo1234')
const busy = ref(false)
const error = ref('')

onMounted(() => {
  auth.restore()
  if (auth.token.value) {
    const role = auth.user.value?.role
    if (role === 'supplier') navigateTo('/supplier')
    else if (role === 'agm') navigateTo('/agm')
    else navigateTo('/dashboard')
  }
})

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const res = await api.login(email.value.trim(), password.value)
    auth.setSession(res)
    // §43: each participant lands in their own surface
    const role = res.user?.role
    if (role === 'supplier') navigateTo('/supplier')
    else if (role === 'agm') navigateTo('/agm')
    else navigateTo('/dashboard')
  }
  catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    error.value = status === 401
      ? 'Invalid email or password.'
      : 'Could not reach the ECOS API — is the backend running?'
  }
  finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-brand">
        ECOS
        <small>LUXEEN COMMERCE OS · BY PLANNEXIS</small>
      </div>
      <h1>Sign in</h1>
      <p class="muted" style="margin-top:-.4rem">Operator access to the commerce network.</p>

      <form @submit.prevent="submit">
        <label class="field">
          <span>Email</span>
          <input v-model="email" type="email" autocomplete="username" required>
        </label>
        <label class="field">
          <span>Password</span>
          <input v-model="password" type="password" autocomplete="current-password" required>
        </label>
        <div v-if="error" class="login-error">{{ error }}</div>
        <button class="primary" style="width:100%" :disabled="busy">
          {{ busy ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <div class="login-demo">
        <div class="muted" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.4rem">
          Demo accounts · password <code>demo1234</code>
        </div>
        <ul>
          <li><code>owner@kara.example</code> — Kara owner (operator, all permissions)</li>
          <li><code>bisi@kara.example</code> — Kara agent (CRM + orders only)</li>
          <li><code>ops@luxeen.example</code> — Luxeen platform admin (review gate)</li>
          <li><code>supplier@shenzhen.example</code> — supplier portal (CN side)</li>
          <li><code>agent@eko.example</code> — AGM console (local fulfillment)</li>
        </ul>
      </div>

      <NuxtLink to="/" class="muted" style="font-size:.8rem">← Back to storefront</NuxtLink>
    </div>
  </div>
</template>
