<script>
  // Readings from a board (or an extra sensor) that config.yaml does not know about yet.
  // They are shown raw so a newly flashed board can be checked before it is configured.
  import { config, nodes, values, settings, now } from '../lib/stores.js';
  import { formatUnknown, nodeDown } from '../lib/format.js';

  export let nodeId;
  export let entities = [];

  $: known = $config.nodes.find((n) => n.id === nodeId);
  $: boardEntry = $values[nodeId + '/text_sensor/board'];
  $: down = nodeDown($nodes[nodeId], $now);
</script>

<section class="card">
  <header>
    <h2>{known ? known.name : nodeId}</h2>
    <span class="badge" class:down>{down ? 'offline' : known ? 'extra readings' : 'new device'}</span>
  </header>
  <p class="hint">
    {#if boardEntry && boardEntry.value}{boardEntry.value}. {/if}
    Found automatically. Not in config.yaml yet, so no zone, alerts or history.
  </p>
  <ul>
    {#each entities as item (item.key)}
      <li>
        <code>{item.component}/{item.entity}</code>
        <span>{formatUnknown(item.component, item.entity, $values[item.key].value, $settings.display_units)}</span>
      </li>
    {/each}
  </ul>
</section>

<style>
  .card {
    background: var(--card);
    border: 2px dashed var(--warn);
    border-radius: 14px;
    padding: 16px;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  h2 {
    margin: 0;
    font-size: 1.1rem;
  }
  .badge {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--warn);
    color: #fff;
  }
  .badge.down {
    background: var(--off-bg);
    color: var(--muted);
  }
  .hint {
    margin: 0 0 10px;
    font-size: 0.85rem;
    color: var(--muted);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 0;
    border-top: 1px solid var(--line);
    font-variant-numeric: tabular-nums;
  }
  code {
    font-size: 0.85rem;
    color: var(--muted);
  }
</style>
