// Display formatting. Data is SI everywhere else; conversion happens only here.

export const STALE_AFTER_S = 120;

export function isStale(entry, nowS) {
  return !entry || nowS - entry.ts > STALE_AFTER_S;
}

// A node is "down" when it said goodbye (offline) or has gone quiet.
// On/off states (leak, float, relay) are only re-sent when they change, so their age
// says nothing. They are trusted for as long as their node is alive.
export function nodeDown(info, nowS) {
  return !info || info.status === 'offline' || !info.last_seen || nowS - info.last_seen > STALE_AFTER_S;
}

// Entities every node publishes about itself. Not garden readings.
const DIAGNOSTICS = ['mode', 'wifi_rssi', 'uptime', 'heartbeat_age', 'board', 'firmware', 'last_interlock'];

export function isDiagnostic(entity) {
  return DIAGNOSTICS.indexOf(entity) >= 0 || /_source$/.test(entity);
}

// For readings that are not in config.yaml yet: guess a sensible display from the name.
export function formatUnknown(component, entity, value, displayUnits) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
  if (typeof value !== 'number') return String(value);
  const kind = /temp/.test(entity) ? 'temperature' : /(_rh|humid)/.test(entity) ? 'humidity' : '';
  if (kind) {
    const shown = formatReading({ kind: kind, unit: '' }, value, displayUnits);
    return shown.text + ' ' + shown.unit;
  }
  return String(Math.round(value * 100) / 100);
}

// -> { text, unit } for a numeric sensor reading.
export function formatReading(sensor, value, displayUnits) {
  if (value === null || value === undefined) return { text: '—', unit: '' };
  if (sensor.kind === 'temperature') {
    if (displayUnits === 'imperial') return { text: ((value * 9) / 5 + 32).toFixed(1), unit: '°F' };
    return { text: value.toFixed(1), unit: '°C' };
  }
  if (sensor.kind === 'humidity' || sensor.kind === 'soil_moisture') return { text: value.toFixed(0), unit: '%' };
  if (sensor.kind === 'ph') return { text: value.toFixed(1), unit: 'pH' };
  // EC is stored in µS/cm and shown in mS/cm, the unit nutrient charts use.
  if (sensor.kind === 'ec') return { text: (value / 1000).toFixed(2), unit: 'mS/cm' };
  if (sensor.kind === 'illuminance') {
    const text = value >= 1000 ? (value / 1000).toFixed(1) + 'k' : value.toFixed(0);
    return { text, unit: 'lx' };
  }
  return { text: String(value), unit: sensor.unit };
}

// -> { text, tone } where tone is "good" | "bad" | "neutral" | "unknown".
export function describeBinary(kind, value) {
  if (value === null || value === undefined) return { text: 'No data', tone: 'unknown' };
  if (kind === 'leak') return value ? { text: 'WET', tone: 'bad' } : { text: 'Dry', tone: 'good' };
  if (kind === 'level_low') return value ? { text: 'LOW', tone: 'bad' } : { text: 'OK', tone: 'good' };
  if (kind === 'level_high') {
    return value ? { text: 'Full', tone: 'neutral' } : { text: 'Not full', tone: 'neutral' };
  }
  return { text: value ? 'On' : 'Off', tone: 'neutral' };
}

export function formatTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  return d.getMonth() + 1 + '/' + d.getDate() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return s + ' s';
  if (s < 3600) return Math.floor(s / 60) + ' min';
  if (s < 86400) return Math.floor(s / 3600) + ' h ' + Math.floor((s % 3600) / 60) + ' min';
  return Math.floor(s / 86400) + ' d ' + Math.floor((s % 86400) / 3600) + ' h';
}
