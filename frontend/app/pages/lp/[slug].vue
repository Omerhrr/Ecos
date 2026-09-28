<script setup lang="ts">
/**
 * Public landing page renderer (§15): /lp/{slug}.
 * Renders any PUBLISHED page's blocks; applies the page theme color.
 */
definePageMeta({ layout: 'public' })

const route = useRoute()
const api = useApi()

const page = ref<PublicPage | null>(null)
const loading = ref(true)
const notFound = ref(false)

const themeColor = computed(() => page.value?.theme?.primary || '#00b374')

onMounted(async () => {
  try {
    page.value = await api.publicPage(String(route.params.slug))
    const seo = page.value?.seo ?? {}
    useHead({
      title: seo.title || page.value?.title,
      meta: seo.description ? [{ name: 'description', content: seo.description }] : [],
    })
  }
  catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 404) notFound.value = true
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div v-if="loading" class="pub-loading">Loading page…</div>

    <div v-else-if="notFound || !page" class="pub-empty">
      <h1>Page not found</h1>
      <p class="muted">This page doesn't exist or isn't published.</p>
      <NuxtLink to="/" class="pub-btn">← Back to store</NuxtLink>
    </div>

    <template v-else>
      <div :style="{ '--lp-primary': themeColor }">
        <BlockRenderer v-for="b in page.blocks" :key="b.id" :block="b" />
      </div>
    </template>
  </div>
</template>
