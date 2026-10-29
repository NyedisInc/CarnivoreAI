/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { inputFocus } from '../../lib/input-focus.svelte';
import { flushSync, mount, unmount } from 'svelte';

const opened: Array<{
  sessionId: string;
  destroyed: number;
  started: number;
  interactive: boolean;
  sent: string[];
}> = [];

vi.mock('../../lib/viewer-socket', () => ({
  createViewerSocket: (options: { sessionId: string; interactive?: boolean }) => {
    const record = {
      sessionId: options.sessionId,
      destroyed: 0,
      started: 0,
      interactive: options.interactive === true,
      sent: [] as string[],
    };
    opened.push(record);
    return {
      state: 'connecting',
      interactive: record.interactive,
      start: () => {
        record.started += 1;
      },
      claimInput: () => ({ session: record.sessionId, connection: 1 }),
      send: (data: string, ticket: { session: string }) => {
        if (ticket.session !== record.sessionId) return false;
        record.sent.push(data);
        return true;
      },
      destroy: () => {
        record.destroyed += 1;
      },
    };
  },
}));

const MOTION_REPORT = '\x1b[<35;10;5M';
const PRESS_REPORT = '\x1b[<0;10;5M';
const FOCUS_IN_REPORT = '\x1b[I';
const FOCUS_OUT_REPORT = '\x1b[O';

const terminals: Array<{
  opens: number;
  disposed: number;
  dataHandlers: number;
  dataDisposed: number;
  fire: ((data: string) => void) | null;
  write: ((data: string) => void) | null;
  element: HTMLElement | null;
}> = [];

import Cell from './Cell.svelte';
import { TERMINAL_META, metaFor } from '../../engine/meta';
import {
  letterbox,
  MAX_VIEWER_SCALE,
  rowFor,
  showsReadOnlyNotice,
  VIEWER_ACCEPTS_INPUT,
  VIEWER_KEYS,
} from './meta';
import type { SessionInfo } from '../../api';

function rowOf(id: string, label: string): SessionInfo {
  return {
    session: { id },
    label,
    tmux_session: id,
    activity_status: 'idle',
    startup_gate: null,
    unread: false,
  } as unknown as SessionInfo;
}

const ROWS = [rowOf('ses_7', 'api'), rowOf('ses_8', 'web')];

beforeEach(() => {
  opened.length = 0;
  terminals.length = 0;
  (globalThis as Record<string, unknown>).Terminal = class {
    private entry = {
      opens: 0,
      disposed: 0,
      dataHandlers: 0,
      dataDisposed: 0,
      fire: null as ((data: string) => void) | null,
      write: null as ((data: string) => void) | null,
      element: null as HTMLElement | null,
    };
    private anyMotion = false;
    private sgr = false;
    private sendFocus = false;
    private textarea: HTMLTextAreaElement | null = null;

    constructor() {
      this.entry.write = (data: string) => this.write(data);
      terminals.push(this.entry);
    }

    private emit(data: string): void {
      this.entry.fire?.(data);
    }

    open(host: HTMLElement): void {
      this.entry.opens += 1;
      const element = document.createElement('div');
      element.className = 'xterm';
      const textarea = document.createElement('textarea');
      element.appendChild(textarea);
      host.appendChild(element);
      this.entry.element = element;
      this.textarea = textarea;

      element.addEventListener('mousemove', () => {
        if (this.anyMotion && this.sgr) this.emit(MOTION_REPORT);
      });
      element.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        this.focus();
        if (this.anyMotion && this.sgr) this.emit(PRESS_REPORT);
      });
      textarea.addEventListener('focus', () => {
        if (this.sendFocus) this.emit(FOCUS_IN_REPORT);
      });
      textarea.addEventListener('blur', () => {
        if (this.sendFocus) this.emit(FOCUS_OUT_REPORT);
      });
    }

    focus(): void {
      this.textarea?.focus({ preventScroll: true });
    }

    resize(): void {}

    write(data: Uint8Array | string): void {
      const text = typeof data === 'string' ? data : String(data);
      if (text.includes('[?1003h')) this.anyMotion = true;
      if (text.includes('[?1003l')) this.anyMotion = false;
      if (text.includes('[?1006h')) this.sgr = true;
      if (text.includes('[?1004h')) this.sendFocus = true;
      if (text.includes('[?1004l')) this.sendFocus = false;
    }

    onData(handler: (data: string) => void): { dispose(): void } {
      const entry = this.entry;
      entry.dataHandlers += 1;
      entry.fire = handler;
      return {
        dispose(): void {
          entry.dataDisposed += 1;
          entry.fire = null;
        },
      };
    }

    dispose(): void {
      this.entry.disposed += 1;
    }
  };
});

