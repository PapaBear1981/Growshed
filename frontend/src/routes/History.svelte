<script>
  // One measure per chart (never two y-axes), one line per sensor, shared time axis.
  import { onMount, onDestroy } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { config, settings } from '../lib/stores.js';

  const MEASURES = [
    { kind: 'temperature', label: 'Temperature' },
    { kind: 'humidity', label: 'Humidity' },
    { kind: 'illuminance', label: 'Light' },
    { kind: 'soil_moisture', label: 'Soil moisture' },
    { kind: 'ph', label: 'pH' },
    { kind: 'ec', label: 'EC' },
  ];
  const RANGES = [
    { hours: 6, label: '6 h' },
    { hours: 24, label: '24 h' },
    { hours: 168, label: '7 d' },
    { hours: 720, label: '30 d' },
  ];

  let kind = 'temperature';
  let hours = 24;
  // A fixed range from the page address (#/history?start=..&end=..), used to look back
  // at a whole grow. Choosing one of the range buttons goes back to "the last N hours".
  function rangeFromAddress() {
    const query = (location.hash.split('?')[1] || '').split('&');
    const get = (name) => Number((query.find((q) => q.indexOf(name + '=') === 0) || '').split('=')[1]);
    const start = get('start');
    const end = get('end');
    return start > 0 && end > start ? { start, end } : null;
  }
  let fixed = rangeFromAddress();
  const onAddress = () => (fixed = rangeFromAddress());
  let range = { start: 0, end: 0 }; // what is currently drawn
  let strips = []; // device on/off timelines under the chart
  let plotBox = { left: 0, width: 0 };
  const DEVICE_KINDS = { temperature: ['light', 'fan', 'heater'], humidity: ['fan', 'light'], illuminance: ['light'], soil_moisture: ['pump'], ph: ['doser'], ec: ['doser'] };
  let host;
  let plot = null;
  let status = 'Loading…';
  let timer;
  let requestId = 0;

  const zoneName = (id) => $config.zones.find((z) => z.id === id).name;
  // Colour is tied to the sensor's position in config.yaml, so it never changes
  // when the range or the data does.
  $: sensors = $config.sensors.filter((s) => s.component === 'sensor' && s.kind === kind);
  // Only offer measures that have sensors in config.yaml.
  $: measures = MEASURES.filter((m) => $config.sensors.some((s) => s.kind === m.kind));
  $: unit = kind === 'temperature' ? ($settings.display_units === 'imperial' ? '°F' : '°C') : kind === 'illuminance' ? 'lx' : kind === 'ph' ? 'pH' : kind === 'ec' ? 'mS/cm' : '%';
  $: decimals = kind === 'illuminance' ? 0 : kind === 'ph' || kind === 'ec' ? 2 : 1;
  $: chemistry = kind === 'ph' || kind === 'ec';
  let doses = []; // manual additions inside the charted range, drawn as markers
  // EC is stored in µS/cm and charted in mS/cm.
  $: convert = kind === 'temperature' && $settings.display_units === 'imperial' ? (v) => (v * 9) / 5 + 32 : kind === 'ec' ? (v) => v / 1000 : (v) => v;

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // A dashed vertical line at each logged addition, so its effect on the curve is visible.
  function drawDoses(u) {
    if (!chemistry || !doses.length) return;
    const ctx = u.ctx;
    ctx.save();
    ctx.strokeStyle = css('--muted');
    ctx.lineWidth = Math.max(1, devicePixelRatio || 1);
    ctx.setLineDash([6, 6]);
    doses.forEach((d) => {
      const x = Math.round(u.valToPos(d.ts, 'x', true));
      if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
      ctx.beginPath();
      ctx.moveTo(x, u.bbox.top);
      ctx.lineTo(x, u.bbox.top + u.bbox.height);
      ctx.stroke();
    });
    ctx.restore();
  }

  function draw(body) {
    const keys = sensors.map((s) => s.node + '/sensor/' + s.key);
    const data = [body.t].concat(
      keys.map((k) => body.series[k].map((v) => (v === null ? null : convert(v))))
    );
    const hasData = data.slice(1).some((col) => col.some((v) => v !== null));
    status = hasData ? '' : kind === 'soil_moisture'
        ? 'No soil history to show. Soil sensors appear here once they are calibrated (System page).'
        : chemistry
        ? 'Nothing to show. pH and EC appear here once the probes are calibrated (System page).'
        : 'No history for this range yet. Readings are saved from the moment the hub starts.';
    if (plot) plot.destroy();
    plot = null;
    if (!hasData || !host) return;
    const axis = { stroke: css('--muted'), grid: { stroke: css('--grid'), width: 1 }, ticks: { show: false } };
    plot = new uPlot(
      {
        width: host.clientWidth,
        height: Math.max(240, Math.min(420, Math.round(window.innerHeight * 0.5))),
        cursor: { points: { size: 9 } },
        hooks: {
          draw: [drawDoses],
          ready: [(u) => (plotBox = { left: u.bbox.left / (devicePixelRatio || 1), width: u.bbox.width / (devicePixelRatio || 1) })],
          setSize: [(u) => (plotBox = { left: u.bbox.left / (devicePixelRatio || 1), width: u.bbox.width / (devicePixelRatio || 1) })],
        },
        scales: { x: { time: true } },
        axes: [axis, Object.assign({ size: 56, values: (u, ticks) => ticks.map((t) => t + ' ' + unit) }, axis)],
        series: [{}].concat(
          sensors.map((s, i) => ({
            label: zoneName(s.zone) + ' · ' + s.name,
            stroke: css('--series-' + ((i % 6) + 1)),
            width: 2,
            spanGaps: false,
            points: { show: false },
            value: (u, v) => (v === null || v === undefined ? '—' : v.toFixed(decimals) + ' ' + unit),
          }))
        ),
      },
      data,
      host
    );
  }

  async function load() {
    if (!sensors.length) {
      status = 'No sensors of this kind are configured.';
      return;
    }
    const mine = ++requestId;
    const end = fixed ? fixed.end : Math.floor(Date.now() / 1000);
    const start = fixed ? fixed.start : end - hours * 3600;
    const keys = sensors.map((s) => s.node + '/sensor/' + s.key).join(',');
    try {
      const res = await fetch('/api/history?keys=' + encodeURIComponent(keys) + '&start=' + start + '&end=' + end);
      if (!res.ok) throw new Error('bad response');
      const body = await res.json();
      doses = [];
      if (chemistry) {
        const zones = sensors.map((s) => s.zone);
        const all = await (await fetch('/api/doses?since=' + start)).json();
        doses = all.filter((d) => zones.indexOf(d.zone) >= 0 && d.ts <= end);
      }
      // Devices that explain this measure (lights and fans for temperature, and so on),
      // in the same zones as the charted sensors or the tents those zones sit in.
      const zoneIds = sensors.map((s) => s.zone);
      const parents = $config.zones.filter((z) => zoneIds.indexOf(z.id) >= 0 && z.parent).map((z) => z.parent);
      const devices = $config.devices.filter((d) => (DEVICE_KINDS[kind] || []).indexOf(d.kind) >= 0 && zoneIds.concat(parents).indexOf(d.zone) >= 0);
      let history = {};
      if (devices.length) {
        const deviceKeys = devices.map((d) => d.node + '/switch/' + d.key).join(',');
        history = await (await fetch('/api/device_history?keys=' + encodeURIComponent(deviceKeys) + '&start=' + start + '&end=' + end)).json();
      }
      if (mine !== requestId) return; // ignore answers to an older selection
      range = { start, end };
      strips = devices
        .map((d) => ({ name: zoneName(d.zone) + ' · ' + d.name, on: history[d.node + '/switch/' + d.key] || [] }))
        .filter((x) => x.on.length);
      draw(body);
    } catch (err) {
      if (mine === requestId) status = 'Could not load history from the hub.';
    }
  }

  const dateText = (ts) => new Date(ts * 1000).toLocaleDateString();
  function pickHours(h) {
    hours = h;
    if (fixed) location.hash = '#/history'; // leave the fixed range
    fixed = null;
  }

  // Reload when the measure, range or units change.
  $: kind, hours, fixed, $settings.display_units, host && load();

  function onResize() {
    if (plot && host) plot.setSize({ width: host.clientWidth, height: plot.height });
  }

  onMount(() => {
    timer = setInterval(load, 60000);
    window.addEventListener('resize', onResize);
  });
  onDestroy(() => {
    clearInterval(timer);
    window.removeEventListener('resize', onResize);
    if (plot) plot.destroy();
  });
