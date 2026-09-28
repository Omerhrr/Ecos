<script setup lang="ts">
/**
 * Notification center (plan §39).
 * In-app feed fanned out from domain events, plus per-user channel
 * preferences — muting a category takes effect immediately because the
 * dispatcher honours it at fan-out time.
 */
const api = useApi()
const { date } = useFormat()

const notes = ref<EcosNotification[]>([])
const prefs = ref<NotificationPreference[]>([])
const unread = ref(0)
const loading = ref(true)
const filter = ref<string>('')
const showRead = ref(true)
const error = ref('')

// §39 Phase 3 — outbound channel workers (email / WhatsApp outbox)
const outboxRows = ref<OutboxRow[]>([])
const outboxInfo = ref<OutboxStats | null>(null)
const outboxChannel = ref<'' | 'email' | 'whatsapp'>('')
const outboxStatus = ref<'' | 'queued' | 'sent' | 'failed'>('')
const processing = ref(false)

const CATEGORIES = ['orders', 'payments', 'shipments', 'returns', 'settlements', 'ai', 'procurement', 'leads', 'system']

const LEVEL_DOT: Record<string, string> = {
  info: '#38bdf8', success: '#00b374', warning: '#f59e0b', critical: '#f87171',
}
const LEVEL_BG: Record<string, string> = {
  info: 'rgba(56,189,248,.08)', success: 'rgba(0,179,116,.08)',
  warning: 'rgba(245,158,11,.08)', critical: 'rgba(248,113,113,.10)',
}

const filtered = computed(() =>
  notes.value.filter(n =>
    (!filter.value || n.category === filter.value)
    && (showRead.value || !n.read),
  ),
)
const unreadIn = (cat: string) => notes.value.filter(n => n.category === cat && !n.read).length

async function load() {
  loading.value = true
  try {
    const [n, p, u] = await Promise.all([
      api.notifications({ limit: 200 }),
      api.notificationPreferences(),
      api.unreadCount(),
    ])
    notes.value = n
    prefs.value = p
    unread.value = u.unread
  }
  finally { loading.value = false }
}

async function loadOutbox() {
  const params: Record<string, unknown> = { limit: 50 }
  if (outboxChannel.value) params.channel = outboxChannel.value
  if (outboxStatus.value) params.status = outboxStatus.value
  const [rows, stats] = await Promise.all([
    api.outbox(params),
    api.outboxStats(),
  ])
  outboxRows.value = rows
  outboxInfo.value = stats
}

onMounted(() => { load(); loadOutbox() })

async function markRead(n: EcosNotification) {
  if (n.read) return
  await api.markNotificationRead(n.id)
  n.read = true
  unread.value = Math.max(0, unread.value - 1)
}

async function readAll() {
  const r = await api.markAllNotificationsRead()
  await load()
  error.value = r.marked ? '' : 'Nothing unread'
  setTimeout(() => { error.value = '' }, 1500)
}

async function sendTest() {
  await api.sendTestNotification()
  await load()
}

async function togglePref(p: NotificationPreference, key: 'in_app' | 'email' | 'whatsapp') {
  const updated = await api.updateNotificationPreference({ category: p.category, [key]: !p[key] })
  Object.assign(p, updated)
}

async function runWorkers() {
  processing.value = true
  try {
    const r = await api.processOutbox()
    await loadOutbox()
    if (r.processed) { error.value = ''; flash.value = `Workers processed ${r.processed} message(s): ${r.sent} sent, ${r.failed} failed, ${r.retried} retried` }
  }
  finally { processing.value = false }
}