afterEach(() => {
  delete (globalThis as Record<string, unknown>).Terminal;
  const held = inputFocus.owner;
  if (held) inputFocus.release(held);
  const active = document.activeElement;
  if (active instanceof HTMLElement) active.blur();
  document.body.innerHTML = '';
});

function render(opts: {
  height: number; width?: number; rows?: SessionInfo[] | null; id?: string; page?: 'home' | 'terminal';
}) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const instance = `terminal:${opts.id ?? 'ses_7'}`;
  const component = mount(Cell, {
    target,
    props: {
      width: opts.width ?? 600,
      height: opts.height,
      meta: metaFor(instance as never),
      instance,
      ...(opts.page ? { page: opts.page } : {}),
    },
  });
  flushSync();
  return { target, component };
}

/* with a plain */
vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api');
  return {
    ...actual,
    sessions: {
      get data() {
        return CURRENT.rows;
      },
      get status() {
        return CURRENT.status;
      },
    },
    openSession: (...args: unknown[]) => {
      CURRENT.openCalls.push(args);
      return true;
    },
  };
});

const CURRENT: {
  rows: SessionInfo[] | null;
  status: string;
  openCalls: unknown[][];
} = { rows: ROWS, status: 'ok', openCalls: [] };

beforeEach(() => {
  CURRENT.rows = ROWS;
  CURRENT.status = 'ok';
  CURRENT.openCalls = [];
});

describe('the strip step draws a sentence and never an emulator', () => {
  test('below the pane step no xterm is built and no socket is opened', () => {
    const { target, component } = render({ height: 90 });
    expect(terminals.length).toBe(0);
    expect(opened.length).toBe(0);
    expect(target.querySelector('[data-viewer-state="strip"]')?.textContent?.trim()).toBe(
      'too short to show the pane',
    );
    unmount(component);
  });

  test('at the pane step exactly one emulator and one socket exist', () => {
    const { target, component } = render({ height: 400 });
    expect(terminals.length).toBe(1);
    expect(terminals[0]?.opens).toBe(1);
    expect(opened.length).toBe(1);
    expect(opened[0]?.sessionId).toBe('ses_7');
    expect(opened[0]?.started).toBe(1);
    expect(target.querySelector('[data-viewer-state="pane"]')).not.toBe(null);
    unmount(component);
  });
});

describe('teardown releases what the cell opened', () => {
  test('unmount destroys the socket exactly once', () => {
    const { component } = render({ height: 400 });
    expect(opened[0]?.destroyed).toBe(0);
    unmount(component);
    flushSync();
    expect(opened.length).toBe(1);
    expect(opened[0]?.destroyed).toBe(1);
  });
});

describe('the dead state is drawn from the listing, not from the socket', () => {
  test('a session absent from an arrived listing is dead, and names remove', () => {
    CURRENT.rows = [rowOf('ses_8', 'web')];
    const { target, component } = render({ height: 400 });
    const note = target.querySelector('[data-viewer-state="dead"]');
    expect(note).not.toBe(null);
    expect(note?.textContent ?? '').toContain('remove');
    expect(target.querySelector('[data-viewer-state="pane"]')).toBe(null);
    expect(opened.length).toBe(0);
    unmount(component);

    CURRENT.rows = null;
    CURRENT.status = 'loading';
    const second = render({ height: 400 });
    expect(second.target.querySelector('[data-viewer-state="dead"]')).toBe(null);
    unmount(second.component);
  });
});

