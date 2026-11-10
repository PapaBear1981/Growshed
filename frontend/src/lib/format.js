// Display formatting. Data is SI everywhere else; conversion happens only here.

export const STALE_AFTER_S = 120;

export function isStale(entry, nowS) {
  return !entry || nowS - entry.ts > STALE_AFTER_S;
}

// -> { text, unit } for a numeric sensor reading.
export function formatReading(sensor, value, displayUnits) {
  if (value === null || value === undefined) return { text: '—', unit: '' };
  if (sensor.kind === 'temperature') {
    if (displayUnits === 'imperial') return { text: ((value * 9) / 5 + 32).toFixed(1), unit: '°F' };
    return { text: value.toFixed(1), unit: '°C' };
  }
  if (sensor.kind === 'humidity') return { text: value.toFixed(0), unit: '%' };
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

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return s + ' s';
  if (s < 3600) return Math.floor(s / 60) + ' min';
  if (s < 86400) return Math.floor(s / 3600) + ' h ' + Math.floor((s % 3600) / 60) + ' min';
  return Math.floor(s / 86400) + ' d ' + Math.floor((s % 86400) / 3600) + ' h';
}
