<script>
  import { onMount } from 'svelte';
  import { config, link, alerts, loadConfig, connect, ackAlert } from './lib/stores.js';
  import Dashboard from './routes/Dashboard.svelte';
  import Controls from './routes/Controls.svelte';
  import History from './routes/History.svelte';
  import Water from './routes/Water.svelte';
  import Journal from './routes/Journal.svelte';
  import Alerts from './routes/Alerts.svelte';
  import System from './routes/System.svelte';

  // Tiny hash router: a handful of pages do not justify a routing library.
  const pages = [
    { hash: '#/', label: 'Dashboard', component: Dashboard },
    { hash: '#/controls', label: 'Controls', component: Controls },
    { hash: '#/water', label: 'Water', component: Water },
    { hash: '#/history', label: 'History', component: History },
    { hash: '#/journal', label: 'Journal', component: Journal },
    { hash: '#/alerts', label: 'Alerts', component: Alerts },
    { hash: '#/system', label: 'System', component: System },
  ];
  let hash = location.hash || '#/';
  $: page = pages.find((p) => p.hash === hash) || pages[0];

  // Unacknowledged critical alerts are shown on every page until someone taps Acknowledge.
  $: urgent = $alerts.filter((a) => a.severity === 'critical' && !a.acked_at);
  $: otherCount = $alerts.length - urgent.length;

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
      <a href={p.hash} class:active={p === page}>
        {p.label}{#if p.label === 'Alerts' && $alerts.length}<span class="count">{$alerts.length}</span>{/if}
      </a>
    {/each}
  </nav>
</header>

{#if !$link.ws}
  <div class="banner">Not connected to the hub. Readings are not updating. Retrying…</div>
{:else if !$link.mqtt}
  <div class="banner">The hub has lost its connection to the nodes (MQTT broker). Readings are not updating.</div>
{/if}

{#each urgent as alert (alert.id)}
  <div class="banner urgent">
    <span><b>{alert.name}</b> · {alert.subject}</span>
    <button on:click={() => ackAlert(alert.id)}>Acknowledge</button>
  </div>
{/each}
{#if otherCount && page.label !== 'Alerts'}
  <a class="banner notice" href="#/alerts">{otherCount} active alert{otherCount === 1 ? '' : 's'}. Tap to view.</a>
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
    flex-wrap: wrap;
    padding: 0 8px 0 16px;
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
    flex-wrap: wrap; /* five tabs do not fit on one phone-width row */
    max-width: 100%;
  }
  nav a {
    display: flex;
    align-items: center;
    min-height: 48px;
    padding: 0 10px;
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
  .banner.urgent {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-top: 1px solid rgba(255, 255, 255, 0.35);
  }
  .banner.urgent button {
    min-height: 44px;
    margin-left: 12px;
    padding: 0 16px;
    border: 2px solid #fff;
    border-radius: 10px;
    background: transparent;
    color: #fff;
    font-weight: 700;
    cursor: pointer;
  }
  .banner.notice {
    display: block;
    background: var(--warn-bg);
    color: var(--text);
    text-decoration: none;
    border-bottom: 1px solid var(--line);
  }
  .count {
    margin-left: 6px;
    min-width: 22px;
    padding: 1px 6px;
    border-radius: 999px;
    background: var(--bad);
    color: #fff;
    font-size: 0.75rem;
    text-align: center;
  }
  main {
    padding: 16px;
  }
  .loading {
    color: var(--muted);
  }
</style>