describe('the one action goes through the host bridge', () => {
  test('pressing it hands the session id and the tmux name over', () => {
    const { target, component } = render({ height: 400 });
    const button = target.querySelector('button.oc-tv-action') as HTMLButtonElement;
    expect(button.textContent?.trim()).toBe('open');
    button.click();
    expect(CURRENT.openCalls).toEqual([['ses_7', 'ses_7']]);
    unmount(component);
  });

  test('on the terminal page the action button does not render at all', () => {
    const { target, component } = render({ height: 400, page: 'terminal' });
    expect(target.querySelector('button.oc-tv-action')).toBe(null);
    unmount(component);
  });
});

describe('the read only notice says only what is true of the cell', () => {
  test('a cell that takes typing prints no notice, and asks for the socket that carries it', () => {
    expect(VIEWER_ACCEPTS_INPUT).toBe(true);
    const { target, component } = render({ height: 400 });
    expect(target.querySelector('[data-viewer-input="none"]')).toBe(null);
    expect(opened.length).toBe(1);
    expect(opened[0]?.interactive).toBe(VIEWER_ACCEPTS_INPUT);
    unmount(component);
  });

  test('the notice is drawn only for a cell that refuses input and is not dead', () => {
    expect(showsReadOnlyNotice(false, false)).toBe(true);
    expect(showsReadOnlyNotice(true, false)).toBe(false);
    expect(showsReadOnlyNotice(false, true)).toBe(false);
    expect(showsReadOnlyNotice(true, true)).toBe(false);
  });

  test('the notice has a string of its own and a place to sit', () => {
    expect(VIEWER_KEYS.readOnly).toBe('opscenter.cell.terminal.viewer.read_only');
    const { target, component } = render({ height: 400 });
    expect(target.querySelector('span.oc-tv-tail button.oc-tv-action')).not.toBe(null);
    unmount(component);
  });
});

describe('the pure parts, with no document involved', () => {
  test('the scale comes from whichever dimension runs out first', () => {
    expect(letterbox(400, 600, 800, 600)).toEqual({ scale: 0.5, left: 0, top: 150 });
    expect(letterbox(1000, 300, 500, 600)).toEqual({ scale: 0.5, left: 375, top: 0 });
    const tight = letterbox(400, 300, 800, 900);
    expect(tight.scale).toBeCloseTo(1 / 3, 10);
    expect(tight.left).toBeCloseTo(200 / 3, 10);
    expect(tight.top).toBe(0);
  });

  test('a pane smaller than the body is magnified, up to the ceiling', () => {
    expect(letterbox(600, 450, 400, 300)).toEqual({ scale: 1.5, left: 0, top: 0 });
    expect(letterbox(1600, 1200, 400, 300)).toEqual({ scale: 2, left: 400, top: 300 });
    expect(letterbox(800, 600, 400, 300)).toEqual({ scale: 2, left: 0, top: 0 });
    expect(MAX_VIEWER_SCALE).toBe(2);
  });

  test('an unmeasured dimension is dropped, never read as no room', () => {
    expect(letterbox(400, 0, 800, 600)).toEqual({ scale: 0.5, left: 0, top: 0 });
    expect(letterbox(0, 300, 800, 600)).toEqual({ scale: 0.5, left: 0, top: 0 });
    expect(letterbox(0, 0, 500, 400)).toEqual({ scale: 1, left: 0, top: 0 });
    expect(letterbox(400, 300, 0, 0)).toEqual({ scale: 1, left: 200, top: 150 });
  });

  test('a row is found by the id on the nested half', () => {
    expect(rowFor(ROWS, 'ses_8')?.label).toBe('web');
    expect(rowFor(ROWS, 'nope')).toBe(null);
    expect(rowFor(null, 'ses_8')).toBe(null);
  });

  test('the record the cell reads its ladders from has both steps', () => {
    expect(TERMINAL_META.heightStates.map((s) => s.name)).toEqual(['strip', 'pane']);
    expect(TERMINAL_META.heightStates[1]?.min).toBe(120);
    expect(TERMINAL_META.widthStates.map((s) => s.name)).toEqual(['narrow', 'wide']);
  });
});

