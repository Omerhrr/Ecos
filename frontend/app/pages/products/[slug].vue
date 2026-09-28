<script setup lang="ts">
/**
 * Public product detail page (§14) with COD order-intent capture.
 * The intent becomes a CRM lead (§17) — an operator confirms and
 * creates the order; payment happens on delivery.
 */
definePageMeta({ layout: 'public' })

const route = useRoute()
const api = useApi()
const utm = useUtm()

const product = ref<PublicProductDetail | null>(null)
const loading = ref(true)
const notFound = ref(false)
const imgBroken = ref(false)
const activeImg = ref(0)
const cart = useCart()
const addedToCart = ref(false)

// §10 catalog depth: variant selection drives the displayed price, stock
// guard and the cart line (two options of one product can coexist in cart).
const selectedVariantId = ref<number | null>(null)

const selectedVariant = computed<PublicVariant | null>(() => {
  const p = product.value
  if (!p || !p.variants?.length) return null
  return p.variants.find(v => v.id === selectedVariantId.value) ?? p.variants[0]
})

const displayPrice = computed(() =>
  selectedVariant.value ? selectedVariant.value.price_ngn : (product.value?.price_ngn ?? 0),
)
const displayStock = computed(() =>
  selectedVariant.value ? selectedVariant.value.stock : (product.value?.stock ?? 0),
)
const displayInStock = computed(() =>
  selectedVariant.value ? selectedVariant.value.in_stock : (product.value?.in_stock ?? false),
)

function addToCart() {
  const p = product.value
  if (!p) return
  const v = selectedVariant.value
  cart.add({
    slug: p.slug,
    title: p.title,
    price_ngn: displayPrice.value,
    image: v?.image ?? p.image,
    in_stock: displayInStock.value,
    stock: displayStock.value,
    variant_id: v?.id ?? null,
    variant_label: v?.label ?? null,
  }, 1)
  addedToCart.value = true
  setTimeout(() => (addedToCart.value = false), 1800)
}

const form = reactive({ name: '', phone: '', qty: 1 })
const submitting = ref(false)
const submitted = ref(false)
const submitError = ref('')

const money = (n: number) =>
  new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(n)

onMounted(async () => {
  utm.capture(route.query)
  try {
    product.value = await api.publicProduct(String(route.params.slug))
    useHead({ title: product.value.title })
  }
  catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 404) notFound.value = true
  }
  finally {
    loading.value = false
  }
})

async function submitIntent() {
  if (!product.value?.slug) return
  submitting.value = true
  submitError.value = ''
  try {
    await api.submitOrderIntent({
      product_slug: product.value.slug,
      contact_name: form.name.trim(),
      contact_phone: form.phone.trim(),
      qty: form.qty,
      utm: utm.payload(),
    })
    submitted.value = true
  }
  catch (e: unknown) {
    const err = e as { response?: { status?: number; _data?: { detail?: string } } }
    submitError.value
      = err.response?._data?.detail
        ?? 'Could not submit your request — please try again.'
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="pub-container">
    <div v-if="loading" class="pub-loading">Loading product…</div>

    <div v-else-if="notFound || !product" class="pub-empty">
      <h1>Product not found</h1>
      <NuxtLink to="/products" class="pub-btn">← Back to products</NuxtLink>
    </div>

    <div v-else class="pdp">
      <div class="pdp-gallery">
        <div class="pdp-main-img">
          <img
            v-if="product.images[activeImg] && !imgBroken"
            :src="product.images[activeImg]"
            :alt="product.title"
            @error="imgBroken = true"
          >
          <span v-else class="prod-img-fallback big">{{ product.title.slice(0, 2).toUpperCase() }}</span>
        </div>
        <div v-if="product.images.length > 1" class="pdp-thumbs">
          <img
            v-for="(src, i) in product.images"
            :key="i"
            :src="src"
            :class="{ active: i === activeImg }"
            @click="activeImg = i; imgBroken = false"
          >
        </div>
      </div>

      <div class="pdp-info">
        <h1>{{ product.title }}</h1>
        <div class="pdp-price">{{ money(displayPrice) }}</div>
        <div class="pdp-cod-badge">💵 Pay on delivery — nationwide</div>

        <!-- §10 catalog depth: variant picker -->
        <div v-if="product.variants.length" class="pdp-variants">
          <span class="pdp-variants-label">Options</span>
          <button
            v-for="v in product.variants"
            :key="v.id"
            class="pdp-variant-chip"
            :class="{
              active: selectedVariant?.id === v.id,
              disabled: !v.in_stock,
            }"
            :disabled="!v.in_stock"
            @click="selectedVariantId = v.id"
          >
            {{ v.label }}
            <small>{{ v.in_stock ? money(v.price_ngn) : 'Out of stock' }}</small>
          </button>
        </div>

        <!-- §14 completion: instant cart path -->
        <div v-if="displayInStock" class="pdp-cart-row">
          <button class="pub-btn lg" @click="addToCart">
            {{ addedToCart ? 'Added ✓' : 'Add to cart' }}
          </button>
          <NuxtLink to="/cart" class="pdp-cart-link">Go to cart →</NuxtLink>
        </div>
        <p v-else class="pdp-oos">Out of stock — check back soon.</p>
        <p class="pdp-desc">{{ product.description }}</p>

        <!-- §10: product video media -->
        <div v-if="product.videos.length" class="pdp-videos">
          <h3>Product videos</h3>
          <video
            v-for="(src, i) in product.videos"
            :key="i"
            :src="src"
            controls
            preload="metadata"
            class="pdp-video"
          >Your browser cannot play this video.</video>
        </div>

        <div v-if="Object.keys(product.specs).length" class="pdp-specs">
          <div v-for="(v, k) in product.specs" :key="k" class="pdp-spec-row">
            <span class="muted">{{ k }}</span><span>{{ v }}</span>
          </div>
        </div>

        <!-- COD order intent -->
        <div class="pdp-order">
          <template v-if="submitted">
            <div class="pdp-order-ok">
              <b>Request received ✅</b>
              <p>Our agent will call you shortly to confirm your order.
                 You pay when it arrives at your door.</p>
            </div>
          </template>
          <template v-else>
            <h3>Order now — pay on delivery</h3>
            <form class="pdp-form" @submit.prevent="submitIntent">
              <label class="field">
                <span>Your name</span>
                <input v-model="form.name" required minlength="2" placeholder="e.g. Amaka Okafor">
              </label>
              <label class="field">
                <span>Phone number</span>
                <input v-model="form.phone" required minlength="7" placeholder="e.g. +234 803 000 0000">
              </label>
              <label class="field" style="max-width:110px">
                <span>Quantity</span>
                <input v-model.number="form.qty" type="number" min="1" max="99" required>
              </label>
              <div v-if="submitError" class="login-error">{{ submitError }}</div>
              <button class="primary lg" :disabled="submitting || !displayInStock">
                {{ !displayInStock ? 'Out of stock' : submitting ? 'Sending…' : 'Request my order' }}
              </button>
            </form>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
