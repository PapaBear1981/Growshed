<script>
  import { config, values } from '../lib/stores.js';
  import { isDiagnostic } from '../lib/format.js';
  import ZoneCard from '../components/ZoneCard.svelte';
  import DiscoveredCard from '../components/DiscoveredCard.svelte';

  $: topLevel = $config.zones.filter((z) => !z.parent);

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

<div class="grid">
  {#each topLevel as zone (zone.id)}
    <ZoneCard {zone} />
  {/each}
  {#each discovered as found (found.id)}
    <DiscoveredCard nodeId={found.id} entities={found.entities} />
  {/each}
</div>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    grid-gap: 16px;
    align-items: start;
  }
</style>
