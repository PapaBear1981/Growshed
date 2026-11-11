<script>
  import { config, nodes, values, now } from '../lib/stores.js';
  import { nodeDown } from '../lib/format.js';
  import ZoneSection from './ZoneSection.svelte';

  export let zone;

  $: children = $config.zones.filter((z) => z.parent === zone.id);
  $: family = [zone.id].concat(children.map((z) => z.id));
  $: sensorsOf = (id) => $config.sensors.filter((s) => s.zone === id);
  $: devicesOf = (id) => $config.devices.filter((d) => d.zone === id);

  // The card turns red when any problem sensor in it (leak, low level) is active.
  $: alarm = $config.sensors.some((s) => {
    if (family.indexOf(s.zone) < 0 || (s.kind !== 'leak' && s.kind !== 'level_low')) return false;
    const entry = $values[s.node + '/binary_sensor/' + s.key];
    return entry && entry.value === true && !nodeDown($nodes[s.node], $now);
  });

  $: nodeIds = Array.from(
    new Set(
      $config.sensors
        .concat($config.devices)
        .filter((item) => family.indexOf(item.zone) >= 0)
        .map((item) => item.node)
    )
  );
  $: offline = nodeIds.filter((id) => nodeDown($nodes[id], $now));
</script>

<section class="card" class:alarm>
  <header>
    <h2>{zone.name}</h2>
    {#if offline.length}
      <span class="badge">node offline</span>
    {/if}
  </header>
  <ZoneSection sensors={sensorsOf(zone.id)} devices={devicesOf(zone.id)} />
  {#each children as child (child.id)}
    <h3>{child.name}</h3>
    <ZoneSection sensors={sensorsOf(child.id)} devices={devicesOf(child.id)} />
  {/each}
</section>

<style>
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
  }
  .card.alarm {
    border-color: var(--bad);
    box-shadow: 0 0 0 2px var(--bad);
    background: var(--bad-bg);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  h2 {
    margin: 0;
    font-size: 1.1rem;
  }
  h3 {
    margin: 16px 0 10px;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }
  .badge {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--warn);
    color: #fff;
  }
</style>