const flash = ref('')
const obStatusColor: Record<string, string> = { queued: '#eab308', sent: '#00b374', failed: '#f87171', skipped: '#94a3b8' }
const filteredOutbox = computed(() => outboxRows.value)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Notifications</h1>
        <div class="sub">plan §39 — events fan out per user; Phase 3 workers deliver email / WhatsApp from the outbox</div>
      </div>
      <div class="row" style="gap:.5rem">
        <button class="ghost" @click="sendTest">Send test</button>
        <button :disabled="!unread" @click="readAll">Mark all read{{ unread ? ` (${unread})` : '' }}</button>
      </div>
    </div>

    <div v-if="flash" class="flash-ok">{{ flash }}</div>

    <div class="grid2">
      <div>
        <div class="row" style="gap:.35rem;flex-wrap:wrap;margin-bottom:.7rem">
          <button class="chip" :class="{ on: !filter }" @click="filter = ''">All · {{ notes.length }}</button>
          <button
            v-for="c in CATEGORIES" :key="c"
            class="chip" :class="{ on: filter === c }" @click="filter = filter === c ? '' : c">
            {{ c }}<template v-if="unreadIn(c)"> · <b>{{ unreadIn(c) }}</b></template>
          </button>
          <button class="chip" :class="{ on: !showRead }" @click="showRead = !showRead">{{ showRead ? 'Hide read' : 'Show read' }}</button>
        </div>

        <div v-if="loading" class="empty">Loading notifications…</div>
        <div v-else-if="!filtered.length" class="empty">Nothing here — events like deliveries, refunds, RMA requests, settlements and Stock Prophet alerts will land in this feed.</div>
        <div v-else class="feed">
          <div
            v-for="n in filtered" :key="n.id"
            class="note" :class="{ unread: !n.read }"
            :style="{ background: LEVEL_BG[n.level] }"
            @click="markRead(n)">
            <span class="dot" :style="{ background: LEVEL_DOT[n.level] }" />
            <div style="flex:1;min-width:0">
              <div class="note-title">{{ n.title }}</div>
              <div v-if="n.body" class="note-body">{{ n.body }}</div>
              <div class="note-meta">
                <span class="cat">{{ n.category }}</span>
                <span>{{ date(n.created_at || '') }}</span>
                <span v-if="n.entity_type" class="mono">→ {{ n.entity_type }} #{{ n.entity_id }}</span>
              </div>
            </div>
            <span v-if="!n.read" class="unread-dot" title="unread" />
          </div>
        </div>
        <div v-if="error" class="muted" style="font-size:.78rem;margin-top:.5rem">{{ error }}</div>
      </div>

      <div class="card pad">
        <h3 style="margin-bottom:.2rem">Channel preferences</h3>
        <div class="muted" style="font-size:.76rem;margin-bottom:.8rem">
          Flipping <b>Email</b> / <b>WhatsApp</b> on queues real outbound messages to the outbox below — the workers deliver them (dev-console provider logs to the API stdout when no SMTP/Cloud credentials are set).
        </div>
        <table>
          <thead><tr><th>Category</th><th>In-app</th><th>Email</th><th>WhatsApp</th></tr></thead>
          <tbody>
            <tr v-for="p in prefs" :key="p.category">
              <td style="text-transform:capitalize">{{ p.category }}</td>
              <td><input type="checkbox" :checked="p.in_app" @change="togglePref(p, 'in_app')" /></td>
              <td><input type="checkbox" :checked="p.email" @change="togglePref(p, 'email')" /></td>
              <td><input type="checkbox" :checked="p.whatsapp" @change="togglePref(p, 'whatsapp')" /></td>
            </tr>
          </tbody>
        </table>
        <div class="muted" style="font-size:.76rem;margin-top:.8rem">
          WhatsApp delivery needs a phone number on your user record; email uses your login email.
        </div>
      </div>
    </div>

    <!-- §39 Phase 3 — outbound workers -->
    <div class="card pad" style="margin-top:1rem">
      <div class="row" style="justify-content:space-between;align-items:flex-start;margin-bottom:.6rem">
        <div>
          <h3 style="margin:0">Outbound channels · email / WhatsApp workers</h3>
          <div class="muted" style="font-size:.76rem">
            Providers: <b>{{ outboxInfo?.providers.email || '…' }}</b> (email) · <b>{{ outboxInfo?.providers.whatsapp || '…' }}</b> (WhatsApp) — background worker ticks every 30s, or run it now.
          </div>
        </div>
        <button :disabled="processing" @click="runWorkers">{{ processing ? 'Running…' : 'Run workers now' }}</button>
      </div>

      <div class="row" style="gap:.4rem;flex-wrap:wrap;margin-bottom:.7rem">
        <button v-for="(s, ch) in outboxInfo?.by_channel || {}" :key="ch"
                class="chip" :class="{ on: outboxChannel === ch }" @click="outboxChannel = outboxChannel === ch ? '' : (ch as any)">
          {{ ch }} · {{ s.sent }}/{{ s.total }} sent
        </button>
        <span class="spacer" />
        <button class="chip" :class="{ on: outboxStatus === 'queued' }" @click="outboxStatus = outboxStatus === 'queued' ? '' : 'queued'">queued</button>
        <button class="chip" :class="{ on: outboxStatus === 'sent' }" @click="outboxStatus = outboxStatus === 'sent' ? '' : 'sent'">sent</button>
        <button class="chip" :class="{ on: outboxStatus === 'failed' }" @click="outboxStatus = outboxStatus === 'failed' ? '' : 'failed'">failed</button>
        <button class="chip" @click="loadOutbox">↻</button>
      </div>

      <table>
        <thead><tr><th>When</th><th>Channel</th><th>Recipient</th><th>Message</th><th>Status</th><th>Attempts</th><th>Provider ref</th></tr></thead>
        <tbody>
          <tr v-for="r in filteredOutbox" :key="r.id">
            <td class="muted">{{ date(r.created_at || '') }}</td>
            <td><span class="ch-badge" :class="r.channel">{{ r.channel }}</span></td>
            <td class="mono" style="font-size:.75rem">{{ r.recipient }}</td>
            <td style="max-width:340px">
              <div style="font-size:.8rem;font-weight:600">{{ r.subject }}</div>
              <div class="muted" style="font-size:.72rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.body }}</div>
              <div v-if="r.last_error" style="font-size:.7rem;color:#fca5a5">{{ r.last_error }}</div>
            </td>
            <td><StatusBadge :status="r.status" :color="obStatusColor[r.status]" /></td>
            <td class="muted">{{ r.attempts }}/{{ r.max_attempts }}</td>
            <td class="muted mono" style="font-size:.72rem">{{ r.provider_ref || '—' }}</td>
          </tr>
          <tr v-if="!filteredOutbox.length">
            <td colspan="7" class="muted">Outbox is empty — flip Email/WhatsApp on for a category and the next notification will queue here.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.grid2 { display: grid; grid-template-columns: 1.7fr 1fr; gap: 1rem; align-items: start; }
