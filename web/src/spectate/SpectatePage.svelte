<script lang="ts">
  import { onDestroy } from 'svelte';

  import CARNIVORE from '../../../client/css/themes/carnivore/theme.json';
  import { t } from '../lib/i18n/index.svelte';
  import { createViewerSocket, type ViewerSocket } from '../opscenter/lib/viewer-socket';
  import { DEFAULT_CHAR_WIDTH_RATIO, MIN_FONT_PX, fitFontSize } from './fit-font';
  import {
    STALL_AFTER_MS,
    createRecordReader,
    deriveViewerKeys,
    newPageStreams,
    parseFragment,
  } from './e2ee';
  import {
    firstConnectRetryDelay,
    isOver,
    relayLinkId,
    spectatorOpener,
    stateForClose,
    type SealedChannel,
    type SpectateState,
  } from './spectate-socket';

  interface Props {
    host: {
      WebSocket: typeof WebSocket;
      location: { protocol: string; host: string; hash: string; pathname?: string };
    };
    deps?: Record<string, unknown>;
  }

  let { host, deps }: Props = $props();

  let stage = $state<HTMLElement | null>(null);

  let scroll = $state(false);

  let phase = $state<SpectateState>('connecting');

  const share = $derived(parseFragment(host.location.hash));
  const token = $derived(share.token);

  let stalled = $state(false);

  const TERM_OPTIONS = {
    theme: CARNIVORE.xterm,
    fontSize: 14,
    fontWeight: 'normal',
    fontWeightBold: 'bold',
    scrollback: 50000,
    disableStdin: true,
    cursorBlink: false,
    cursorStyle: 'bar',
    allowTransparency: false,
  };

  const THEME_STYLE = Object.entries(CARNIVORE.cssVars)
    .map(([name, value]) => `${name}: ${value}`)
    .join('; ');

  let root = $state<HTMLElement | null>(null);

  function monoFace(): string {
    const view = root?.ownerDocument?.defaultView;
    if (!root || !view) return '';
    return view.getComputedStyle(root).getPropertyValue('--font-mono').replace(/\s+/g, ' ').trim();
  }

  let view: ViewerSocket | null = null;
  let gone = false;
  let opened = false;
  let everOpened = false;
  let retries = 0;

  function settle(next: SpectateState): void {
    if (isOver(phase)) return;
    phase = next;
  }

  function finish(next: SpectateState): void {
    if (isOver(phase)) return;
    phase = next;
    const open = view;
    view = null;
    open?.destroy();
  }

  $effect(() => {
    if (!token) {
      finish('missing');
      return;
    }
    const target = stage;
    const Ctor = (globalThis as { Terminal?: new (options: unknown) => unknown }).Terminal;
    if (!target || typeof Ctor !== 'function') return;

    const face = monoFace();
    type Xterm = {
      open(el: HTMLElement): void;
      resize(cols: number, rows: number): void;
      write(data: Uint8Array | string): void;
      dispose(): void;
      options: { fontSize?: number };
      element?: HTMLElement;
    };
    let xterm: Xterm | null = null;
    let cols = 0;
    let ratio = DEFAULT_CHAR_WIDTH_RATIO;

    function drawnWidth(): number {
      const screen = xterm?.element?.querySelector('.xterm-screen') as HTMLElement | null;
      return screen ? screen.getBoundingClientRect().width : 0;
    }

    function refit(): void {
      if (!xterm || !target || cols <= 0) return;
      for (let pass = 0; pass < 3; pass += 1) {
        const fit = fitFontSize(target.clientWidth, cols, ratio);
        scroll = fit.scroll;
        if (xterm.options.fontSize !== fit.fontSize) xterm.options.fontSize = fit.fontSize;
        const drawn = drawnWidth();
        if (!(drawn > 0)) return;
        const measured = drawn / (cols * fit.fontSize);
        if (drawn <= target.clientWidth || fit.fontSize <= MIN_FONT_PX || measured === ratio) {
          ratio = measured;
          return;
        }
        ratio = measured;
      }
    }

    const term = {
      resize(nextCols: number, rows: number): void {
        cols = nextCols;
        if (xterm) {
          xterm.resize(nextCols, rows);
        } else {
          const options = { ...TERM_OPTIONS, cols: nextCols, rows };
          xterm = new Ctor!(face ? { ...options, fontFamily: face } : options) as Xterm;
          xterm.open(target!);
        }
        refit();
      },
      write(data: Uint8Array | string): void {
        xterm?.write(data);
      },
      dispose(): void {
        xterm?.dispose();
        xterm = null;
      },
    };

    const onViewport = () => refit();
    globalThis.addEventListener?.('resize', onViewport);
    globalThis.addEventListener?.('orientationchange', onViewport);

    const setTimer =
      (deps?.setTimer as ((fn: () => void, ms: number) => unknown) | undefined) ??
      ((fn: () => void, ms: number) => globalThis.setTimeout(fn, ms));
    const clearTimer =
      (deps?.clearTimer as ((handle: unknown) => void) | undefined) ??
      ((handle: unknown) => globalThis.clearTimeout(handle as number));
    let retryTimer: unknown = null;

    let credential = token;
    let sealed: SealedChannel | undefined;
    let stallTimer: unknown = null;
    let expiryTimer: unknown = null;

    const armStall = (): void => {
      stalled = false;
      if (stallTimer !== null) clearTimer(stallTimer);
      const mine = (stallTimer = setTimer(() => {
        if (stallTimer === mine && !gone && !isOver(phase)) stalled = true;
      }, STALL_AFTER_MS));
    };

    const connect = (): void => {
      view = createViewerSocket({
        sessionId: '',
        term,
        interactive: false,
        onState: (next) => {
          if (next === 'live') settle('live');
          else if (next === 'connecting') settle('connecting');
          else if (next === 'gone') finish('ended');
          else if (next === 'reconnecting') settle('reconnecting');
        },
        deps: {
          openSocket: spectatorOpener(credential, host, {
            onOpen: () => {
              opened = true;
              everOpened = true;
              if (sealed) armStall();
            },
            onClose: (code) => {
              if (gone) return;
              const verdict = stateForClose(code, opened);
              opened = false;
              if (verdict === 'reconnecting') return;
              const delay = firstConnectRetryDelay(verdict, everOpened, retries);
              if (delay === null) {
                finish(verdict);
                return;
              }
              retries += 1;
              const dead = view;
              view = null;
              dead?.destroy();
              settle('connecting');
              retryTimer = setTimer(() => {
                retryTimer = null;
                if (!gone && !isOver(phase)) connect();
              }, delay);
            },
          }, sealed),
          ...(deps ?? {}),
        } as never,
      });
      view.start();
    };

    if (!share.e2ee) {
      connect();
    } else {
      const subtle =
        (deps?.subtle as SubtleCrypto | undefined) ?? globalThis.crypto?.subtle;
      const linkId = relayLinkId(host.location.pathname);
      const pageStreams = newPageStreams();
      const now = (deps?.now as (() => number) | undefined) ?? (() => Date.now());
      const armExpiry = (atMs: number): void => {
        if (expiryTimer !== null) clearTimer(expiryTimer);
        expiryTimer = setTimer(() => {
          if (!gone && now() >= atMs) finish('ended');
        }, Math.max(0, atMs - now()));
      };
      if (!subtle || !linkId) {
        finish('refused');
      } else {
        void deriveViewerKeys(token, linkId, subtle).then(
          (keys) => {
            if (gone || isOver(phase)) return;
            if (!keys) {
              finish('refused');
              return;
            }
            credential = keys.watchAuth;
            sealed = (sink) =>
              createRecordReader({
                linkId,
                contentKey: keys.contentKey,
                subtle,
                page: pageStreams,
                now,
                events: {
                  grid: sink.grid,
                  bytes: sink.bytes,
                  record: armStall,
                  expiry: armExpiry,
                  end: () => finish('ended'),
                  integrity: () => finish('integrity'),
                },
              });
            connect();
          },
          () => finish('refused'),
        );
      }
    }

    return () => {
      gone = true;
      if (retryTimer !== null) clearTimer(retryTimer);
      if (stallTimer !== null) clearTimer(stallTimer);
      if (expiryTimer !== null) clearTimer(expiryTimer);
      globalThis.removeEventListener?.('resize', onViewport);
      globalThis.removeEventListener?.('orientationchange', onViewport);
      view?.destroy();
      view = null;
    };
  });

  onDestroy(() => {
    gone = true;
  });

  const over = $derived(isOver(phase));

  const notice = $derived(
    phase === 'missing'
      ? t('spectate.notice.missing')
      : phase === 'refused'
        ? t('spectate.notice.refused')
        : phase === 'integrity'
          ? t('spectate.notice.integrity')
        : phase === 'ended'
          ? t('spectate.notice.ended')
          : phase === 'reconnecting'
            ? t('spectate.notice.reconnecting')
            : phase === 'connecting'
              ? t('spectate.notice.connecting')
              : '',
  );
