<script setup lang="ts">
/**
 * AGM console layout — the agent's local fulfillment surface (§20-24).
 * Agents manage warehouses, per-vendor inventory, alerts and COD remittance.
 */
const auth = useAuth()
const mounted = ref(false)
onMounted(() => { auth.restore(); mounted.value = true })
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        ECOS
        <small>AGENT MANAGEMENT · AGM</small>
      </div>
      <nav class="nav">
        <NuxtLink to="/agm">Console</NuxtLink>
      </nav>
      <div class="sidebar-foot">
        <template v-if="mounted && auth.user.value">
          <div class="user-chip">
            <span class="user-name">{{ auth.user.value.name }}</span>
            <span class="user-role">{{ auth.user.value.email }}</span>
          </div>
          <div class="foot-actions">
            <button class="ghost small" @click="auth.logout()">Sign out</button>
          </div>
        </template>
        <template v-else>
          Destination side: NG (any market)<br>
          Hold stock per vendor. Call. Ship. Collect. Remit.
        </template>
      </div>
    </aside>
    <main class="content">
      <NuxtPage />
    </main>
  </div>
</template>
