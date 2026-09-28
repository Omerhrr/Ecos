<script setup lang="ts">
/**
 * §14 — public order tracking (no auth).
 *
 * The customer identifies with two things only they know: the order number
 * (from the checkout success screen / confirmation message) and the phone
 * number they checked out with. The API is phone-guarded; this page turns
 * the response into a friendly status ladder + shipment checkpoint timeline.
 */
definePageMeta({ layout: 'public' })

const api = useApi()
const route = useRoute()

const money = (n: number) =>
  new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(n)

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' }) : '—'

const form = reactive({ order: '', phone: '' })
const tracking = ref(false)
const error = ref('')
const order = ref<PublicOrderStatus | null>(null)

onMounted(() => {
  // /track?order=32 (link from the checkout success screen) prefills the number
  if (route.query.order) form.order = String(route.query.order)
  if (route.query.phone) form.phone = String(route.query.phone)
  if (form.order && form.phone) void submit()
})

async function submit() {
  const id = String(form.order).replace(/[^0-9]/g, '')
  if (!id || !form.phone.trim()) {
    error.value = 'Enter your order number and the phone number you used at checkout.'
    return
  }
  tracking.value = true
  error.value = ''
  order.value = null
  try {
    order.value = await api.publicOrderStatus(Number(id), form.phone.trim())
  }
  catch (e: unknown) {
    const err = e as { response?: { status?: number; _data?: { detail?: string } } }
    if (err.response?.status === 404) error.value = 'We couldn\u2019t find that order — double-check the order number.'
    else if (err.response?.status === 403) error.value = 'That phone number doesn\u2019t match this order.'
    else error.value = err.response?._data?.detail ?? 'Something went wrong — please try again.'
  }
  finally {
    tracking.value = false
  }
}

function reset() {
  order.value = null
  error.value = ''
  form.order = ''
  form.phone = ''
}

/* Order status ladder (§19) — the customer-facing view of the machine */
const LADDER = [
  { key: 'pending_confirmation', label: 'Order placed' },
  { key: 'confirmed', label: 'Confirmed' },
  { key: 'processing', label: 'Processing' },
  { key: 'fulfilled', label: 'Packed' },
  { key: 'in_transit', label: 'In transit' },
  { key: 'out_for_delivery', label: 'Out for delivery' },
  { key: 'delivered', label: 'Delivered' },
]
const BAD_STATUSES: Record<string, string> = {
  cancelled: 'This order was cancelled.',
  failed: 'This order failed — contact support for help.',
  returned: 'This order was returned to us.',
  refunded: 'This order was refunded.',
  disputed: 'This order is under review.',
}
const stepIndex = computed(() => {
  if (!order.value) return -1
  return LADDER.findIndex(s => s.key === order.value!.status)
})

/* §23 normalized tracking codes -> friendly labels */
const TRACK_LABELS: Record<string, string> = {
  supplier_processing: 'Supplier processing',
  picked_up: 'Picked up',
  origin_warehouse: 'Origin warehouse',
  exported: 'Exported',
  in_transit: 'In transit',
  customs: 'Customs clearance',
  destination_hub: 'Destination hub',
  local_courier: 'With local courier',
  out_for_delivery: 'Out for delivery',
  delivered: 'Delivered',
  return_requested: 'Return requested',
  return_pickup: 'Return pickup',
  return_received: 'Return received',
}
</script>

