<script setup lang="ts">
/**
 * Admin (default) layout — the ECOS Command Center shell.
 * Public storefront pages opt into the `public` layout instead.
 */
const auth = useAuth()
const mounted = ref(false)
onMounted(() => {
  auth.restore()
  mounted.value = true
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        ECOS
        <small>LUXEEN COMMERCE OS · BY PLANNEXIS</small>
      </div>
      <nav class="nav">
        <NuxtLink to="/dashboard">Command Center</NuxtLink>
        <NuxtLink to="/catalog">Catalog</NuxtLink>
        <NuxtLink to="/crm">CRM · Leads</NuxtLink>
        <NuxtLink to="/orders">Orders</NuxtLink>
        <NuxtLink to="/logistics">Logistics</NuxtLink>
        <NuxtLink to="/returns">Returns · RMA</NuxtLink>
        <NuxtLink to="/finance">Finance · Ledger</NuxtLink>
        <NuxtLink to="/marketing">Marketing · Attribution</NuxtLink>
        <NuxtLink to="/landing-pages">Landing Pages</NuxtLink>
        <NuxtLink to="/events">Event Stream</NuxtLink>
      </nav>
      <div class="sidebar-foot">
        <template v-if="mounted && auth.user.value">
          <div class="user-chip">
            <span class="user-name">{{ auth.user.value.name }}</span>
            <span class="user-role">{{ auth.user.value.role }} · {{ auth.user.value.email }}</span>
          </div>
          <div class="foot-actions">
            <NuxtLink to="/" class="ghost-link" target="_blank">View storefront ↗</NuxtLink>
            <button class="ghost small" @click="auth.logout()">Sign out</button>
          </div>
        </template>
        <template v-else>
          Corridor: China → Nigeria<br>
          Currencies: CNY · NGN · USD<br>
          Phase 2 build
        </template>
      </div>
    </aside>
    <main class="content">
      <NuxtPage />
    </main>
  </div>
</template>
