<script>
  // Grow journal: which plants are where, how old they are, notes and photos.
  import { onMount } from 'svelte';
  import { config, command } from '../lib/stores.js';
  import { formatTime } from '../lib/format.js';

  let plants = [];
  let entries = [];
  let message = '';
  let saving = false;
  const today = () => new Date().toISOString().slice(0, 10);
  let grows = [];
  let plantForm = { name: '', variety: '', zone: '', started: today(), grow_id: '' };
  let entryForm = { plant_id: '', text: '' };
  let fileInput;

  const zoneName = (id) => {
    const zone = $config.zones.find((z) => z.id === id);
    return zone ? zone.name : id;
  };
  const days = (plant) => Math.max(0, Math.floor(((plant.ended_at || Date.now() / 1000) - plant.started_at) / 86400));
  const plantName = (id) => {
    const plant = plants.find((p) => p.id === id);
    return plant ? plant.name : 'General';
  };
  $: growing = plants.filter((p) => !p.ended_at);
  $: finished = plants.filter((p) => p.ended_at);

  async function load() {
    try {
      plants = await (await fetch('/api/plants')).json();
      entries = await (await fetch('/api/journal')).json();
      grows = (await (await fetch('/api/grows')).json()).filter((g) => !g.ended_at);
    } catch (err) {
      // the banner already says the hub is unreachable
    }
  }
  onMount(load);

  async function addPlant() {
    if (!plantForm.name.trim() || !plantForm.zone) {
      message = 'Give the plant a name and say where it is growing.';
      return;
    }
    message = await command('/api/plants', {
      zone: plantForm.zone,
      name: plantForm.name,
      variety: plantForm.variety,
      started_at: new Date(plantForm.started + 'T12:00:00').getTime() / 1000,
      grow_id: plantForm.grow_id === '' ? null : Number(plantForm.grow_id),
    });
    if (!message) {
      plantForm = { name: '', variety: '', zone: plantForm.zone, started: today(), grow_id: plantForm.grow_id };
      load();
    }
  }

  async function finish(plant) {
    await command('/api/plants/' + plant.id, {
      zone: plant.zone, name: plant.name, variety: plant.variety, notes: plant.notes, grow_id: plant.grow_id,
      started_at: plant.started_at, ended_at: Date.now() / 1000,
    }, 'PUT');
    load();
  }

  // Phone photos are several megabytes. Shrink to 1600 px JPEG before sending.
  function shrink(file) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(img.src);
        canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('no image'))), 'image/jpeg', 0.85);
      };
      img.onerror = () => reject(new Error('not an image'));
      img.src = URL.createObjectURL(file);
    });
  }

  async function addEntry() {
    const file = fileInput && fileInput.files[0];
    if (!entryForm.text.trim() && !file) {
      message = 'Write a note or choose a photo.';
      return;
    }
    saving = true;
    message = '';
    try {
      const res = await fetch('/api/journal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plant_id: entryForm.plant_id === '' ? null : Number(entryForm.plant_id), text: entryForm.text }),
      });
      if (!res.ok) throw new Error('save failed');
      const id = (await res.json()).id;
      if (file) {
        // The note is already saved; a photo problem must not look like losing the note.
        try {
          const photo = await fetch('/api/journal/' + id + '/photo', { method: 'PUT', body: await shrink(file) });
          if (!photo.ok) message = 'The note was saved, but the hub could not store the photo.';
        } catch (err) {
          message = 'The note was saved, but that file could not be read as a photo.';
        }
      }
      entryForm.text = '';
      if (fileInput) fileInput.value = '';
    } catch (err) {
      message = 'Could not save the note.';
    }
    saving = false;
    load();
  }

  async function removeEntry(id) {
    await command('/api/journal/' + id, null, 'DELETE');
    load();
  }
</script>

