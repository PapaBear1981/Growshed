<script>
  // Everything a person may want to change without editing files on the Pi.
  import { onMount } from 'svelte';
  import { config, settings, saveUnits, command } from '../lib/stores.js';
  import { theme, setTheme } from '../lib/theme.js';
  import { formatTime } from '../lib/format.js';
  import TunableInput from '../components/TunableInput.svelte';

  let tunables = [];
  let profiles = [];
  let applied = {};
  let chosen = {}; // zone -> profile picked in the select
  let prefs = null;
  let reminders = [];
  let energy = null;
  let backups = [];
  let note = {};
  let newReminder = { name: '', every_days: 14 };

  const UNITS = [{ id: 'imperial', label: '°F' }, { id: 'metric', label: '°C' }];
  const THEMES = [{ id: 'auto', label: 'Match device' }, { id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }];
  const json = async (path) => (await fetch(path)).json();

  async function loadTunables() {
    const body = await json('/api/tunables');
    tunables = body.tunables;
    profiles = body.profiles;
    applied = body.applied;
  }
  async function loadAll() {
    try {
      await loadTunables();
      prefs = await json('/api/preferences');
      reminders = await json('/api/reminders');
      backups = await json('/api/backups');
      energy = await json('/api/energy?days=30');
    } catch (err) {
      note.page = 'Could not load the settings from the hub.';
    }
  }
  onMount(loadAll);

  // Zones that have something to tune, parents first so a tent is followed by what is in it.
  $: zoneGroups = $config.zones.filter((z) => tunables.some((t) => t.group === z.id));
  $: electricity = tunables.filter((t) => t.group === 'electricity');
  const canProfile = (zone) => zone.kind === 'tent' || zone.kind === 'rdwc';

  async function applyProfile(zone) {
    if (!chosen[zone.id]) return;
    note[zone.id] = await command('/api/profiles/apply', { zone: zone.id, profile: chosen[zone.id] });
    if (!note[zone.id]) note[zone.id] = 'Applied. You can still change any value below.';
    loadTunables();
  }

  // ---- notification preferences
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  const toClock = (minutes) => pad(Math.floor(minutes / 60)) + ':' + pad(minutes % 60);
  const fromClock = (text) => String(Number(text.split(':')[0]) * 60 + Number(text.split(':')[1]));
  async function setPref(key, value) {
    note.prefs = await command('/api/preferences', { key: key, value: value }, 'PUT');
    prefs = await json('/api/preferences');
  }
  const deviceZone = () => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch (err) {
      return '';
    }
  };

  // ---- reminders
  async function addReminder() {
    if (!newReminder.name.trim()) return;
    note.reminders = await command('/api/reminders', { name: newReminder.name, every_days: Number(newReminder.every_days) });
    newReminder = { name: '', every_days: 14 };
    reminders = await json('/api/reminders');
  }
  async function reminderAction(id, action) {
    await command('/api/reminders/' + id + (action === 'done' ? '/done' : ''), null, action === 'done' ? 'POST' : 'DELETE');
    reminders = await json('/api/reminders');
  }

  // ---- backups
  let backingUp = false;
  async function backupNow() {
    backingUp = true;
    note.backup = await command('/api/backups/run');
    backups = await json('/api/backups');
    backingUp = false;
  }
</script>

