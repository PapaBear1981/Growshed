<script>
  import { config } from '../lib/stores.js';
  import ZoneCard from '../components/ZoneCard.svelte';

  $: topLevel = $config.zones.filter((z) => !z.parent);
</script>

<div class="grid">
  {#each topLevel as zone (zone.id)}
    <ZoneCard {zone} />
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
