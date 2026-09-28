<script setup lang="ts">
definePageMeta({ layout: 'public' })

const api = useApi()
const products = ref<PublicProduct[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    products.value = await api.publicProducts()
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="pub-container">
    <h1 class="pub-page-title">All products</h1>
    <p class="muted" style="margin-top:-.6rem">Imported quality, nationwide delivery, pay on arrival.</p>

    <div v-if="loading" class="pub-loading">Loading products…</div>
    <div v-else-if="products.length" class="prod-grid">
      <ProductCard v-for="p in products" :key="p.id" :product="p" />
    </div>
    <div v-else class="pub-empty">
      <p>No products published yet — check back soon.</p>
    </div>
  </div>
</template>