describe('a cell the user can type into, and where those bytes go', () => {
  test('the view is opened as one that accepts input', () => {
    render({ height: 300 });
    expect(opened.length).toBe(1);
    expect(opened[0]?.interactive).toBe(true);
  });

  /* nothing at all */
  test('a keystroke reaches its own cell`s session and no other', () => {
    render({ height: 300, id: 'ses_7' });
    render({ height: 300, id: 'ses_8' });
    expect(opened.map((o) => o.sessionId)).toEqual(['ses_7', 'ses_8']);

    inputFocus.claim('terminal:ses_7');
    terminals[0]?.fire?.('ls\r');
    inputFocus.claim('terminal:ses_8');
    terminals[1]?.fire?.('pwd\r');
    inputFocus.release('terminal:ses_8');

    expect(opened[0]?.sent).toEqual(['ls\r']);
    expect(opened[1]?.sent).toEqual(['pwd\r']);
  });

  test('a cell that does not own input writes nothing', () => {
    render({ height: 300, id: 'ses_7' });
    inputFocus.claim('terminal:ses_other');
    try {
      terminals[0]?.fire?.('rm -rf /\r');
      expect(opened[0]?.sent).toEqual([]);
      inputFocus.claim('terminal:ses_7');
      terminals[0]?.fire?.('ls\r');
      expect(opened[0]?.sent).toEqual(['ls\r']);
    } finally {
      inputFocus.release('terminal:ses_7');
      inputFocus.release('terminal:ses_other');
    }
  });

  test('a keystroke in a cell nobody has focused writes nothing', () => {
    render({ height: 300, id: 'ses_7' });
    expect(inputFocus.owner).toBe(null);
    terminals[0]?.fire?.('rm -rf /\r');
    expect(opened[0]?.sent).toEqual([]);

    inputFocus.claim('terminal:ses_7');
    try {
      terminals[0]?.fire?.('ls\r');
      expect(opened[0]?.sent).toEqual(['ls\r']);
    } finally {
      inputFocus.release('terminal:ses_7');
    }
  });

  /* and the focus ring */
  test('focus entering the pane claims input, and leaving it gives it back', () => {
    const { target } = render({ height: 300, id: 'ses_7' });
    const body = target.querySelector('[data-viewer-state="pane"]') as HTMLElement;
    const inner = target.querySelector('.xterm') as HTMLElement;
    expect(body).toBeTruthy();
    expect(inner).toBeTruthy();
    expect(inputFocus.owner).toBe(null);

    inner.dispatchEvent(new FocusEvent('focus', { bubbles: false }));
    flushSync();
    expect(inputFocus.owner).toBe('terminal:ses_7');
    inputFocus.release('terminal:ses_7');
    expect(inputFocus.owner).toBe(null);

    body.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    flushSync();
    expect(inputFocus.owner).toBe('terminal:ses_7');
    expect(body.getAttribute('data-input-owner')).toBe('true');

    body.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
    flushSync();
    expect(inputFocus.owner).toBe(null);
    expect(body.getAttribute('data-input-owner')).toBe(null);
  });

  test('the keystroke handler is attached once and released on unmount', () => {
    const { component } = render({ height: 300 });
    expect(terminals[0]?.dataHandlers).toBe(1);
    expect(terminals[0]?.dataDisposed).toBe(0);
    unmount(component);
    flushSync();
    expect(terminals[0]?.dataDisposed).toBe(1);
  });
});

