/**
 * Global auth guard (plan §43).
 *
 * Public routes (storefront, landing pages, PDP, login) are open.
 * Everything else (Command Center, catalog, CRM, orders, landing page
 * editor, ...) requires a session token — enforced client-side.
 */
export default defineNuxtRouteMiddleware((to) => {
  if (import.meta.server) return

  const PUBLIC = (path: string) =>
    path === '/'
    || path === '/login'
    || path === '/cart'
    || path.startsWith('/lp')
    || path.startsWith('/products')

  if (PUBLIC(to.path)) return

  useAuth().restore()

  const token = localStorage.getItem('ecos:token')
  if (!token) {
    return navigateTo('/login', { redirectCode: 302 })
  }
})
