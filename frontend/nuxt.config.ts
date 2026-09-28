// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },

  // Proxy /api requests to the FastAPI backend during development,
  // so the frontend can call /api/... without CORS headaches.
  nitro: {
    devProxy: {
      '/api': {
        target: 'http://localhost:8000/api',
        changeOrigin: true,
      },
    },
  },

  app: {
    head: {
      title: 'App',
      meta: [{ name: 'description', content: 'Nuxt + FastAPI + SQLAlchemy' }],
    },
  },
})
