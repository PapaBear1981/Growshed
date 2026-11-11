<script>
  // Water chemistry at a glance, plus the log of what was added by hand.
  import { onMount } from 'svelte';
  import { config, values, settings, calibration, now, command } from '../lib/stores.js';
  import { formatReading, formatTime, isStale } from '../lib/format.js';

  const PRODUCTS = ['pH down', 'pH up', 'Nutrient A', 'Nutrient B', 'Cal-Mag', 'Fresh water'];
  const KINDS = ['ph', 'ec', 'temperature'];

  // Reservoirs = zones that have a pH or EC probe.
  $: reservoirs = $config.zones.filter((z) => $config.sensors.some((s) => s.zone === z.id && (s.kind === 'ph' || s.kind === 'ec')));
  $: sensorsOf = (zone) => KINDS.map((k) => $config.sensors.find((s) => s.zone === zone.id && s.kind === k)).filter(Boolean);

  // The comfortable range for a reading comes from the alert rules in config.yaml.
  function target(sensor, zone, units) {
    const rules = ($config.alerts.rules || []).filter((r) => r.sensor_kind === sensor.kind && (!r.zone_kinds || r.zone_kinds.indexOf(zone.kind) >= 0));
    const low = rules.filter((r) => r.below !== null && r.below !== undefined).map((r) => r.below)[0];
    const high = rules.filter((r) => r.above !== null && r.above !== undefined).map((r) => r.above)[0];
    if (low === undefined || high === undefined) return '';
    return 'target ' + formatReading(sensor, low, units).text + ' to ' + formatReading(sensor, high, units).text;
  }
  function outside(sensor, zone, value) {
    return ($config.alerts.rules || []).some((r) => r.sensor_kind === sensor.kind && (!r.zone_kinds || r.zone_kinds.indexOf(zone.kind) >= 0) && ((r.below != null && value < r.below) || (r.above != null && value > r.above)));
  }

  let doses = [];
  let form = { product: PRODUCTS[0], other: '', amount: '', unit: 'mL', note: '' };
  let message = '';

  async function load() {
    try {
      doses = await (await fetch('/api/doses')).json();
    } catch (err) {
      // the banner already says the hub is unreachable
    }
  }
  onMount(load);

  async function save(zone) {
    const product = form.product === 'Other' ? form.other.trim() : form.product;
    const amount = Number(form.amount);
    if (!product || !(amount > 0)) {
      message = 'Enter what you added and how much.';
      return;
    }
    message = await command('/api/doses', { zone: zone.id, product: product, amount: amount, unit: form.unit, note: form.note });
    if (!message) {
      form.amount = '';
      form.note = '';
      load();
    }
  }
  async function remove(id) {
    await command('/api/doses/' + id, null, 'DELETE');
    load();
  }
</script>

{#if reservoirs.length === 0}
  <p class="hint">No pH or EC probes are set up in config.yaml yet.</p>
{/if}

{#each reservoirs as zone (zone.id)}
  <section class="card">
    <h2>{zone.name}</h2>
    <div class="readings">
      {#each sensorsOf(zone) as sensor (sensor.key)}
        {@const key = sensor.node + '/sensor/' + sensor.key}
        {@const entry = $values[key]}
        {@const stale = isStale(entry, $now)}
        {@const cal = $calibration[key]}
        {@const shown = formatReading(sensor, entry ? entry.value : null, $settings.display_units)}
        <div class="reading" class:stale class:bad={!stale && entry && entry.value !== null && outside(sensor, zone, entry.value)}>
          <div class="label">{sensor.name}</div>
          <div class="value">{shown.text}<span class="unit">{sensor.kind === 'ph' ? '' : shown.unit}</span></div>
          <div class="hint">
            {#if cal && cal.required && !cal.calibrated}not calibrated: see the System page
            {:else if stale}no recent reading
            {:else}{target(sensor, zone, $settings.display_units)}{/if}
          </div>
        </div>
      {/each}
    </div>

    <h3>Log what you added</h3>
    <div class="form">
      <label>What
        <select bind:value={form.product}>
          {#each PRODUCTS as p (p)}<option>{p}</option>{/each}
          <option>Other</option>
        </select>
      </label>
      {#if form.product === 'Other'}
        <label>Name <input type="text" maxlength="60" bind:value={form.other} /></label>
      {/if}
      <label>Amount <input type="number" min="0" step="0.5" bind:value={form.amount} /></label>
      <label>Unit
        <select bind:value={form.unit}><option>mL</option><option>L</option><option>g</option></select>
      </label>
      <label class="wide">Note (optional) <input type="text" maxlength="500" bind:value={form.note} /></label>
      <button on:click={() => save(zone)}>Save</button>
    </div>
    {#if message}<p class="bad-text">{message}</p>{/if}

    <h3>Recent additions</h3>
    {#if doses.filter((d) => d.zone === zone.id).length === 0}
      <p class="hint">Nothing logged yet. Logged additions also appear as markers on the pH and EC charts.</p>
    {:else}
      <table>
        <tbody>
          {#each doses.filter((d) => d.zone === zone.id).slice(0, 30) as d (d.id)}
            <tr>
              <td>{formatTime(d.ts)}</td>
              <td><b>{d.product}</b>{d.note ? ' · ' + d.note : ''}</td>
              <td class="num">{d.amount} {d.unit}</td>
              <td><button class="quiet" aria-label="Delete this entry" on:click={() => remove(d.id)}>✕</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </section>
{/each}

<style>
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 16px;
    max-width: 760px;
  }
  h2 {
    margin: 0 0 10px;
    font-size: 1.1rem;
  }
  h3 {
    margin: 18px 0 8px;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }
  .readings {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    grid-gap: 12px;
  }
  .reading {
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 10px 12px;
  }
  .reading.bad {
    border-color: var(--warn);
    background: var(--warn-bg);
  }
  .label,
  .hint {
    color: var(--muted);
    font-size: 0.85rem;
  }
  .value {
    font-size: 2rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .stale .value {
    opacity: 0.4;
  }
  .unit {
    margin-left: 4px;
    font-size: 0.95rem;
    font-weight: 400;
    color: var(--muted);
  }
  .form {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
  }
  .form > * {
    margin: 0 8px 8px 0;
  }
  label {
    display: block;
    font-size: 0.85rem;
    color: var(--muted);
  }
  label.wide {
    flex: 1 1 200px;
  }
  select,
  input {
    display: block;
    width: 130px;
    min-height: 44px;
    margin-top: 2px;
    padding: 0 8px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  label.wide input {
    width: 100%;
  }
  button {
    min-height: 44px;
    padding: 0 18px;
    border: 0;
    border-radius: 10px;
    background: var(--accent);
    color: var(--bg);
    font-weight: 700;
    cursor: pointer;
  }
  button.quiet {
    min-width: 44px;
    padding: 0;
    background: transparent;
    color: var(--muted);
  }
  .bad-text {
    color: var(--bad);
    margin: 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92rem;
  }
  td {
    padding: 6px 8px 6px 0;
    border-top: 1px solid var(--line);
  }
  .num {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
</style>