<template>
  <div class="pub-container track-page">
    <!-- lookup form -->
    <template v-if="!order">
      <h1 class="pub-page-title">Track your order</h1>
      <p class="muted track-sub">Enter the order number and the phone number you used at checkout.</p>

      <form class="track-form" @submit.prevent="submit">
        <label>
          <span>Order number</span>
          <input v-model="form.order" type="text" placeholder="e.g. #32 or 32" autocomplete="off">
        </label>
        <label>
          <span>Phone number</span>
          <input v-model="form.phone" type="tel" placeholder="e.g. 0803 123 4567" autocomplete="tel">
        </label>
        <button class="pub-btn lg" type="submit" :disabled="tracking">
          {{ tracking ? 'Checking…' : 'Track order' }}
        </button>
      </form>

      <p v-if="error" class="track-error">{{ error }}</p>
    </template>

    <!-- result -->
    <template v-else>
      <div class="track-head">
        <div>
          <h1 class="pub-page-title">Order {{ order.order_number }}</h1>
          <p class="muted">Placed {{ when(order.placed_at) }}</p>
        </div>
        <button class="track-again" @click="reset">Track another order</button>
      </div>

      <!-- terminal / branched states -->
      <div v-if="BAD_STATUSES[order.status]" class="track-banner" :class="{ bad: ['cancelled', 'failed', 'refunded', 'disputed'].includes(order.status) }">
        {{ BAD_STATUSES[order.status] }}
      </div>

      <!-- status ladder -->
      <div v-else class="track-ladder">
        <div
          v-for="(step, i) in LADDER"
          :key="step.key"
          class="track-step"
          :class="{ done: i < stepIndex, now: i === stepIndex }"
        >
          <span class="track-dot">{{ i < stepIndex ? '✓' : i + 1 }}</span>
          <span class="track-step-label">{{ step.label }}</span>
        </div>
      </div>

      <!-- shipment -->
      <div v-if="order.shipment" class="track-shipment">
        <div class="track-shipment-head">
          <div>
            <h3>{{ order.shipment.carrier }}</h3>
            <div class="muted">Tracking code: <b>{{ order.shipment.tracking_code }}</b></div>
          </div>
          <span class="track-shipment-status">{{ order.shipment.status.replaceAll('_', ' ') }}</span>
        </div>
        <ol class="track-checkpoints">
          <li v-for="(ev, i) in order.shipment.tracking_events" :key="i" :class="{ first: i === 0 }">
            <div class="cp-line" />
            <div class="cp-body">
              <b>{{ TRACK_LABELS[ev.code] ?? ev.code }}</b>
              <span v-if="ev.location" class="muted"> · {{ ev.location }}</span>
              <div class="muted cp-when">{{ ev.description }} — {{ when(ev.occurred_at) }}</div>
            </div>
          </li>
        </ol>
      </div>
      <div v-else-if="!BAD_STATUSES[order.status]" class="track-noshipment muted">
        No shipment yet — once your order is packed and handed to the courier, tracking updates appear here.
      </div>

      <!-- items -->
      <div class="track-items">
        <h3>Items</h3>
        <div v-for="(it, i) in order.items" :key="i" class="track-item">
          <span class="track-item-title">{{ it.title }} <span class="muted">× {{ it.qty }}</span></span>
          <span>{{ money(it.unit_price * it.qty) }}</span>
        </div>
        <div class="track-item track-total">
          <span>Total · {{ order.payment_method === 'cod' ? 'Pay on delivery' : 'Online transfer' }} ({{ order.payment_status }})</span>
          <b>{{ money(order.total) }}</b>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.track-page { min-height: 60vh; }