</script>

<div class="controls">
  <div class="segmented" role="group" aria-label="Measure">
    {#each measures as m (m.kind)}
      <button class:selected={kind === m.kind} aria-pressed={kind === m.kind} on:click={() => (kind = m.kind)}>{m.label}</button>
    {/each}
  </div>
  <div class="segmented" role="group" aria-label="Time range">
    {#each RANGES as r (r.hours)}
      <button class:selected={!fixed && hours === r.hours} aria-pressed={!fixed && hours === r.hours} on:click={() => pickHours(r.hours)}>{r.label}</button>
    {/each}
  </div>
</div>

<svelte:window on:hashchange={onAddress} />

<section class="card">
  {#if fixed}<p class="status">Showing {dateText(fixed.start)} to {dateText(fixed.end)}. Pick a range above to return to recent readings.</p>{/if}
  {#if status}<p class="status">{status}</p>{/if}
  <div class="chart" bind:this={host}></div>
  {#if strips.length && plot}
    <div class="strips" aria-label="When devices were on">
      {#each strips as strip (strip.name)}
        <div class="strip-name" style="padding-left: {plotBox.left}px">{strip.name}</div>
        <div class="track" style="margin-left: {plotBox.left}px; width: {plotBox.width}px">
          {#each strip.on as span (span[0])}
            <i style="left: {((span[0] - range.start) / (range.end - range.start)) * 100}%; width: {Math.max(0.3, ((span[1] - span[0]) / (range.end - range.start)) * 100)}%"></i>
          {/each}
        </div>
      {/each}
      <p class="hint">Bars show when each device was on.</p>
    </div>
  {/if}
  {#if chemistry && doses.length}
    <p class="hint">Dashed lines mark what you added: {doses.slice(0, 6).map((d) => d.product + ' ' + d.amount + ' ' + d.unit).join(', ')}{doses.length > 6 ? ', …' : ''}.</p>
  {/if}
  <p class="hint">Touch or hover the chart to read values. Tap a name in the legend to hide or show that line.</p>
</section>

<style>
  .controls {
    display: flex;
    flex-wrap: wrap;
    margin: -6px -6px 10px;
  }
  .segmented {
    display: inline-flex;
    margin: 6px;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
    background: var(--card);
  }
  .segmented button {
    min-height: 44px;
    padding: 0 14px;
    border: 0;
    background: transparent;
    font-weight: 600;
    cursor: pointer;
  }
  .segmented button.selected {
    background: var(--accent);
    color: var(--bg);
  }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 12px;
  }
  .status,
  .hint {
    margin: 6px 4px;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .strips {
    margin-top: 6px;
  }
  .strip-name {
    font-size: 0.8rem;
    color: var(--muted);
  }
  .track {
    position: relative;
    height: 10px;
    margin-bottom: 6px;
    border-radius: 3px;
    background: var(--off-bg);
    overflow: hidden;
  }
  .track i {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--accent);
  }
  .chart {
    width: 100%;
    overflow: hidden;
  }
  /* uPlot's legend: readable ink for names and values, colour only on the swatch. */
  .chart :global(.u-legend) {
    text-align: left;
    color: var(--text);
    font-size: 0.85rem;
  }
  .chart :global(.u-legend .u-series) {
    display: inline-block;
    padding: 6px 10px 6px 0;
  }
  .chart :global(.u-legend .u-marker) {
    width: 14px;
    height: 4px;
    border-radius: 2px;
  }
</style>
