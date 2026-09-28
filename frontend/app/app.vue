<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>App</h1>
      <nav>
        <NuxtLink to="/">Home</NuxtLink>
      </nav>
    </header>
    <main class="app-main">
      <NuxtPage />
    </main>
  </div>
</template>

<style>
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --text: #1a2233;
  --muted: #64748b;
  --accent: #00dc82;
  --border: #e2e8f0;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
}

.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.9rem 1.5rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.app-header h1 {
  font-size: 1.15rem;
  margin: 0;
}

.app-header nav a {
  color: var(--muted);
  text-decoration: none;
  margin-left: 1rem;
  font-weight: 500;
}

.app-header nav a.router-link-active {
  color: var(--text);
}

.app-main {
  flex: 1;
  max-width: 960px;
  width: 100%;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}
</style>
