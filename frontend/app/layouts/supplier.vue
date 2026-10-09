<script setup lang="ts">
/**
 * Supplier portal layout (§8/§9) — the supply-side surface.
 * Suppliers see their listings and their sourcing orders only.
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
        <small>SUPPLIER PORTAL · SOURCE SIDE</small>
      </div>
      <nav class="nav">
        <NuxtLink to="/supplier">My Listings & Orders</NuxtLink>
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
          Origin: CN (any supply market)<br>
          Currency: CNY<br>
          Your identity stays private from buyers.
        </template>
      </div>
    </aside>
    <main class="content">
      <NuxtPage />
    </main>
  </div>
</template>