@media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
.card.pad { padding: 1rem 1.2rem; }
.feed { display: flex; flex-direction: column; gap: .5rem; }
.note {
  display: flex; gap: .7rem; align-items: flex-start;
  border: 1px solid rgba(148, 163, 184, .18); border-radius: 10px;
  padding: .65rem .85rem; cursor: pointer; transition: border-color .15s;
}
.note:hover { border-color: rgba(56, 189, 248, .45); }
.note.unread { border-left: 3px solid #38bdf8; }
.dot { width: 9px; height: 9px; border-radius: 50%; margin-top: .38rem; flex-shrink: 0; }
.note-title { font-weight: 600; font-size: .86rem; }
.note-body { font-size: .78rem; color: #94a3b8; margin-top: .15rem; line-height: 1.45; }
.note-meta { display: flex; gap: .7rem; font-size: .7rem; color: #64748b; margin-top: .3rem; align-items: center; }
.note-meta .cat { text-transform: uppercase; letter-spacing: .06em; font-size: .62rem; background: rgba(148,163,184,.12); padding: .1rem .4rem; border-radius: 4px; }
.unread-dot { width: 7px; height: 7px; border-radius: 50%; background: #38bdf8; margin-top: .45rem; flex-shrink: 0; }
.chip { font-size: .74rem; padding: .28rem .65rem; border-radius: 999px; border: 1px solid rgba(148,163,184,.25); background: transparent; color: #cbd5e1; cursor: pointer; }
.chip.on { border-color: #38bdf8; color: #38bdf8; background: rgba(56,189,248,.08); }
.chip b { color: #38bdf8; }
input[type='checkbox'] { accent-color: #38bdf8; width: 15px; height: 15px; cursor: pointer; }
table td, table th { padding: .4rem .5rem; }
.flash-ok { background: rgba(0,179,116,.12); border: 1px solid rgba(0,179,116,.4); color: #4ade80; padding: .5rem .8rem; border-radius: 8px; margin-bottom: .8rem; font-size: .85rem; }
.spacer { flex: 1; }
.ch-badge { font-size: .7rem; font-weight: 700; padding: .15rem .5rem; border-radius: 99px; text-transform: uppercase; }
.ch-badge.email { background: rgba(56,189,248,.15); color: #7dd3fc; }
.ch-badge.whatsapp { background: rgba(0,179,116,.15); color: #4ade80; }
.mono { font-family: ui-monospace, monospace; }
</style>
