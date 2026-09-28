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
onMounted(load)

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
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Notifications</h1>
        <div class="sub">plan §39 — domain events fan out here per user; preferences mute categories at the dispatcher, not just in the UI</div>
      </div>
      <div class="row" style="gap:.5rem">
        <button class="ghost" @click="sendTest">Send test</button>
        <button :disabled="!unread" @click="readAll">Mark all read{{ unread ? ` (${unread})` : '' }}</button>
      </div>
    </div>

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
          In-app is live today. Email and WhatsApp switches are wired into the dispatcher for the Phase 3 outbound workers — flipping them now records intent.
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
          Click any notification to mark it read. The <b>Send test</b> button drops a row into your own feed.
        </div>
      </div>
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
</style>
