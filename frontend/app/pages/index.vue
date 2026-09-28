<script setup lang="ts">
/**
 * Public storefront home (plan §14): renders the published `home`
 * landing page (§15 engine) plus the latest products.
 */
definePageMeta({ layout: 'public' })

const api = useApi()
const home = ref<PublicHome | null>(null)
const loading = ref(true)
const failed = ref(false)

onMounted(async () => {
  try {
    home.value = await api.publicHome()
    if (home.value.page?.seo?.title) {
      useHead({ title: home.value.page.seo.title })
    }
  }
  catch {
    failed.value = true
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div v-if="loading" class="pub-loading">Loading storefront…</div>

    <div v-else-if="failed" class="pub-empty">
      <h1>Storefront unavailable</h1>
      <p class="muted">Could not reach the ECOS API. Is the backend running on :8000?</p>
    </div>

    <template v-else-if="home">
      <!-- Published home page from the landing page engine -->
      <template v-if="home.page">
        <BlockRenderer v-for="b in home.page.blocks" :key="b.id" :block="b" />
      </template>

      <!-- Fallback when no `home` page is published yet -->
      <template v-else>
        <section class="blk">
          <div class="blk-hero">
            <div class="blk-hero-inner">
              <h1>{{ home.store.name }}</h1>
              <p>Quality imports, delivered nationwide — pay on delivery.</p>
              <NuxtLink to="/products" class="pub-btn lg">Shop now</NuxtLink>
            </div>
          </div>
        </section>
      </template>

      <!-- Latest products strip -->
      <section class="blk blk-wide">
        <h2 class="blk-center">Latest arrivals</h2>
        <div class="prod-grid">
          <ProductCard v-for="p in home.products" :key="p.id" :product="p" />
        </div>
        <div v-if="!home.products.length" class="muted blk-center">No products published yet.</div>
      </section>
    </template>
  </div>
</template>
