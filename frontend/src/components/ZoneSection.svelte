<script>
  // The readings and devices of one zone. Used for a card's own zone and its child zones.
  import { values, nodes, settings, now } from '../lib/stores.js';
  import { formatReading, describeBinary, isStale, nodeDown } from '../lib/format.js';

  export let sensors = [];
  export let devices = [];

  const keyOf = (item, component) => item.node + '/' + component + '/' + item.key;

  $: numeric = sensors.filter((s) => s.component === 'sensor');
  $: binary = sensors.filter((s) => s.component === 'binary_sensor');
</script>

{#if numeric.length}
  <div class="readings">
    {#each numeric as sensor (keyOf(sensor, 'sensor'))}
      {@const entry = $values[keyOf(sensor, 'sensor')]}
      {@const stale = isStale(entry, $now)}
      {@const shown = formatReading(sensor, entry ? entry.value : null, $settings.display_units)}
      <div class="reading" class:stale>
        <div class="label">{sensor.name}</div>
        <div class="value">{shown.text}<span class="unit">{shown.unit}</span></div>
        {#if stale && entry}<div class="note">stale</div>
        {:else if entry && entry.value === null && entry.raw !== undefined && entry.raw !== null}
          <div class="note">not calibrated</div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

{#if binary.length || devices.length}
  <ul class="rows">
    {#each binary as sensor (keyOf(sensor, 'binary_sensor'))}
      {@const entry = $values[keyOf(sensor, 'binary_sensor')]}
      {@const stale = !entry || nodeDown($nodes[sensor.node], $now)}
      {@const shown = describeBinary(sensor.kind, stale ? null : entry.value)}
      <li>
        <span>{sensor.name}</span>
        <span class="chip {shown.tone}">{shown.text}</span>
      </li>
    {/each}
    {#each devices as device (keyOf(device, 'switch'))}
      {@const entry = $values[keyOf(device, 'switch')]}
      {@const stale = !entry || nodeDown($nodes[device.node], $now)}
      {@const on = !stale && entry.value === true}
      <li>
        <span>{device.name}</span>
        <span class="chip" class:on class:off={!stale && !on} class:unknown={stale}>
          {stale || entry.value === null ? 'No data' : on ? 'ON' : 'OFF'}
        </span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .readings {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    grid-gap: 12px;
    margin-bottom: 12px;
  }
  .label {
    font-size: 0.8rem;
    color: var(--muted);
  }
  .value {
    font-size: 1.9rem;
    font-weight: 600;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
  }
  .unit {
    font-size: 0.95rem;
    font-weight: 400;
    color: var(--muted);
    margin-left: 2px;
  }
  .stale .value {
    opacity: 0.4;
  }
  .note {
    font-size: 0.75rem;
    color: var(--warn);
  }
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 0;
    border-top: 1px solid var(--line);
    font-size: 0.95rem;
  }
  .chip {
    min-width: 64px;
    text-align: center;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--off-bg);
    color: var(--muted);
  }
  .chip.good,
  .chip.on {
    background: var(--on-bg);
    color: var(--good);
  }
  .chip.bad {
    background: var(--bad);
    color: #fff;
  }
  .chip.unknown {
    color: var(--warn);
  }
</style>
