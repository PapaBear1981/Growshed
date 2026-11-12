// Light / dark choice, remembered on this device only (the wall tablet and a phone can
// differ). "auto" follows the device's own setting.
import { writable } from 'svelte/store';

const KEY = 'growshed-theme';

function read() {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'auto';
  } catch (err) {
    return 'auto'; // storage blocked (private window): just follow the device
  }
}

function apply(choice) {
  const root = document.documentElement;
  if (choice === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

export const theme = writable(read());
apply(read());

export function setTheme(choice) {
  try {
    if (choice === 'auto') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch (err) {
    // not remembered, but still applied for this visit
  }
  apply(choice);
  theme.set(choice);
}
