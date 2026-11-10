<script>
  import { onMount } from 'svelte';
  import { config, link, loadConfig, connect } from './lib/stores.js';
  import Dashboard from './routes/Dashboard.svelte';
  import System from './routes/System.svelte';

  // Tiny hash router: two pages do not justify a routing library.
  const pages = [
    { hash: '#/', label: 'Dashboard', component: Dashboard },
    { hash: '#/system', label: 'System', component: System },
  ];
  let hash = location.hash || '#/';
  $: page = pages.find((p) => p.hash === hash) || pages[0];

  onMount(() => {
    loadConfig();
    connect();
    const onHash = () => (hash = location.hash || '#/');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  });
</script>

<header class="bar">
  <span class="brand">Growshed</span>
  <nav>
    {#each pages as p (p.hash)}
      <a href={p.hash} class:active={p === page}>{p.label}</a>
    {/each}
  </nav>
</header>

{#if !$link.ws}
  <div class="banner">Not connected to the hub. Readings are not updating. Retrying…</div>
{:else if !$link.mqtt}
  <div class="banner">The hub has lost its connection to the nodes (MQTT broker). Readings are not updating.</div>
{/if}

<main>
  {#if $config}
    <svelte:component this={page.component} />
  {:else}
    <p class="loading">Loading…</p>
  {/if}
</main>

<style>
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
    background: var(--card);
    border-bottom: 1px solid var(--line);
    position: sticky;
    top: 0;
    z-index: 1;
  }
  .brand {
    font-weight: 700;
    color: var(--accent);
  }
  nav {
    display: flex;
  }
  nav a {
    display: flex;
    align-items: center;
    min-height: 48px;
    padding: 0 14px;
    color: var(--muted);
    text-decoration: none;
    font-weight: 600;
    border-bottom: 3px solid transparent;
  }
  nav a.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .banner {
    background: var(--bad);
    color: #fff;
    padding: 10px 16px;
    font-weight: 600;
  }
  main {
    padding: 16px;
  }
  .loading {
    color: var(--muted);
  }
</style>
