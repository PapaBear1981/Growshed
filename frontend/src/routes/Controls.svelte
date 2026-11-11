<script>
  // The hub only ever ASKS a node for a mode, a setting or a dose. The node applies its
  // own safety rules first, so what you see here is what the node actually did.
  import { config, values, nodes, settings, control, now, command } from '../lib/stores.js';
  import { nodeDown, formatTime } from '../lib/format.js';

  const DURATIONS = [
    { hours: 1, label: '1 hour' },
    { hours: 4, label: '4 hours' },
    { hours: 12, label: '12 hours' },
    { hours: null, label: 'until I change it' },
  ];
  let hours = 1;
  let message = {}; // key -> last refusal text
  let leakMessage = '';

  $: zones = $config.zones.filter((z) => !z.parent);
  const family = (zone) => [zone].concat($config.zones.filter((z) => z.parent === zone.id));
  const devicesOf = (id, kind) => $config.devices.filter((d) => d.zone === id && d.control === kind);
  const settingsOf = (id) => ($config.settings || []).filter((s) => s.zone === id);
  const hasControls = (z) => devicesOf(z.id, 'mode').length + devicesOf(z.id, 'dose').length + settingsOf(z.id).length > 0;
  const deviceKey = (d) => d.node + '/switch/' + d.key;
  const valueOf = (all, key) => (all[key] ? all[key].value : null);
  const potFor = (list, d) => list.find((p) => p.pump === deviceKey(d));

  const SOURCES = { auto: 'automatic', manual: 'manual', fallback: 'running without the hub', interlock: 'safety cutoff', dosing: 'running', refused: 'last request refused', idle: 'idle' };

  async function send(key, path, body) {
    message[key] = await command(path, body);
  }
  const setMode = (d, mode) => send(deviceKey(d), '/api/control/mode', { key: deviceKey(d), mode: mode, hours: mode === 'auto' ? null : hours });
  const runDose = (d) => send(deviceKey(d), '/api/control/dose', { key: deviceKey(d) });

  // ---- settings: shown in friendly units, sent in the node's units
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  function shown(setting, raw, units) {
    if (raw === null || raw === undefined) return '';
    if (setting.kind === 'time_of_day') return pad(Math.floor(raw / 60)) + ':' + pad(Math.round(raw % 60));
    if (setting.kind === 'temperature' && units === 'imperial') return String(Math.round(((raw * 9) / 5 + 32) * 10) / 10);
    if (setting.kind === 'duration') return String(Math.round(raw / 60));
    return String(raw);
  }
  function unitOf(setting, units) {
    if (setting.kind === 'temperature') return units === 'imperial' ? '°F' : '°C';
    if (setting.kind === 'humidity') return '%';
    if (setting.kind === 'duration') return 'min';
    return '';
  }
  // The limits in the units the person is typing in, for the error message.
  function limits(setting, units) {
    return shown(setting, setting.min, units) + ' and ' + shown(setting, setting.max, units) + ' ' + unitOf(setting, units);
  }
  function saveSetting(setting, input, units) {
    const text = input.value;
    let value;
    if (setting.kind === 'time_of_day') {
      const parts = text.split(':');
      value = Number(parts[0]) * 60 + Number(parts[1]);
    } else if (setting.kind === 'temperature' && units === 'imperial') {
      value = Math.round((((Number(text) - 32) * 5) / 9) * 2) / 2; // nearest 0.5 °C
    } else if (setting.kind === 'duration') {
      value = Number(text) * 60;
    } else {
      value = Number(text);
    }
    const key = setting.node + '/number/' + setting.key;
    if (text === '' || isNaN(value) || value < setting.min || value > setting.max) {
      message[key] = setting.name + ' must be between ' + limits(setting, units) + '.';
      input.value = shown(setting, valueOf($values, key), units); // put the real value back
      return;
    }
    send(key, '/api/control/number', { key: key, value: value });
  }

  async function clearLeak() {
    leakMessage = await command('/api/control/leak/clear');
  }
  const potMode = (pot, mode) => send(pot.sensor, '/api/watering/mode', { key: pot.sensor, mode: mode });
  const potUnlock = (pot) => send(pot.sensor, '/api/watering/unlock', { key: pot.sensor });
</script>

