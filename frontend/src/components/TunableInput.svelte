<script>
  // One editable limit or target. Shown in friendly units, stored in the hub's units.
  import { createEventDispatcher } from 'svelte';
  import { settings, command } from '../lib/stores.js';

  export let tunable;
  const dispatch = createEventDispatcher();
  let message = '';

  $: imperial = $settings.display_units === 'imperial';
  $: unit = { temperature: imperial ? '°F' : '°C', humidity: '%', soil_moisture: '%', ph: 'pH', ec: 'mS/cm', ml: 'mL', watts: 'W', money: 'per kWh' }[tunable.kind];
  const round = (v, d) => Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
  function show(v) {
    if (tunable.kind === 'temperature' && imperial) return round((v * 9) / 5 + 32, 1);
    if (tunable.kind === 'ec') return round(v / 1000, 2);
    return round(v, 2);
  }
  function parse(text) {
    const v = Number(text);
    if (tunable.kind === 'temperature' && imperial) return Math.round((((v - 32) * 5) / 9) * 100) / 100;
    if (tunable.kind === 'ec') return v * 1000;
    return v;
  }
  $: step = tunable.kind === 'ph' || tunable.kind === 'ml' ? 0.1 : tunable.kind === 'ec' || tunable.kind === 'money' ? 0.01 : 1;

  async function save(input) {
    const value = parse(input.value);
    if (input.value === '' || isNaN(value) || value < tunable.min || value > tunable.max) {
      message = 'Must be between ' + show(tunable.min) + ' and ' + show(tunable.max) + ' ' + unit + '.';
      input.value = show(tunable.value);
      return;
    }
    message = await command('/api/tunables', { key: tunable.key, value: value }, 'PUT');
    dispatch('changed');
  }
  async function reset() {
    message = await command('/api/tunables?key=' + encodeURIComponent(tunable.key), null, 'DELETE');
    dispatch('changed');
  }
</script>

<div class="row">
  <label for={tunable.key}>{tunable.label}</label>
  <span class="field">
    <input id={tunable.key} type="number" {step} value={show(tunable.value)} on:change={(e) => save(e.target)} />
    <span class="unit">{unit}</span>
    {#if tunable.changed}<button class="quiet" title="Back to {show(tunable.default)} {unit}" on:click={reset}>Reset</button>{/if}
  </span>
</div>
{#if message}<p class="bad">{message}</p>{/if}

<style>
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-top: 1px solid var(--line);
  }
  label {
    margin-right: 10px;
  }
  .field {
    white-space: nowrap;
  }
  input {
    width: 96px;
    min-height: 44px;
    padding: 0 8px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  .unit {
    display: inline-block;
    min-width: 56px;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .quiet {
    min-height: 44px;
    border: 0;
    background: transparent;
    color: var(--muted);
    text-decoration: underline;
    cursor: pointer;
  }
  .bad {
    margin: 0 0 6px;
    color: var(--bad);
    font-size: 0.9rem;
  }
</style>
