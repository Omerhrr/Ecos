<script setup lang="ts">
/**
 * §14 completion — public cart + checkout.
 * The cart is client-side (useCart); pricing is re-verified server-side via
 * /public/checkout/quote, then /public/checkout places a REAL order through
 * the same order pipeline the operators use (pricing waterfall, snapshots,
 * payment record, notifications). COD is the corridor default.
 */
definePageMeta({ layout: 'public' })

const api = useApi()
const route = useRoute()
const utm = useUtm()
const cart = useCart()

const money = (n: number) =>
  new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(n)

onMounted(() => {
  cart.load()
  utm.capture(route.query)
})

const form = reactive({
  full_name: '', contact_phone: '', address: '', city: '', state: '',
  payment_method: 'cod' as 'cod' | 'online_transfer', note: '',
})
const placing = ref(false)
const placeError = ref('')
const result = ref<CheckoutResult | null>(null)

async function placeOrder() {
  if (!cart.lines.value.length) return
  placing.value = true
  placeError.value = ''
  try {
    const res = await api.checkout({
      items: cart.lines.value.map(l => ({ product_slug: l.slug, qty: l.qty })),
      full_name: form.full_name.trim(),
      contact_phone: form.contact_phone.trim(),
      address: form.address.trim(),
      city: form.city.trim(),
      state: form.state.trim(),
      payment_method: form.payment_method,
      note: form.note.trim(),
      utm: utm.payload(),
    })
    result.value = res
    cart.clear()
  }
  catch (e: unknown) {
    const err = e as { response?: { _data?: { detail?: string } } }
    placeError.value = err.response?._data?.detail ?? 'Could not place your order — please try again.'
  }
  finally {
    placing.value = false
  }
}
</script>

<template>
  <div class="pub-container">
    <template v-if="result">
      <div class="cart-done">
        <div class="cart-done-badge">✓</div>
        <h1>Order #{{ result.order_id }} placed!</h1>
        <p class="muted">{{ result.message }}</p>
        <div class="cart-done-total">Total: <b>{{ money(result.total) }}</b> · {{ result.payment_method === 'cod' ? 'Pay on delivery' : 'Online transfer' }}</div>
        <p class="muted" style="font-size:.85rem">Keep your phone number handy — you can check the status any time with it.</p>
        <div class="cart-done-actions">
          <NuxtLink to="/products" class="pub-btn">Keep shopping</NuxtLink>
        </div>
      </div>
    </template>

    <template v-else>
      <h1 class="pub-page-title">Your cart</h1>

      <div v-if="!cart.lines.value.length" class="pub-empty">
        <p>Your cart is empty.</p>
        <NuxtLink to="/products" class="pub-btn">Browse products</NuxtLink>
      </div>

      <div v-else class="cart-layout">
        <div class="cart-lines">
          <div v-for="l in cart.lines.value" :key="l.slug" class="cart-line">
            <div class="cart-line-img">
              <img v-if="l.image" :src="l.image" :alt="l.title">
              <span v-else>{{ l.title.slice(0, 2).toUpperCase() }}</span>
            </div>
            <div class="cart-line-body">
              <NuxtLink :to="`/products/${l.slug}`" class="cart-line-title">{{ l.title }}</NuxtLink>
              <div class="muted">{{ money(l.price_ngn) }} each</div>
              <div class="cart-qty">
                <button @click="cart.setQty(l.slug, l.qty - 1)">−</button>
                <input
                  :value="l.qty"
                  type="number"
                  min="1"
                  :max="Math.max(l.stock, 1)"
                  @change="cart.setQty(l.slug, Number(($event.target as HTMLInputElement).value) || 1)"
                >
                <button @click="cart.setQty(l.slug, l.qty + 1)">+</button>
              </div>
            </div>
            <div class="cart-line-side">
              <div class="cart-line-total">{{ money(l.price_ngn * l.qty) }}</div>
              <button class="cart-remove" @click="cart.remove(l.slug)">Remove</button>
            </div>
          </div>
        </div>

        <div class="cart-checkout">
          <h3>Checkout</h3>
          <div class="cart-totals">
            <div><span>Items ({{ cart.count.value }})</span><b>{{ money(cart.itemsTotal.value) }}</b></div>
            <div><span>Delivery</span><b class="ok">Free</b></div>
            <div class="cart-grand"><span>Total</span><b>{{ money(cart.itemsTotal.value) }}</b></div>
          </div>

          <form class="cart-form" @submit.prevent="placeOrder">
            <label class="field"><span>Full name</span>
              <input v-model="form.full_name" required minlength="2" placeholder="e.g. Amaka Okafor">
            </label>
            <label class="field"><span>Phone number</span>
              <input v-model="form.contact_phone" required minlength="7" placeholder="e.g. +234 803 000 0000">
            </label>
            <label class="field"><span>Delivery address</span>
              <input v-model="form.address" required minlength="4" placeholder="Street / house details">
            </label>
            <div class="cart-form-row">
              <label class="field"><span>City</span>
                <input v-model="form.city" required maxlength="100" placeholder="e.g. Lagos">
              </label>
              <label class="field"><span>State</span>
                <input v-model="form.state" required maxlength="100" placeholder="e.g. Lagos">
              </label>
            </div>
            <div class="field">
              <span>Payment</span>
              <div class="cart-pay">
                <label :class="{ active: form.payment_method === 'cod' }">
                  <input v-model="form.payment_method" type="radio" value="cod">
                  <b>Pay on delivery</b><small>Cash when it arrives</small>
                </label>
                <label :class="{ active: form.payment_method === 'online_transfer' }">
                  <input v-model="form.payment_method" type="radio" value="online_transfer">
                  <b>Bank transfer</b><small>Pay now, get receipt</small>
                </label>
              </div>
            </div>
            <label class="field"><span>Note for the agent <i>(optional)</i></span>
              <input v-model="form.note" maxlength="300" placeholder="e.g. Call before 6pm">
            </label>

            <div v-if="placeError" class="login-error">{{ placeError }}</div>
            <button class="pub-btn lg wide" :disabled="placing || !cart.lines.value.length">
              {{ placing ? 'Placing order…' : `Place order · ${money(cart.itemsTotal.value)}` }}
            </button>
            <p class="muted cart-terms">By ordering you agree to a confirmation call. 7-day returns.</p>
          </form>
        </div>
      </div>
    </template>
  </div>
</template>
