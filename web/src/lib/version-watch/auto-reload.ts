
export const AUTO_RELOAD_SETTLE_MS = 2_000;

export const AUTO_RELOAD_RECHECK_MS = 2_000;

export const AUTO_RELOAD_STORAGE_KEY = 'carnivore.autoReload.lastKey';

export interface AutoReloadDeps {
  reload: () => void;
  atRisk: (hidden: boolean) => boolean;
  isHidden: () => boolean;
  readSpent: () => string;
  writeSpent: (key: string) => boolean;
  listen: (recheck: () => void) => () => void;
  settleMs?: number;
  recheckMs?: number;
}

export interface AutoReloader {
  consider: (key: string | null) => void;
}

export function createAutoReloader(deps: AutoReloadDeps): AutoReloader {
  const settleMs = deps.settleMs ?? AUTO_RELOAD_SETTLE_MS;
  const recheckMs = deps.recheckMs ?? AUTO_RELOAD_RECHECK_MS;
  let pending: string | null = null;
  let settled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let unlisten: (() => void) | null = null;

  function stop(): void {
    pending = null;
    settled = false;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (unlisten) unlisten();
    unlisten = null;
  }

  function attempt(): void {
    if (pending === null || !settled) return;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (deps.atRisk(deps.isHidden())) {
      timer = setTimeout(attempt, recheckMs);
      return;
    }
    const key = pending;
    stop();
    if (deps.writeSpent(key)) deps.reload();
  }

  return {
    consider(key: string | null): void {
      if (key === null || key === '' || key === deps.readSpent()) {
        stop();
        return;
      }
      if (key === pending) return;
      stop();
      pending = key;
      unlisten = deps.listen(attempt);
      timer = setTimeout(() => {
        settled = true;
        attempt();
      }, settleMs);
    },
  };
}

const OPEN_DIALOG = 'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]';

const TEXT_TYPES = new Set(['', 'text', 'search', 'email', 'url', 'tel', 'password', 'number']);

function shown(el: Element): boolean {
  return el.getClientRects().length > 0;
}

export function pageHasRisk(hidden: boolean): boolean {
  const fields = document.querySelectorAll<HTMLElement>('input, textarea, [contenteditable]');
  for (const el of Array.from(fields)) {
    if (el.closest('.xterm') || !shown(el)) continue;
    if (el instanceof HTMLInputElement) {
      if (el.disabled || el.readOnly || !TEXT_TYPES.has(el.type)) continue;
      if (el.value.trim() !== '') return true;
    } else if (el instanceof HTMLTextAreaElement) {
      if (el.disabled || el.readOnly) continue;
      if (el.value.trim() !== '') return true;
    } else if (el.isContentEditable && (el.textContent || '').trim() !== '') {
      return true;
    }
  }
  if (hidden) return false;
  return Array.from(document.querySelectorAll(OPEN_DIALOG)).some(shown);
}

export function browserDeps(): AutoReloadDeps {
  return {
    reload: () => location.reload(),
    atRisk: pageHasRisk,
    isHidden: () => document.visibilityState === 'hidden',
    readSpent: () => {
      try {
        return sessionStorage.getItem(AUTO_RELOAD_STORAGE_KEY) || '';
      } catch {
        return '';
      }
    },
    writeSpent: (key) => {
      try {
        sessionStorage.setItem(AUTO_RELOAD_STORAGE_KEY, key);
        return true;
      } catch {
        return false;
      }
    },
    listen: (recheck) => {
      document.addEventListener('input', recheck, true);
      document.addEventListener('focusout', recheck, true);
      document.addEventListener('visibilitychange', recheck);
      return () => {
        document.removeEventListener('input', recheck, true);
        document.removeEventListener('focusout', recheck, true);
        document.removeEventListener('visibilitychange', recheck);
      };
    },
  };
}
