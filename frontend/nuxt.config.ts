// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },

  css: ['~/assets/css/main.css'],

  // Proxy /api requests to the FastAPI backend during development,
  // so the frontend can call /api/... without CORS friction.
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
      title: 'Ecos — Commerce Operating System',
      meta: [
        { name: 'description', content: 'Luxeen\'s global e-commerce operating system, built by Plannexis.' },
      ],
    },
  },
})
