import { getContext, setContext, untrack, type Snippet } from 'svelte';
import type { ZoneVisibility } from '../../lib/zone-shell/zone-types';

const FRAME_HEADER = Symbol('frame-header');
export interface StripSlotProps {
  onIconClick: (button: HTMLElement) => void;
  menuOpen: boolean;
  menuLabel: string;
}

export interface FrameHeader {
  content: Snippet | null;
  action: Snippet | null;
  groups: Snippet[];
  strip: Snippet<[StripSlotProps]> | null;
  tools: Snippet | null;
  title: string | null;
  hostId: string;
  takesBars: boolean;
  drawn: boolean;
  suppressed: boolean;
  gridSlot: string | null;
  rowless: symbol | null;
}

export function createFrameHeader(hostId: string, onGrid = false): FrameHeader {
  const header: FrameHeader = $state({
    content: null, action: null, groups: [], strip: null, tools: null, title: null, hostId,
    takesBars: false, drawn: false, suppressed: false, gridSlot: onGrid ? hostId : null, rowless: null,
  });
  return header;
}

export function provideFrameHeader(hostId: string, onGrid = false): FrameHeader {
  const header = createFrameHeader(hostId, onGrid);
  setContext(FRAME_HEADER, header);
  return header;
}

export function adoptFrameHeader(header: FrameHeader): void {
  setContext(FRAME_HEADER, header);
}

interface HandedGroups {
  calls: number;
  entries: { order: number; snippet: Snippet }[];
}

const handedGroups = new WeakMap<FrameHeader, HandedGroups>();

function bookFor(frame: FrameHeader): HandedGroups {
  let book = handedGroups.get(frame);
  if (!book) {
    book = { calls: 0, entries: [] };
    handedGroups.set(frame, book);
  }
  return book;
}

function writeGroups(frame: FrameHeader, book: HandedGroups): void {
  frame.groups = [...book.entries].sort((a, b) => a.order - b.order).map((entry) => entry.snippet);
}

export interface HeaderGroupPlace {
  readonly up: boolean;
}

export function useHeaderGroup(group: () => Snippet | null, keepInBody = false): HeaderGroupPlace {
  const frame = useFrameHeader();
  const book = frame ? bookFor(frame) : null;
  const order = book ? book.calls++ : 0;
  const snippet = $derived(frame?.takesBars ? group() : null);
  $effect(() => {
    const handed = snippet;
    if (!frame || !book || !handed) return;
    const entry = { order, snippet: handed };
    untrack(() => {
      book.entries = [...book.entries, entry];
      writeGroups(frame, book);
    });
    return () => {
      untrack(() => {
        book.entries = book.entries.filter((one) => one !== entry);
        writeGroups(frame, book);
      });
    };
  });
  return {
    get up() {
      return snippet !== null || (!keepInBody && !!frame?.suppressed);
    },
  };
}

export function useFrameHeader(): FrameHeader | undefined {
  return getContext<FrameHeader | undefined>(FRAME_HEADER);
}

export interface FramedTitle {
  readonly on: boolean;
}

export function framedTitle(): FramedTitle {
  const frame = getContext<FrameHeader | undefined>(FRAME_HEADER);
  return {
    get on() {
      return !!frame?.drawn || !!frame?.suppressed;
    },
  };
}

const TITLELESS_HOST = Symbol('titleless-host');

export function provideTitlelessHost(): void {
  setContext(TITLELESS_HOST, true);
}

export function titlelessHost(): boolean {
  return getContext<boolean | undefined>(TITLELESS_HOST) === true;
}

const TAB_PANE = Symbol('tab-pane');

/*  hidden  */
export interface TabPane {
  readonly active: boolean;
  readonly visible: ZoneVisibility;
}

export function provideTabPane(pane: TabPane): void {
  setContext(TAB_PANE, pane);
}

export function useTabPane(): TabPane | undefined {
  return getContext<TabPane | undefined>(TAB_PANE);
}

const titleOwners = new WeakMap<FrameHeader, symbol>();

export function claimFrameTitle(header: FrameHeader, title: string | null): () => void {
  const mine = Symbol('frame-title');
  titleOwners.set(header, mine);
  header.title = title;
  return () => {
    if (titleOwners.get(header) !== mine) return;
    titleOwners.delete(header);
    header.title = null;
  };
}