<section class="card">
  <h2>Plants</h2>
  {#if growing.length === 0}<p class="hint">No plants yet. Add the first one below.</p>{/if}
  {#each growing as plant (plant.id)}
    <div class="plant">
      <div>
        <b>{plant.name}</b>{plant.variety ? ' · ' + plant.variety : ''}
        <div class="hint">{zoneName(plant.zone)} · day {days(plant)} · started {formatTime(plant.started_at).split(' ')[0]}</div>
      </div>
      <button class="plain" on:click={() => finish(plant)}>Harvested / removed</button>
    </div>
  {/each}
  {#if finished.length}
    <details>
      <summary>Finished ({finished.length})</summary>
      {#each finished as plant (plant.id)}
        <div class="plant">
          <div><b>{plant.name}</b>{plant.variety ? ' · ' + plant.variety : ''}
            <div class="hint">{zoneName(plant.zone)} · {days(plant)} days</div></div>
        </div>
      {/each}
    </details>
  {/if}

  <h3>Add a plant</h3>
  <div class="form">
    <label>Name <input type="text" maxlength="80" bind:value={plantForm.name} /></label>
    <label>Variety (optional) <input type="text" maxlength="80" bind:value={plantForm.variety} /></label>
    <label>Where
      <select bind:value={plantForm.zone}>
        <option value="">choose…</option>
        {#each $config.zones.filter((z) => z.kind !== 'room') as z (z.id)}<option value={z.id}>{z.name}</option>{/each}
      </select>
    </label>
    <label>Started <input type="date" bind:value={plantForm.started} /></label>
    {#if grows.length}
      <label>Part of grow
        <select bind:value={plantForm.grow_id}>
          <option value="">none</option>
          {#each grows as g (g.id)}<option value={g.id}>{g.name}</option>{/each}
        </select>
      </label>
    {/if}
    <button on:click={addPlant}>Add</button>
  </div>
</section>

<section class="card">
  <h2>Notes and photos</h2>
  <div class="form">
    <label>About
      <select bind:value={entryForm.plant_id}>
        <option value="">General</option>
        {#each growing as plant (plant.id)}<option value={plant.id}>{plant.name}</option>{/each}
      </select>
    </label>
    <label class="wide">Note <textarea rows="2" maxlength="4000" bind:value={entryForm.text}></textarea></label>
    <label>Photo (optional) <input type="file" accept="image/*" bind:this={fileInput} /></label>
    <button disabled={saving} on:click={addEntry}>{saving ? 'Saving…' : 'Save'}</button>
  </div>
  {#if message}<p class="bad-text">{message}</p>{/if}

  {#each entries as entry (entry.id)}
    <article>
      <div class="meta">
        <span>{formatTime(entry.ts)} · <b>{entry.plant_id ? plantName(entry.plant_id) : 'General'}</b></span>
        <button class="quiet" aria-label="Delete this note" on:click={() => removeEntry(entry.id)}>✕</button>
      </div>
      {#if entry.text}<p>{entry.text}</p>{/if}
      {#if entry.photo}<img src={'/api/photos/' + entry.photo} alt="Journal entry from {formatTime(entry.ts)}" loading="lazy" />{/if}
    </article>
  {/each}
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
  .hint {
    color: var(--muted);
    font-size: 0.85rem;
  }
  .plant {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    padding: 10px 0;
    border-top: 1px solid var(--line);
  }
  summary {
    min-height: 44px;
    line-height: 44px;
    cursor: pointer;
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
    flex: 1 1 240px;
  }
  select,
  input,
  textarea {
    display: block;
    width: 160px;
    max-width: 100%;
    min-height: 44px;
    margin-top: 2px;
    padding: 6px 8px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  input[type='file'] {
    width: 220px;
    border: 0;
    padding: 8px 0;
  }
  label.wide textarea {
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
  button.plain {
    border: 1px solid var(--line);
    background: var(--off-bg);
    color: var(--text);
    font-weight: 600;
  }
  button.quiet {
    min-width: 44px;
    padding: 0;
    background: transparent;
    color: var(--muted);
  }
  button:disabled {
    opacity: 0.5;
  }
  .bad-text {
    color: var(--bad);
    margin: 0 0 8px;
  }
  article {
    border-top: 1px solid var(--line);
    padding: 10px 0;
  }
  .meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    color: var(--muted);
    font-size: 0.85rem;
  }
  article p {
    margin: 4px 0 8px;
    white-space: pre-wrap;
  }
  img {
    display: block;
    max-width: 100%;
    max-height: 480px;
    border-radius: 10px;
  }
</style>
