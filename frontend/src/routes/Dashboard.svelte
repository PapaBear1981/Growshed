<script>
  import { onMount } from 'svelte';
  import { config, values, command } from '../lib/stores.js';
  import { isDiagnostic } from '../lib/format.js';
  import ZoneCard from '../components/ZoneCard.svelte';
  import DiscoveredCard from '../components/DiscoveredCard.svelte';

  $: topLevel = $config.zones.filter((z) => !z.parent);

  // Maintenance jobs that are due sit at the top until someone ticks them off.
  let due = [];
  async function loadReminders() {
    try {
      due = (await (await fetch('/api/reminders')).json()).filter((r) => r.overdue);
    } catch (err) {
      due = [];
    }
  }
  async function done(id) {
    await command('/api/reminders/' + id + '/done');
    loadReminders();
  }
  onMount(loadReminders);

  // Auto-discovery: anything a board publishes that config.yaml does not mention yet.
  $: configured = new Set(
    $config.sensors
      .map((s) => s.node + '/' + s.component + '/' + s.key)
      .concat($config.devices.map((d) => d.node + '/switch/' + d.key))
  );
  $: discovered = (() => {
    const byNode = {};
    Object.keys($values).forEach((key) => {
      const parts = key.split('/');
      if (configured.has(key) || isDiagnostic(parts[2])) return;
      (byNode[parts[0]] = byNode[parts[0]] || []).push({ key, component: parts[1], entity: parts[2] });
    });
    return Object.keys(byNode)
      .sort()
      .map((id) => ({ id, entities: byNode[id].sort((a, b) => (a.key < b.key ? -1 : 1)) }));
  })();
</script>

{#if due.length}
  <section class="due">
    <b>To do</b>
    {#each due as r (r.id)}
      <div class="job"><span>{r.name}</span><button on:click={() => done(r.id)}>Done</button></div>
    {/each}
  </section>
{/if}

<div class="grid">
  {#each topLevel as zone (zone.id)}
    <ZoneCard {zone} />
  {/each}
  {#each discovered as found (found.id)}
    <DiscoveredCard nodeId={found.id} entities={found.entities} />
  {/each}
</div>

<style>
  .due {
    max-width: 620px;
    margin-bottom: 16px;
    padding: 12px 16px;
    border: 1px solid var(--warn);
    border-radius: 14px;
    background: var(--warn-bg);
  }
  .job {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 0;
  }
  .job button {
    min-height: 44px;
    padding: 0 16px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    font-weight: 600;
    cursor: pointer;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    grid-gap: 16px;
    align-items: start;
  }
</style>