{#if $control.leak_alarm}
  <section class="card alarm">
    <h2>Leak alarm: all water pumps are stopped</h2>
    <p>Find and fix the leak, dry the sensor, then clear the alarm. Air pumps keep running.</p>
    <button class="primary" on:click={clearLeak}>Clear the alarm</button>
    {#if leakMessage}<p class="bad">{leakMessage}</p>{/if}
  </section>
{/if}

<div class="duration">
  <label for="duration">Manual ON / OFF lasts&nbsp;</label>
  <select id="duration" bind:value={hours}>
    {#each DURATIONS as d (d.label)}<option value={d.hours}>{d.label}</option>{/each}
  </select>
  <span class="hint">then the device returns to automatic.</span>
</div>

<div class="grid">
  {#each zones.filter((z) => family(z).some(hasControls)) as zone (zone.id)}
    <section class="card">
      <h2>{zone.name}</h2>
      {#each family(zone).filter(hasControls) as part (part.id)}
        {#if part.id !== zone.id}<h3>{part.name}</h3>{/if}

        {#each devicesOf(part.id, 'mode') as d (d.key)}
          {@const down = nodeDown($nodes[d.node], $now)}
          {@const on = valueOf($values, deviceKey(d))}
          {@const mode = valueOf($values, d.node + '/select/' + d.key + '_mode')}
          {@const source = valueOf($values, d.node + '/text_sensor/' + d.key + '_source')}
          {@const timer = $control.overrides[deviceKey(d)]}
          <div class="row">
            <div class="what">
              <b>{d.name}</b>
              <span class="chip" class:on={!down && on === true} class:cutoff={!down && source === 'interlock'}>
                {down ? 'offline' : on === true ? 'ON' : on === false ? 'OFF' : '—'}
              </span>
              <div class="hint">
                {down ? 'node is offline' : SOURCES[source] || ''}{timer ? ' until ' + formatTime(timer.expires_at) : ''}
              </div>
            </div>
            <div class="segmented">
              {#each ['auto', 'on', 'off'] as m (m)}
                <button disabled={down} class:selected={mode === m} aria-pressed={mode === m} on:click={() => setMode(d, m)}>
                  {m === 'auto' ? 'Auto' : m === 'on' ? 'On' : 'Off'}
                </button>
              {/each}
            </div>
          </div>
          {#if message[deviceKey(d)]}<p class="bad">{message[deviceKey(d)]}</p>{/if}
        {/each}

        {#each devicesOf(part.id, 'dose') as d (d.key)}
          {@const down = nodeDown($nodes[d.node], $now)}
          {@const on = valueOf($values, deviceKey(d))}
          {@const source = valueOf($values, d.node + '/text_sensor/' + d.key + '_source')}
          {@const pot = potFor($control.watering, d)}
          {@const moisture = pot ? valueOf($values, pot.sensor) : null}
          <div class="row">
            <div class="what">
              <b>{pot ? pot.name : d.name}</b>
              <span class="chip" class:on={!down && on === true}>{down ? 'offline' : on === true ? 'RUNNING' : 'idle'}</span>
              <div class="hint">
                {#if pot}
                  soil {moisture === null ? 'not calibrated' : moisture.toFixed(0) + ' %'} · waters below {pot.below} % ·
                  {pot.doses_24h}/{pot.max_doses} doses today{pot.last_dose ? ' · last ' + formatTime(pot.last_dose) : ''}
                {:else}
                  runs for up to {d.dose_s} s{source === 'refused' ? ' · last request refused by the node' : ''}
                {/if}
              </div>
            </div>
            <div class="actions">
              {#if pot}
                <div class="segmented">
                  {#each ['off', 'auto'] as m (m)}
                    <button class:selected={pot.mode === m} aria-pressed={pot.mode === m} on:click={() => potMode(pot, m)}>
                      {m === 'auto' ? 'Auto' : 'Off'}
                    </button>
                  {/each}
                </div>
              {/if}
              <button class="plain" disabled={down} on:click={() => runDose(d)}>{pot ? 'Water now' : 'Fill now'}</button>
            </div>
          </div>
          {#if pot && pot.locked}
            <p class="bad">
              Auto-watering stopped: {pot.locked}.
              <button class="plain" on:click={() => potUnlock(pot)}>Re-enable</button>
            </p>
          {:else if pot && pot.mode === 'auto' && pot.blocked}
            <p class="hint">Not watering right now: {pot.blocked}.</p>
          {/if}
          {#if message[deviceKey(d)]}<p class="bad">{message[deviceKey(d)]}</p>{/if}
          {#if pot && message[pot.sensor]}<p class="bad">{message[pot.sensor]}</p>{/if}
        {/each}

        {#each settingsOf(part.id) as s (s.key)}
          {@const key = s.node + '/number/' + s.key}
          {@const raw = valueOf($values, key)}
          <div class="row setting">
            <label for={key}>{s.name}</label>
            <span>
              <input
                id={key}
                type={s.kind === 'time_of_day' ? 'time' : 'number'}
                step={s.kind === 'time_of_day' ? 60 : s.kind === 'temperature' ? 0.5 : 1}
                value={shown(s, raw, $settings.display_units)}
                on:change={(e) => saveSetting(s, e.target, $settings.display_units)}
              />
              <span class="unit">{unitOf(s, $settings.display_units)}</span>
            </span>
          </div>
          {#if message[key]}<p class="bad">{message[key]}</p>{/if}
        {/each}
      {/each}
    </section>
  {/each}
</div>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    grid-gap: 16px;
    align-items: start;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
  }
  .card.alarm {
    border-color: var(--bad);
    background: var(--bad-bg);
    margin-bottom: 16px;
  }
  h2 {
    margin: 0 0 8px;
    font-size: 1.1rem;
  }
  h3 {
    margin: 16px 0 4px;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }
  .duration {
    margin-bottom: 14px;
  }
  .duration select {
    min-height: 44px;
    max-width: 100%;
    margin: 4px 8px 4px 0;
    padding: 0 10px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    padding: 10px 0;
    border-top: 1px solid var(--line);
  }
  .what {
    margin-right: 10px;
  }
  .hint {
    color: var(--muted);
    font-size: 0.85rem;
  }
  p.hint,
  p.bad {
    margin: 0 0 8px;
  }
  .bad {
    color: var(--bad);
    font-size: 0.9rem;
  }
  .chip {
    margin-left: 6px;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--off-bg);
    color: var(--muted);
  }
  .chip.on {
    background: var(--on-bg);
    color: var(--good);
  }
  .chip.cutoff {
    background: var(--bad);
    color: #fff;
  }
  .actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  .segmented button {
    min-width: 56px;
    min-height: 44px;
    border: 0;
    background: transparent;
    font-weight: 600;
    cursor: pointer;
  }
  .segmented button.selected {
    background: var(--accent);
    color: var(--bg);
  }
  button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  button.plain,
  button.primary {
    min-height: 44px;
    margin-left: 8px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--off-bg);
    font-weight: 600;
    cursor: pointer;
  }
  button.primary {
    margin-left: 0;
    border-color: var(--bad);
    background: var(--bad);
    color: #fff;
  }
  .setting input {
    width: 124px;
    max-width: 100%;
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
    min-width: 28px;
    color: var(--muted);
  }
</style>
