<script setup lang="ts">
/**
 * Public layout — customer-facing storefront chrome (plan §14).
 * No sidebar; light header with the active store name, nav and cart badge.
 */
const api = useApi()
const store = useAuth().token // just to react to login state changes
const storeName = useState<string>('pub-store-name', () => '')
const mounted = ref(false)
const cart = useCart()

onMounted(async () => {
  cart.load()
  mounted.value = true
  if (!storeName.value) {
    try {
      const s = await api.publicStore()
      storeName.value = s?.name ?? 'Storefront'
    }
    catch {
      storeName.value = 'Storefront'
    }
  }
})
</script>

<template>
  <div class="pub">
    <header class="pub-header">
      <div class="pub-header-inner">
        <NuxtLink to="/" class="pub-brand">
          <span v-if="storeName" class="pub-brand-name">{{ storeName }}</span>
          <span v-else class="pub-brand-name muted">…</span>
        </NuxtLink>
        <nav class="pub-nav">
          <NuxtLink to="/">Home</NuxtLink>
          <NuxtLink to="/products">Products</NuxtLink>
          <NuxtLink to="/cart" class="pub-cart-link">
            Cart
            <span v-if="mounted && cart.count.value" class="pub-cart-badge">{{ cart.count.value > 99 ? '99+' : cart.count.value }}</span>
          </NuxtLink>
        </nav>
        <div class="pub-auth">
          <template v-if="mounted && store">
            <NuxtLink to="/dashboard" class="pub-link">Dashboard</NuxtLink>
          </template>
          <NuxtLink v-else-if="mounted" to="/login" class="pub-link">Sign in</NuxtLink>
        </div>
      </div>
    </header>
    <main class="pub-main">
      <slot />
    </main>
    <footer class="pub-footer">
      <div>Powered by <b>ECOS</b> — Plannexis</div>
      <div class="muted">Cash on delivery · Nationwide shipping · 7-day returns</div>
    </footer>
  </div>
</template>
