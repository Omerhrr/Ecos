<script setup lang="ts">
/**
 * USD pricing page (plan §46 — multi-currency).
 * Every active product priced in Naira and US Dollars via the live
 * corridor FX table. Supplier identity/costs stay hidden (§9) —
 * customers see the Ecos price, never the waterfall.
 */
definePageMeta({ layout: 'public' })

const api = useApi()

const data = ref<PublicPricing | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try { data.value = await api.publicPricing() }
  catch (e: unknown) { error.value = (e as Error)?.message || 'Could not load pricing' }
  finally { loading.value = false }
})

const usd = (n: number | undefined) =>
  n == null ? '—' : `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const ngn = (n: number) => `₦${Math.round(n).toLocaleString()}`
</script>

<template>
  <div class="pricing-wrap">
    <div class="pricing-head">
      <h1>Prices in US Dollars</h1>
      <p class="muted">
        Same products, same cash-on-delivery promise — shown in USD for international
        reference. Checkout settles in Naira at the day's corridor rate.
      </p>
    </div>

    <div v-if="loading" class="muted" style="padding:2rem 0">Loading prices…</div>
    <div v-else-if="error" class="muted" style="padding:2rem 0">{{ error }}</div>

    <template v-else-if="data">
      <div class="rate-note card">
        <span class="mono">1 NGN = ${{ data.usd.rate.toFixed(6) }}</span>
        <span class="muted">· rate source: {{ data.usd.source }} · all prices include delivery to your door</span>
      </div>

      <div class="pricing-grid">
        <div v-for="p in data.products" :key="p.id" class="product card">
          <div class="thumb-wrap">
            <img :src="p.image || ''" :alt="p.title" loading="lazy">
            <span v-if="!p.in_stock" class="oos">Sold out</span>
          </div>
          <div class="p-body">
            <div class="p-title">{{ p.title }}</div>
            <div class="p-cat muted">{{ p.category.replace('-', ' ') }}</div>
            <div class="p-prices">
              <span class="usd-price">{{ usd(p.price_display?.amount) }}</span>
              <span class="ngn-price muted">{{ ngn(p.price_ngn) }}</span>
            </div>
            <NuxtLink :to="`/products/${p.slug}`" class="p-cta">View & order</NuxtLink>
          </div>
        </div>
      </div>

      <div class="muted" style="margin-top:1.4rem;font-size:.82rem">
        Pay cash on delivery anywhere in Nigeria · tracked China→Nigeria shipping · 7-day returns.
      </div>
    </template>
  </div>
</template>

<style scoped>
.pricing-wrap { max-width: 1080px; margin: 0 auto; padding: 2rem 1.2rem 3rem; }
.pricing-head h1 { font-size: 1.7rem; margin-bottom: .3rem; }
.rate-note { display: inline-block; padding: .5rem .9rem; margin: .8rem 0 1.4rem; font-size: .84rem; }
.pricing-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 1rem; }
.product { overflow: hidden; display: flex; flex-direction: column; }
.thumb-wrap { position: relative; aspect-ratio: 4/3; background: #f1f5f9; }
.thumb-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.oos { position: absolute; top: .5rem; right: .5rem; background: #0f172a; color: #fff; font-size: .7rem; padding: .15rem .5rem; border-radius: 6px; opacity: .85; }
.p-body { padding: .8rem .9rem 1rem; display: flex; flex-direction: column; gap: .25rem; flex: 1; }
.p-title { font-weight: 600; font-size: .92rem; line-height: 1.3; }
.p-cat { font-size: .74rem; text-transform: capitalize; }
.p-prices { display: flex; align-items: baseline; gap: .5rem; margin: .35rem 0 .6rem; }
.usd-price { font-size: 1.15rem; font-weight: 700; color: #0f766e; }
.ngn-price { font-size: .82rem; }
.p-cta { margin-top: auto; background: #00b374; color: #fff; text-align: center; padding: .5rem .8rem; border-radius: 8px; font-size: .84rem; font-weight: 600; }
.p-cta:hover { background: #029e68; }
</style>