.track-sub { margin-bottom: 1.4rem; }
.track-form {
  display: grid; gap: 1rem; max-width: 420px;
  background: #fff; border: 1px solid #e5e9ee; border-radius: 12px; padding: 1.4rem;
}
.track-form label { display: grid; gap: .35rem; font-size: .82rem; font-weight: 600; color: #334; }
.track-form input {
  border: 1px solid #d7dde5; border-radius: 8px; padding: .6rem .75rem; font-size: .95rem;
}
.track-form input:focus { outline: 2px solid var(--accent, #16a34a); outline-offset: -1px; }
.track-form button { margin-top: .2rem; }
.track-form button:disabled { opacity: .6; }
.track-error { color: #b91c1c; margin-top: .9rem; font-size: .9rem; }

.track-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
.track-again {
  background: none; border: 1px solid #d7dde5; border-radius: 8px;
  padding: .45rem .8rem; font-size: .85rem; cursor: pointer; color: #334;
}
.track-again:hover { border-color: #9aa6b5; }

.track-banner {
  margin-top: 1.2rem; padding: .9rem 1.1rem; border-radius: 10px;
  background: #fef9c3; border: 1px solid #fde047; color: #713f12; font-weight: 600;
}
.track-banner.bad { background: #fee2e2; border-color: #fecaca; color: #991b1b; }

.track-ladder {
  display: flex; justify-content: space-between; gap: .3rem; margin-top: 1.4rem;
  background: #fff; border: 1px solid #e5e9ee; border-radius: 12px; padding: 1.2rem 1rem 1rem;
  overflow-x: auto;
}
.track-step { display: grid; justify-items: center; gap: .45rem; flex: 1; min-width: 72px; position: relative; }
.track-step:not(:last-child)::after {
  content: ''; position: absolute; top: 13px; left: calc(50% + 16px); width: calc(100% - 32px);
  height: 2px; background: #e5e9ee;
}
.track-step.done:not(:last-child)::after { background: #16a34a; }
.track-dot {
  width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: #eef1f5; color: #667; font-size: .72rem; font-weight: 700; z-index: 1;
}
.track-step.done .track-dot { background: #16a34a; color: #fff; }
.track-step.now .track-dot { background: #0e1621; color: #fff; box-shadow: 0 0 0 4px rgba(14, 22, 33, .15); }
.track-step-label { font-size: .72rem; font-weight: 600; color: #445; text-align: center; }
.track-step.now .track-step-label { color: #0e1621; }

.track-shipment {
  margin-top: 1.2rem; background: #fff; border: 1px solid #e5e9ee; border-radius: 12px; padding: 1.2rem;
}
.track-shipment-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.track-shipment-head h3 { margin: 0 0 .2rem; font-size: 1rem; }
.track-shipment-status {
  background: #0e1621; color: #fff; border-radius: 999px; padding: .3rem .8rem;
  font-size: .75rem; font-weight: 700; text-transform: capitalize;
}
.track-checkpoints { list-style: none; margin: 1.1rem 0 0; padding: 0; display: grid; gap: .9rem; }
.track-checkpoints li { display: flex; gap: .8rem; position: relative; padding-bottom: .2rem; }
.track-checkpoints li:not(:last-child) .cp-line {
  position: absolute; left: 5px; top: 14px; bottom: -12px; width: 2px; background: #e5e9ee;
}
.cp-dot, .track-checkpoints li::before {
  content: ''; width: 12px; height: 12px; border-radius: 50%; background: #cbd5e1;
  flex-shrink: 0; margin-top: 4px; position: relative; z-index: 1;
}
.track-checkpoints li.first::before { background: #16a34a; }
.cp-body { font-size: .88rem; }
.cp-when { font-size: .78rem; margin-top: .1rem; }

.track-noshipment {
  margin-top: 1.2rem; background: #fff; border: 1px dashed #d7dde5; border-radius: 12px;
  padding: 1rem 1.2rem; font-size: .88rem;
}

.track-items {
  margin-top: 1.2rem; background: #fff; border: 1px solid #e5e9ee; border-radius: 12px; padding: 1.2rem;
}
.track-items h3 { margin: 0 0 .8rem; font-size: 1rem; }
.track-item {
  display: flex; justify-content: space-between; gap: 1rem; padding: .45rem 0;
  border-bottom: 1px solid #f0f3f7; font-size: .9rem;
}
.track-item-title { font-weight: 600; }
.track-total { border-bottom: none; border-top: 2px solid #0e1621; margin-top: .4rem; padding-top: .7rem; font-size: .95rem; }
.muted { color: #67788c; }
</style>
