import type { Snippet } from 'svelte';
import type { FrameHeader } from '../../opscenter/shell/frame-header.svelte';
import type { Zone } from './zone.svelte';

function mirror(header: FrameHeader, frame: FrameHeader): void {
  header.drawn = frame.drawn;
  header.suppressed = frame.suppressed;
  header.takesBars = frame.takesBars;
  header.gridSlot = frame.gridSlot;
}

export function seedFrameHeader(frame: FrameHeader | undefined): (header: FrameHeader) => void {
  return (header) => {
    if (frame) mirror(header, frame);
  };
}

export function linkZoneToFrame(zone: Zone, frame: FrameHeader | undefined, toolbar: Snippet): void {
  if (!frame) return;

  $effect(() => {
    for (const tab of zone.tabs) mirror(zone.headerFor(tab.key), frame);
  });

  $effect(() => {
    const head = zone.toolbar;
    if (!head) return;
    const content = head.content;
    const rowless = head.rowless;
    frame.content = content;
    frame.rowless = rowless;
    frame.tools = head.tools || head.action || head.groups.length ? toolbar : null;
    return () => {
      if (frame.content === content) frame.content = null;
      if (frame.rowless === rowless) frame.rowless = null;
      if (frame.tools === toolbar) frame.tools = null;
    };
  });
}
