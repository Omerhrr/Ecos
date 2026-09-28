/**
 * §16 marketing attribution — visitor-side UTM capture.
 *
 * Campaign links (meta/tiktok/google ads, WhatsApp broadcasts, landing pages)
 * arrive with ?utm_source=...&utm_campaign=... . We persist the last touch in
 * sessionStorage (per tab, survives navigation across /lp/* → /products/*)
 * and replay it when the visitor submits a COD order intent, so the lead
 * that lands in the CRM carries its full acquisition context.
 */

interface UtmPayload {
  utm_source?: string
  utm_medium?: string
  utm_campaign?: string
  utm_content?: string
  utm_term?: string
  landing_page?: string
  referrer?: string
}

const KEY = 'ecos:utm'

export function useUtm() {
  /** Call on every public page mount: stores last-touch UTM if present. */
  function capture(query: Record<string, string | string[] | undefined> = {}) {
    if (!import.meta.client) return
    const found: UtmPayload = {}
    for (const k of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'] as const) {
      const v = query[k]
      const s = Array.isArray(v) ? v[0] : v
      if (s) found[k] = String(s)
    }
    const existing = read()
    if (Object.keys(found).length) {
      sessionStorage.setItem(KEY, JSON.stringify({ ...existing, ...found }))
    }
    else if (!existing) {
      // no explicit UTM — attribute the landing context anyway (organic/storefront)
      const ref = document.referrer || ''
      const external = ref && !ref.includes(window.location.host)
      if (external) sessionStorage.setItem(KEY, JSON.stringify({ referrer: ref }))
    }
    // remember which page captured the touch (first touch wins for landing_page)
    const cur = read()
    if (!cur.landing_page) {
      cur.landing_page = window.location.pathname
      sessionStorage.setItem(KEY, JSON.stringify(cur))
    }
  }

  function read(): UtmPayload {
    if (!import.meta.client) return {}
    try { return JSON.parse(sessionStorage.getItem(KEY) || '{}') }
    catch { return {} }
  }

  /** UTM payload to attach to a public order intent (empty keys dropped). */
  function payload(): Record<string, string> {
    const utm = read()
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(utm)) if (v) out[k] = String(v)
    return out
  }

  return { capture, read, payload }
}