{#if note.page}<p class="bad">{note.page}</p>{/if}

<section class="card">
  <h2>Appearance</h2>
  <div class="row">
    <span>Temperature units <span class="hint">(every screen)</span></span>
    <div class="segmented">
      {#each UNITS as u (u.id)}
        <button class:selected={$settings.display_units === u.id} aria-pressed={$settings.display_units === u.id} on:click={() => saveUnits(u.id)}>{u.label}</button>
      {/each}
    </div>
  </div>
  <div class="row">
    <span>Light or dark <span class="hint">(this device only)</span></span>
    <div class="segmented">
      {#each THEMES as t (t.id)}
        <button class:selected={$theme === t.id} aria-pressed={$theme === t.id} on:click={() => setTheme(t.id)}>{t.label}</button>
      {/each}
    </div>
  </div>
  <div class="row">
    <span>Wall display <span class="hint">(big numbers for the tablet)</span></span>
    <a class="button" href="#/kiosk">Open kiosk view</a>
  </div>
</section>

{#if prefs}
  <section class="card">
    <h2>Phone notifications</h2>
    <div class="row">
      <span>Time zone: <b>{prefs.timezone}</b></span>
      {#if deviceZone() && deviceZone() !== prefs.timezone}
        <button class="button" on:click={() => setPref('timezone', deviceZone())}>Use {deviceZone()}</button>
      {/if}
    </div>
    <div class="row">
      <label><input type="checkbox" checked={prefs.summary_enabled === '1'} on:change={(e) => setPref('summary_enabled', e.target.checked ? '1' : '0')} /> Daily summary at</label>
      <input type="time" step="60" value={toClock(Number(prefs.summary_minute))} on:change={(e) => setPref('summary_minute', fromClock(e.target.value))} />
    </div>
    <div class="row">
      <label><input type="checkbox" checked={prefs.quiet_enabled === '1'} on:change={(e) => setPref('quiet_enabled', e.target.checked ? '1' : '0')} /> Quiet hours from</label>
      <span>
        <input type="time" step="60" value={toClock(Number(prefs.quiet_start))} on:change={(e) => setPref('quiet_start', fromClock(e.target.value))} />
        to
        <input type="time" step="60" value={toClock(Number(prefs.quiet_end))} on:change={(e) => setPref('quiet_end', fromClock(e.target.value))} />
      </span>
    </div>
    <p class="hint">During quiet hours, warnings wait and arrive as one message afterwards. Critical alerts such as leaks always come through at once.</p>
    {#if note.prefs}<p class="bad">{note.prefs}</p>{/if}
  </section>
{/if}

<section class="card">
  <h2>Limits and targets</h2>
  <p class="hint">When alerts fire, and what the dosing and watering aim for. A crop profile fills in typical values for one tent or reservoir; you can then adjust any of them. The safety cutoffs on the boards are not here and cannot be changed from this page.</p>
  {#each zoneGroups as zone (zone.id)}
    <h3>{zone.name}{applied[zone.id] ? ' · ' + applied[zone.id] : ''}</h3>
    {#if canProfile(zone)}
      <div class="row">
        <label for={'profile-' + zone.id}>Crop profile</label>
        <span>
          <select id={'profile-' + zone.id} bind:value={chosen[zone.id]}>
            <option value={undefined}>choose…</option>
            {#each profiles as p (p)}<option value={p}>{p}</option>{/each}
          </select>
          <button class="button" disabled={!chosen[zone.id]} on:click={() => applyProfile(zone)}>Apply</button>
        </span>
      </div>
      {#if note[zone.id]}<p class="hint">{note[zone.id]}</p>{/if}
    {/if}
    {#each tunables.filter((t) => t.group === zone.id) as t (t.key)}
      <TunableInput tunable={t} on:changed={loadTunables} />
    {/each}
  {/each}
</section>

<section class="card">
  <h2>Maintenance reminders</h2>
  {#each reminders as r (r.id)}
    <div class="row">
      <span>
        <b>{r.name}</b>
        <span class="hint">every {r.every_days} days · {r.overdue ? 'due now' : 'due in ' + (r.days_left + 1) + ' day' + (r.days_left === 0 ? '' : 's')}</span>
      </span>
      <span>
        <button class="button" on:click={() => reminderAction(r.id, 'done')}>Done</button>
        <button class="quiet" aria-label="Delete this reminder" on:click={() => reminderAction(r.id, 'delete')}>✕</button>
      </span>
    </div>
  {/each}
  <div class="row">
    <span>
      <input type="text" maxlength="120" placeholder="New reminder" aria-label="New reminder name" bind:value={newReminder.name} />
      every <input class="small" type="number" min="1" max="365" aria-label="Days between" bind:value={newReminder.every_days} /> days
    </span>
    <button class="button" on:click={addReminder}>Add</button>
  </div>
  {#if note.reminders}<p class="bad">{note.reminders}</p>{/if}
</section>

<section class="card">
  <h2>Electricity</h2>
  <p class="hint">An estimate: the time each device was switched on, times the wattage you enter here. Read the wattage off the device's label or a plug-in meter.</p>
  {#if energy}
    <p>Last 30 days: <b>{energy.kwh} kWh</b>, about <b>{energy.cost.toFixed(2)}</b> at {energy.price_per_kwh} per kWh.</p>
  {/if}
  {#each electricity as t (t.key)}
    <TunableInput tunable={t} on:changed={loadAll} />
  {/each}
</section>

<section class="card">
  <h2>Backups</h2>
  <p class="hint">The hub saves a copy of its database and settings every night, on the same disk. That protects against mistakes, not against the disk failing: download a full backup now and then and keep it somewhere else.</p>
  <div class="row">
    <span>{backups.length ? 'Latest: ' + formatTime(backups[0].ts) + ' (' + backups.length + ' kept)' : 'No backups yet'}</span>
    <span>
      <button class="button" disabled={backingUp} on:click={backupNow}>{backingUp ? 'Saving…' : 'Back up now'}</button>
      <a class="button primary" href="/api/backups/export" download>Download full backup</a>
    </span>
  </div>
  {#if note.backup}<p class="bad">{note.backup}</p>{/if}
</section>

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
    margin: 0 0 8px;
    font-size: 1.1rem;
  }
  h3 {
    margin: 18px 0 6px;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }
  .hint {
    color: var(--muted);
    font-size: 0.88rem;
  }
  p.hint {
    margin: 4px 0 8px;
  }
  .bad {
    color: var(--bad);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-top: 1px solid var(--line);
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  .segmented button {
    min-width: 64px;
    min-height: 44px;
    padding: 0 12px;
    border: 0;
    background: transparent;
    font-weight: 600;
    cursor: pointer;
  }
  .segmented button.selected {
    background: var(--accent);
    color: var(--bg);
  }
  .button {
    display: inline-block;
    min-height: 44px;
    line-height: 42px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--off-bg);
    color: var(--text);
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
  }
  .button.primary {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--bg);
  }
  .button:disabled {
    opacity: 0.45;
  }
  .quiet {
    min-width: 44px;
    min-height: 44px;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  select,
  input[type='text'],
  input[type='number'],
  input[type='time'] {
    min-height: 44px;
    max-width: 100%;
    padding: 0 8px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  input.small {
    width: 70px;
  }
  input[type='checkbox'] {
    width: 20px;
    height: 20px;
    vertical-align: middle;
  }
</style>
