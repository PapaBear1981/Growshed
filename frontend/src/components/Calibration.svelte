<script>
  // Calibration for every sensor that can use it. The hub captures each point itself,
  // and only once the reading is steady, so this page just asks and waits.
  import { onDestroy } from 'svelte';
  import { config, values, settings, calibration, now, command } from '../lib/stores.js';
  import { formatReading } from '../lib/format.js';

  const GROUPS = [
    { title: 'Water chemistry (pH and EC)', kinds: ['ph', 'ec'], open: true,
      help: 'Cheap probes drift, so redo pH about once a month and EC every three months. Rinse the probe in clean water between solutions.' },
    { title: 'Soil moisture', kinds: ['soil_moisture'], open: true,
      help: 'Once per sensor, before it goes in the pot: first in open air (dry), then standing in a glass of water up to the line (wet).' },
    { title: 'Temperature and humidity (optional fine-tuning)', kinds: ['temperature', 'humidity'], open: false,
      help: 'These work without calibration. If one disagrees with a thermometer or hygrometer you trust, enter the trusted reading. Waterproof probes can use ice water: a glass packed with ice and topped up with water is exactly 32 °F (0 °C).' },
  ];
  const BUFFERS = [4.0, 6.86, 7.0, 9.18, 10.0];

  let busy = {}; // key -> status text while waiting
  let note = {}; // key -> last result text
  let buffer = {}; // key -> selected pH buffer
  let ref = {}; // key -> typed reference value
  let timers = {};

  const zoneName = (id) => $config.zones.find((z) => z.id === id).name;
  const keyOf = (s) => s.node + '/sensor/' + s.key;
  $: sensorsOf = (kinds) => $config.sensors.filter((s) => s.component === 'sensor' && kinds.indexOf(s.kind) >= 0);

  function stop(key) {
    clearTimeout(timers[key]);
    delete timers[key];
    busy[key] = '';
  }
  onDestroy(() => Object.keys(timers).forEach(stop));

  // Ask the hub to capture; keep asking every 4 s until the reading has settled.
  async function capture(key, label, value, started) {
    started = started || Date.now();
    note[key] = '';
    busy[key] = 'Waiting for a steady reading…';
    let res;
    try {
      res = await fetch('/api/calibration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key, label: label, ref: value }),
      });
    } catch (err) {
      stop(key);
      note[key] = 'Could not reach the hub.';
      return;
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      stop(key);
      note[key] = typeof body.detail === 'string' ? body.detail : 'The hub refused that.';
    } else if (body.status === 'saved') {
      stop(key);
      note[key] = 'Saved.';
    } else if (Date.now() - started > 180000) {
      stop(key);
      note[key] = 'The reading never settled. Check the probe and its wiring, then try again.';
    } else {
      busy[key] = 'Waiting: ' + body.reason + '…';
      timers[key] = setTimeout(() => capture(key, label, value, started), 4000);
    }
  }

  function captureRef(sensor, key) {
    let value = Number(ref[key]);
    if (ref[key] === undefined || ref[key] === '' || isNaN(value)) {
      note[key] = 'Enter a value first.';
      return;
    }
    if (sensor.kind === 'temperature' && $settings.display_units === 'imperial') value = ((value - 32) * 5) / 9;
    capture(key, sensor.kind === 'ec' ? 'ec' : 'offset', value);
  }

  async function reset(key) {
    stop(key);
    note[key] = await command('/api/calibration?key=' + encodeURIComponent(key), null, 'DELETE');
  }

  function age(cal) {
    const stamps = Object.keys(cal.points || {}).map((label) => cal.points[label].ts);
    if (!stamps.length || !cal.calibrated) return null;
    return Math.max(0, Math.floor(($now - Math.min.apply(null, stamps)) / 86400));
  }
  const show = (sensor, entry) => {
    if (!entry || entry.value === null || entry.value === undefined) return '—';
    const r = formatReading(sensor, entry.value, $settings.display_units);
    return r.text + ' ' + r.unit;
  };
  // What the sensor itself says, before calibration. Temperatures follow the display units.
  const rawText = (sensor, entry) => {
    if (!entry || entry.raw === null || entry.raw === undefined) return '—';
    if (sensor.kind === 'temperature' || sensor.kind === 'humidity') {
      const r = formatReading(sensor, entry.raw, $settings.display_units);
      return r.text + ' ' + r.unit;
    }
    return entry.raw.toFixed(2) + ' V';
  };
  // Ice-water calibration only makes sense for the waterproof probes.
  const inWater = (sensor) => {
    const zone = $config.zones.find((z) => z.id === sensor.zone);
    return zone && (zone.kind === 'rdwc' || zone.kind === 'tower');
  };
</script>

