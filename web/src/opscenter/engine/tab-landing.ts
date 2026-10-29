import { beginNav, currentNav, keepNav, type NavToken } from '../../lib/launchpad/nav-generation';

interface Armed {
  nav: NavToken;
  ours: NavToken;
  land: (sessionId: string) => void;
}

let armed: Armed | null = null;
let listening = false;

function onCreated(event: Event): void {
  const target = armed;
  const detail = (event as CustomEvent<{ session?: { id?: unknown }; nav?: NavToken }>).detail;
  if (!target || detail?.nav == null || detail.nav !== target.nav) return;
  armed = null;
  const id = typeof detail.session?.id === 'string' ? detail.session.id : '';
  if (!id || !keepNav(target.ours, 'tab landing')) return;
  target.land(id);
}

export async function createAsTab(
  start: () => Promise<void> | null,
  land: (sessionId: string) => void,
): Promise<void> {
  if (!listening && typeof globalThis.addEventListener === 'function') {
    globalThis.addEventListener('session-created', onCreated);
    listening = true;
  }
  const mine: Armed = { nav: null, ours: null, land };
  armed = mine;
  const flow = start();
  if (!flow) {
    armed = null;
    return;
  }
  mine.nav = currentNav();
  mine.ours = beginNav('tab landing');
  if (mine.nav == null || mine.ours == null) {
    armed = null;
  }
  try {
    await flow;
  } finally {
    if (armed === mine) armed = null;
  }
}