</script>

<div class="spectate" data-session-theme={CARNIVORE.id} style={THEME_STYLE} bind:this={root}>
  <header class="spectate-bar">
    <img
      class="spectate-wordmark"
      src="/static/img/carnivore/carnivore-wordmark.png"
      srcset="/static/img/carnivore/carnivore-wordmark@2x.png 2x"
      alt={t('opscenter.brand.wordmark_alt')}
    />
    <span class="spectate-title">{t('spectate.title')}</span>
    <span class="spectate-bar-end">
      
      <span class="spectate-state" data-spectate-state={phase}>
        <span class="spectate-dot" aria-hidden="true"></span>
        {#if notice && !over}
          <span class="spectate-notice" role="status" data-spectate-state={phase}>{notice}</span>
        {:else if !over && stalled}
          <span data-spectate-stalled>{t('spectate.state.stalled')}</span>
        {:else if !over}
          <span>{t('spectate.state.live')}</span>
        {/if}
      </span>
      <span class="spectate-badge">{t('spectate.read_only')}</span>
    </span>
  </header>

  <div class="spectate-body">
    
    {#if over}
      <p class="spectate-notice spectate-ending" role="status" data-spectate-state={phase}>{notice}</p>
    {:else}
      <div class="spectate-stage xterm-host" class:spectate-stage--scroll={scroll} bind:this={stage}></div>
    {/if}
  </div>

  
  <footer class="spectate-footer">
    {t('spectate.footer_lead')}<a href="https://carnivore.ai/" target="_blank" rel="noopener"
      >{t('spectate.footer_link')}</a
    >
  </footer>
</div>

<style>
  .spectate {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 100vh;
    height: 100dvh;
    z-index: 2000;
    display: flex;
    flex-direction: column;
    padding: 0 env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    box-sizing: border-box;
    background: var(--oc-ground-page);
    color: var(--oc-text-primary);
    font-family: var(--oc-font);
    overflow: hidden;
  }

  .spectate-bar {
    flex: none;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 34px;
    padding: env(safe-area-inset-top) 10px 0;
    box-sizing: content-box;
    background: var(--oc-ground-chrome);
    border-bottom: 1px solid var(--oc-line-chrome);
    font-size: 12px;
    white-space: nowrap;
  }

  .spectate-wordmark {
    display: block;
    height: 28px;
    width: auto;
    flex: none;
  }

  .spectate-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--oc-text-muted);
  }

  .spectate-bar-end {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
  }

  .spectate-state {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--oc-text-secondary);
  }

  .spectate-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--oc-yellow);
  }

  .spectate-state[data-spectate-state='live'] .spectate-dot {
    background: var(--oc-green);
  }

  .spectate-state[data-spectate-state='ended'] .spectate-dot,
  .spectate-state[data-spectate-state='refused'] .spectate-dot,
  .spectate-state[data-spectate-state='integrity'] .spectate-dot,
  .spectate-state[data-spectate-state='missing'] .spectate-dot {
    background: var(--oc-coral);
  }

  .spectate-badge {
    padding: 1px 6px;
    border: 1px solid var(--oc-orange-dim);
    border-radius: 2px;
    background: var(--oc-orange-tint);
    color: var(--oc-orange-bright);
    font-size: 11px;
  }

  .spectate-body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 6px;
  }

  .spectate-footer {
    flex: none;
    padding: 2px 6px 4px;
    text-align: center;
    font-size: 11px;
    color: var(--oc-text-secondary);
  }

  .spectate-footer a {
    color: inherit;
    text-decoration: underline;
  }

  .spectate-ending {
    margin: auto;
    max-width: 36em;
    padding: 0 12px;
    text-align: center;
    font-size: 13px;
    color: var(--oc-text-secondary);
  }

  .spectate-stage {
    flex: 1;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    scrollbar-width: none;
  }

  .spectate-stage--scroll {
    overflow-x: auto;
    scrollbar-width: thin;
  }

  .spectate-stage :global(.xterm-viewport) {
    scrollbar-width: none;
  }

  @media (max-width: 600px) {
    .spectate-bar {
      height: 30px;
      gap: 8px;
      padding-left: 8px;
      padding-right: 8px;
    }

    .spectate-wordmark {
      height: 24px;
    }

    .spectate-body {
      padding: 4px;
    }
  }
</style>