{#each GROUPS as group (group.title)}
  {#if sensorsOf(group.kinds).length}
    <details class="card" open={group.open}>
      <summary>{group.title}</summary>
      <p class="hint">{group.help}</p>
      {#each sensorsOf(group.kinds) as sensor (keyOf(sensor))}
        {@const key = keyOf(sensor)}
        {@const entry = $values[key]}
        {@const cal = $calibration[key] || { points: {} }}
        {@const days = age(cal)}
        <div class="sensor">
          <div class="head">
            <b>{zoneName(sensor.zone)} · {sensor.name}</b>
            <span class="chip" class:ok={cal.calibrated} class:due={cal.calibrated && cal.max_age_days && days > cal.max_age_days}>
              {#if !cal.calibrated}{cal.required ? 'not calibrated' : 'factory'}
              {:else if cal.max_age_days && days > cal.max_age_days}due ({days} days old)
              {:else}calibrated{days !== null ? ' ' + (days === 0 ? 'today' : days + ' d ago') : ''}{/if}
            </span>
          </div>
          <div class="hint">Sensor reads {rawText(sensor, entry)} · shown as <b>{show(sensor, entry)}</b></div>

          <div class="actions">
            {#if sensor.kind === 'soil_moisture'}
              <button disabled={!!busy[key]} on:click={() => capture(key, 'dry')}>Set dry (in air)</button>
              <button disabled={!!busy[key]} on:click={() => capture(key, 'wet')}>Set wet (in water)</button>
            {:else if sensor.kind === 'ph'}
              <label>Probe is in buffer pH
                <select bind:value={buffer[key]}>
                  <option value={undefined}>choose…</option>
                  {#each BUFFERS as b (b)}<option value={b}>{b.toFixed(2)}</option>{/each}
                </select>
              </label>
              <button disabled={!!busy[key] || buffer[key] === undefined} on:click={() => capture(key, 'ph', buffer[key])}>Capture</button>
            {:else}
              <label>
                {sensor.kind === 'ec' ? 'Solution EC (µS/cm)' : 'Trusted reading (' + (sensor.kind === 'humidity' ? '%' : $settings.display_units === 'imperial' ? '°F' : '°C') + ')'}
                <input type="number" step="0.1" placeholder={sensor.kind === 'ec' ? '1413' : ''} bind:value={ref[key]} />
              </label>
              <button disabled={!!busy[key]} on:click={() => captureRef(sensor, key)}>{sensor.kind === 'ec' ? 'Capture' : 'Match'}</button>
              {#if sensor.kind === 'temperature' && inWater(sensor)}
                <button disabled={!!busy[key]} on:click={() => capture(key, 'offset', 0)}>In ice water</button>
              {/if}
            {/if}
            {#if Object.keys(cal.points || {}).length}
              <button class="quiet" on:click={() => reset(key)}>Reset</button>
            {/if}
          </div>

          {#if sensor.kind === 'ph' && Object.keys(cal.points || {}).length}
            <div class="hint">
              Stored buffers: {Object.keys(cal.points).map((l) => cal.points[l].ref.toFixed(2) + ' (' + cal.points[l].raw.toFixed(2) + ' V)').join(', ')}.
              {Object.keys(cal.points).length < 2 ? 'Capture a second buffer to finish.' : ''}
            </div>
          {/if}
          {#if busy[key]}<div class="busy">{busy[key]} <button class="quiet" on:click={() => stop(key)}>Cancel</button></div>{/if}
          {#if note[key]}<div class="note" class:good={note[key] === 'Saved.'}>{note[key]}</div>{/if}
          {#if cal.warning}<div class="note">{cal.warning}</div>{/if}
        </div>
      {/each}
    </details>
  {/if}
{/each}

<style>
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 16px;
    max-width: 720px;
  }
  summary {
    font-size: 1.1rem;
    font-weight: 700;
    cursor: pointer;
    min-height: 32px;
  }
  .hint {
    margin: 6px 0;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .sensor {
    border-top: 1px solid var(--line);
    padding: 12px 0;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .chip {
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--off-bg);
    white-space: nowrap;
  }
  .chip.ok {
    background: var(--on-bg);
    color: var(--good);
  }
  .chip.due {
    background: var(--warn);
    color: #fff;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    margin-top: 8px;
  }
  .actions > * {
    margin: 0 8px 6px 0;
  }
  label {
    display: block;
    font-size: 0.85rem;
    color: var(--muted);
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
  button {
    min-height: 44px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--off-bg);
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.45;
    cursor: default;
  }
  button.quiet {
    background: transparent;
    color: var(--muted);
    font-weight: 400;
  }
  .busy {
    color: var(--warn);
    font-size: 0.9rem;
  }
  .note {
    color: var(--bad);
    font-size: 0.9rem;
  }
  .note.good {
    color: var(--good);
  }
</style>
