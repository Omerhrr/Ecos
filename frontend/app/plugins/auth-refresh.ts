/**
 * §43 session continuity — proactive token refresh.
 *
 * Access tokens carry a 12h lease. Instead of letting a session die at an
 * awkward moment, this plugin rotates the token on a 9h cadence while the
 * tab is open (and once shortly after boot), so an active operator never
 * hits the expiry wall. The reactive fallback (one silent refresh + retry
 * on a 401) still exists inside useApi for anything that slips through.
 */
export default defineNuxtPlugin(() => {
  if (!import.meta.client) return

  const REFRESH_INTERVAL_MS = 9 * 60 * 60 * 1000 // 9h (token TTL is 12h)
  let timer: ReturnType<typeof setInterval> | null = null

  function shouldRefresh() {
    const path = window.location.pathname
    const isPublic = path === '/' || path === '/login' || path === '/cart'
      || path === '/track' || path === '/pricing'
      || path.startsWith('/lp') || path.startsWith('/products')
    if (isPublic) return false
    return !!localStorage.getItem('ecos:token')
  }

  async function tick() {
    if (!shouldRefresh()) return
    const { refreshToken } = useApi()
    await refreshToken()
  }

  // first rotation shortly after boot, then on the 9h cadence
  setTimeout(tick, 5_000)
  timer = setInterval(tick, REFRESH_INTERVAL_MS)

  window.addEventListener('pagehide', () => {
    if (timer) clearInterval(timer)
  })
})
