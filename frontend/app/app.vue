<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        ECOS
        <small>LUXEEN COMMERCE OS · BY PLANNEXIS</small>
      </div>
      <nav class="nav">
        <NuxtLink to="/">Command Center</NuxtLink>
        <NuxtLink to="/catalog">Catalog</NuxtLink>
        <NuxtLink to="/crm">CRM · Leads</NuxtLink>
        <NuxtLink to="/orders">Orders</NuxtLink>
        <NuxtLink to="/logistics">Logistics</NuxtLink>
        <NuxtLink to="/finance">Finance · Ledger</NuxtLink>
        <NuxtLink to="/events">Event Stream</NuxtLink>
      </nav>
      <div class="sidebar-foot">
        Corridor: China → Nigeria<br>
        Currencies: CNY · NGN · USD<br>
        Phase 1 build
      </div>
    </aside>
    <main class="content">
      <NuxtPage />
    </main>
  </div>
</template>
