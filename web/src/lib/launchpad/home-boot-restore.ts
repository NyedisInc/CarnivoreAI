import { readLastView, restoreLastView } from '../drawer/last-view';
import { legacyGlobal } from '../legacy-globals';
import { SURFACE_MIN_WIDTH_PX } from '../menu-page/menu-page-surface';
import { MENU_PAGE_OPEN_CLASS } from '../menu-page/menu-pages';
import { primarySessionId, primaryTmuxName } from '../../opscenter/api/host';
import { currentNav, keepNav, type NavToken } from './nav-generation';
import { isResolvingDeepLink } from './navigation';

const LIST_COLLECTION = 'list';
const FALLBACK_POLL_MS = 3000;

const ROWS_ID = 'session-sidebar-list';

export const RESTORE_TIMEOUT_MS = 15000;

const PRIMARY_BOUND_EVENT = 'cloude:primary-session-bound';

const HOME_PATH = '/';

export interface BootRestoreDeps {
  screen: () => string | null | undefined;
  wide: () => boolean;
  held: () => boolean;
  nav: () => NavToken;
  keep: (token: NavToken) => boolean;
  restore: () => boolean;
  shownIsRestored: () => boolean;
  whenTerminalUp: (fn: () => void) => () => void;
  showHome: () => void;
  whenHomeLeft: (fn: () => void) => () => void;
  onListing: (fn: () => void) => () => void;
  holdPrimary: (ids: string[]) => void;
  releasePrimary: () => void;
  later: (fn: () => void, ms: number) => () => void;
}

export function isHeld(win: Window = window, resolving: () => boolean = isResolvingDeepLink): boolean {
  return (
    win.location.pathname !== HOME_PATH ||
    win.location.hash !== '' ||
    Boolean(legacyGlobal('DeepLinkTarget')) ||
    Boolean(legacyGlobal('LayoutDeepLinkTarget')) ||
    resolving() ||
    win.document.body.classList.contains(MENU_PAGE_OPEN_CLASS)
  );
}

interface PrimaryHold {
  hold?: (ids: string[]) => void;
  release?: () => void;
}

function liveDeps(): BootRestoreDeps {
  const app = (): { currentScreen?: string | null; showLaunchpad?: () => void } | undefined => legacyGlobal('App');
  const push = (): { pushOrPoll?: (refresh: () => void, ms: number, collections: readonly string[]) => () => void } | undefined => legacyGlobal('ListingPush');
  const hold = (): PrimaryHold | undefined => legacyGlobal<PrimaryHold>('TerminalPrimaryHold');
  return {
    screen: () => app()?.currentScreen,
    wide: () => window.innerWidth >= SURFACE_MIN_WIDTH_PX,
    held: () => isHeld(),
    nav: currentNav,
    keep: (token) => keepNav(token, 'home-boot-restore'),
    restore: () => restoreLastView(),
    shownIsRestored: () => {
      const view = readLastView();
      if (view?.kind !== 'session') return false;
      const id = primarySessionId();
      const name = primaryTmuxName();
      return (view.sessionId !== '' && id === view.sessionId) || (view.tmuxName !== '' && name === view.tmuxName);
    },
    whenTerminalUp: (fn) => {
      const screen = document.getElementById('terminal-screen');
      if (!screen) return () => {};
      const ready = (): boolean =>
        screen.classList.contains('active') &&
        document.querySelector('#terminal-grid > .oc-surface') !== null &&
        (primarySessionId() !== '' || primaryTmuxName() !== '');
      const done = (): void => {
        if (!ready()) return;
        stop();
        fn();
      };
      const observer = new MutationObserver(done);
      observer.observe(screen, { attributes: true, attributeFilter: ['class'] });
      observer.observe(document.getElementById('terminal-grid') ?? screen, { childList: true });
      window.addEventListener(PRIMARY_BOUND_EVENT, done);
      const stop = (): void => {
        observer.disconnect();
        window.removeEventListener(PRIMARY_BOUND_EVENT, done);
      };
      return stop;
    },
    showHome: () => app()?.showLaunchpad?.(),
    whenHomeLeft: (fn) => {
      const home = document.getElementById('launchpad-screen');
      if (!home) return () => {};
      const observer = new MutationObserver(() => {
        if (home.classList.contains('active')) return;
        observer.disconnect();
        fn();
      });
      observer.observe(home, { attributes: true, attributeFilter: ['class'] });
      return () => observer.disconnect();
    },
    onListing: (fn) => {
      const stopPush = push()?.pushOrPoll?.(fn, FALLBACK_POLL_MS, [LIST_COLLECTION]) ?? (() => {});
      const watch = new MutationObserver(fn);
      const list = document.getElementById(ROWS_ID);
      if (list) watch.observe(list, { childList: true, subtree: true });
      const home = document.getElementById('launchpad-screen');
      if (home) watch.observe(home, { attributes: true, attributeFilter: ['class'] });
      return () => {
        stopPush();
        watch.disconnect();
      };
    },
    holdPrimary: (ids) => hold()?.hold?.(ids),
    releasePrimary: () => hold()?.release?.(),
    later: (fn, ms) => {
      const id = window.setTimeout(fn, ms);
      return () => window.clearTimeout(id);
    },
  };
}

export function initHomeBootRestore(deps: BootRestoreDeps = liveDeps()): () => void {
  let stopListing: () => void = () => {};
  let stopWaiting: () => void = () => {};
  let cancelTimer: () => void = () => {};
  let finished = false;
  let holding = false;
  let claimed: NavToken;

  const releaseHold = (): void => {
    if (!holding) return;
    holding = false;
    deps.releasePrimary();
  };

  const finish = (): void => {
    finished = true;
    stopListing();
  };

  const standDown = (): void => {
    finish();
    stopWaiting();
    cancelTimer();
    releaseHold();
  };

  const onTerminalUp = (): void => {
    cancelTimer();
    if (!deps.shownIsRestored()) return standDown();
    cancelTimer = deps.later(() => {
      if (!deps.keep(claimed)) return standDown();
      deps.showHome();
      stopWaiting = deps.whenHomeLeft(releaseHold);
    }, 0);
  };

  const attempt = (): void => {
    if (finished) return;
    const screen = deps.screen();
    if (!screen) return;
    if (screen !== 'launchpad' || !deps.wide() || deps.held()) return finish();
    if (readLastView()?.kind !== 'session') return finish();
    const view = readLastView();
    deps.holdPrimary(view?.kind === 'session' ? [view.sessionId, view.tmuxName] : []);
    holding = true;
    if (!deps.restore()) {
      if (readLastView() === null) standDown();
      else releaseHold();
      return;
    }
    claimed = deps.nav();
    finish();
    stopWaiting = deps.whenTerminalUp(onTerminalUp);
    cancelTimer = deps.later(standDown, RESTORE_TIMEOUT_MS);
  };

  stopListing = deps.onListing(attempt);
  attempt();
  return standDown;
}
