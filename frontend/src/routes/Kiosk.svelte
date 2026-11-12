<script>
  // Wall display: big numbers readable from across the room. Always dark, no menus,
  // and dimmer when every tent's lights are off (night).
  import { onMount, onDestroy } from 'svelte';
  import { config, values, alerts, link, settings, now } from '../lib/stores.js';
  import { formatReading, isStale } from '../lib/format.js';

  let clock = '';
  let timer;
  const tick = () => {
    const d = new Date();
    clock = d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
  };
  onMount(() => {
    tick();
    timer = setInterval(tick, 10000);
    // Keep the screen awake where the browser allows it (kiosk apps do this themselves).
    try {
      if (navigator.wakeLock) navigator.wakeLock.request('screen').catch(() => {});
    } catch (err) {
      // not supported: nothing to do
    }
  });
  onDestroy(() => clearInterval(timer));

  const KINDS = ['temperature', 'humidity', 'ph', 'ec'];
  $: tiles = $config.zones
    .filter((z) => !z.parent)
    .map((zone) => ({
      zone,
      sensors: KINDS.map((k) => $config.sensors.find((s) => s.zone === zone.id && s.kind === k)).filter(Boolean),
      lights: $config.devices.find((d) => d.zone === zone.id && d.kind === 'light'),
    }))
    .filter((t) => t.sensors.length);
  $: lightStates = tiles.filter((t) => t.lights).map((t) => ($values[t.lights.node + '/switch/' + t.lights.key] || {}).value);
  $: night = lightStates.length > 0 && lightStates.every((v) => v === false);
  const short = { temperature: 'Temp', humidity: 'Humidity', ph: 'pH', ec: 'EC' };
</script>

<div class="kiosk" class:night>
  <header>
    <span class="clock">{clock}</span>
    <a href="#/">Exit</a>
  </header>

  {#if !$link.ws}
    <div class="strip">Not connected to the hub</div>
  {:else if $alerts.length}
    <div class="strip" class:critical={$alerts[0].severity === 'critical'}>
      {$alerts[0].name} · {$alerts[0].subject}{$alerts.length > 1 ? ' (+' + ($alerts.length - 1) + ' more)' : ''}
    </div>
  {/if}

  <div class="tiles">
    {#each tiles as tile (tile.zone.id)}
      <section>
        <h2>{tile.zone.name}</h2>
        <div class="numbers">
          {#each tile.sensors as sensor (sensor.key)}
            {@const entry = $values[sensor.node + '/sensor/' + sensor.key]}
            {@const shown = formatReading(sensor, entry && !isStale(entry, $now) ? entry.value : null, $settings.display_units)}
            <div class="number">
              <div class="value">{shown.text}<span>{sensor.kind === 'ph' ? '' : shown.unit}</span></div>
              <div class="label">{short[sensor.kind]}</div>
            </div>
          {/each}
        </div>
      </section>
    {/each}
  </div>
</div>

<style>
  .kiosk {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 5;
    overflow-y: auto;
    padding: 16px;
    background: #0b110e;
    color: #e8efe9;
  }
  .kiosk.night {
    opacity: 0.45; /* easy on the eyes when the tents are dark */
  }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .clock {
    font-size: 2.2rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  header a {
    display: inline-block;
    min-height: 44px;
    line-height: 44px;
    padding: 0 14px;
    color: #94a69a;
  }
  .strip {
    margin-bottom: 12px;
    padding: 12px 16px;
    border-radius: 12px;
    background: #b26a00;
    color: #fff;
    font-size: 1.3rem;
    font-weight: 700;
  }
  .strip.critical {
    background: #c0392b;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    grid-gap: 14px;
  }
  section {
    padding: 16px 20px;
    border: 1px solid #2a3a30;
    border-radius: 16px;
    background: #141d18;
  }
  h2 {
    margin: 0 0 6px;
    font-size: 1.3rem;
    color: #94a69a;
  }
  .numbers {
    display: flex;
    flex-wrap: wrap;
  }
  .number {
    margin: 0 28px 6px 0;
  }
  .value {
    font-size: 4rem;
    font-weight: 700;
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
  }
  .value span {
    margin-left: 4px;
    font-size: 1.3rem;
    font-weight: 400;
    color: #94a69a;
  }
  .label {
    color: #94a69a;
    font-size: 1.05rem;
  }
</style>