describe('the pointer over a cell nobody has focused, and the click that focuses one', () => {
  test('a pointer swept across an unfocused cell sends nothing', () => {
    render({ height: 300, id: 'ses_7' });
    terminals[0]?.write?.('\x1b[?1003h\x1b[?1006h');
    const xterm = terminals[0]?.element as HTMLElement;
    expect(xterm).toBeTruthy();
    expect(inputFocus.owner).toBe(null);

    for (let i = 0; i < 3; i += 1) {
      xterm.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    }
    expect(opened[0]?.sent).toEqual([]);

    inputFocus.claim('terminal:ses_7');
    try {
      xterm.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
      expect(opened[0]?.sent).toEqual([MOTION_REPORT]);
    } finally {
      inputFocus.release('terminal:ses_7');
    }
  });

  test('a click on an unfocused cell sends the focus report before the press', () => {
    render({ height: 300, id: 'ses_7' });
    terminals[0]?.write?.('\x1b[?1003h\x1b[?1006h\x1b[?1004h');
    const xterm = terminals[0]?.element as HTMLElement;
    expect(inputFocus.owner).toBe(null);

    xterm.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    flushSync();

    expect(inputFocus.owner).toBe('terminal:ses_7');
    expect(opened[0]?.sent).toEqual([FOCUS_IN_REPORT, PRESS_REPORT]);
  });

  test('clicking from one cell into another keeps both focus reports', () => {
    render({ height: 300, id: 'ses_7' });
    render({ height: 300, id: 'ses_8' });
    terminals[0]?.write?.('\x1b[?1004h');
    terminals[1]?.write?.('\x1b[?1004h');
    const first = terminals[0]?.element as HTMLElement;
    const second = terminals[1]?.element as HTMLElement;

    first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    flushSync();
    expect(inputFocus.owner).toBe('terminal:ses_7');
    expect(opened[0]?.sent).toEqual([FOCUS_IN_REPORT]);

    second.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    flushSync();
    expect(inputFocus.owner).toBe('terminal:ses_8');
    expect(opened[0]?.sent).toEqual([FOCUS_IN_REPORT, FOCUS_OUT_REPORT]);
    expect(opened[1]?.sent).toEqual([FOCUS_IN_REPORT]);
  });
});

describe('a mouse wheel over the pane scrolls this cell, and never types into the session', () => {
  test('a capture-phase, non-passive wheel listener is registered on the stage', () => {
    const addSpy = vi.spyOn(HTMLElement.prototype, 'addEventListener');
    const { target, component } = render({ height: 400 });

    const wheelAdds = addSpy.mock.calls.filter(
      (call) =>
        call[0] === 'wheel' &&
        typeof call[2] === 'object' &&
        call[2] !== null &&
        (call[2] as AddEventListenerOptions).capture === true,
    );
    expect(wheelAdds.length).toBe(1);
    expect((wheelAdds[0]?.[2] as AddEventListenerOptions).passive).toBe(false);

    unmount(component);
    addSpy.mockRestore();
  });

  test('the listener is removed on unmount', () => {
    const removeSpy = vi.spyOn(HTMLElement.prototype, 'removeEventListener');
    const { component } = render({ height: 400 });
    unmount(component);

    const wheelRemoves = removeSpy.mock.calls.filter(
      (call) =>
        call[0] === 'wheel' &&
        typeof call[2] === 'object' &&
        call[2] !== null &&
        (call[2] as AddEventListenerOptions).capture === true,
    );
    expect(wheelRemoves.length).toBe(1);
    removeSpy.mockRestore();
  });

  test('the gesture is prevented and never bubbles past the stage', () => {
    const { target, component } = render({ height: 400 });
    const stage = target.querySelector('.oc-tv-stage') as HTMLElement;
    expect(stage).toBeTruthy();

    let bubbled = false;
    target.addEventListener('wheel', () => {
      bubbled = true;
    });

    const ev = new WheelEvent('wheel', { deltaY: 120, cancelable: true, bubbles: true });
    stage.dispatchEvent(ev);

    expect(ev.defaultPrevented).toBe(true);
    expect(bubbled).toBe(false);
    unmount(component);
  });
});
