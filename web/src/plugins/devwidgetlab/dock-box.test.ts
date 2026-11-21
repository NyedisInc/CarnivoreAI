import { describe, expect, it } from 'vitest';
import { BAR_PX, dockBox, dockEdge, DOCK_WINDOW, PANEL_DEFAULT_PX, PANEL_EDGE_PX } from './dock-box';
import { OUT_DEFAULT_PX } from '../../lib/session-rail/rail-size';

describe('the slide-out body box', () => {
  it('pins the lab defaults to the real panel\'s own constants', () => {
    expect(PANEL_DEFAULT_PX).toEqual(OUT_DEFAULT_PX);
  });

  it('is the whole panel less the inner edge line, the right one the window tall and the bottom one the strip wide', () => {
    expect(dockBox('drawer', 'right')).toEqual({ w: OUT_DEFAULT_PX.side - PANEL_EDGE_PX, h: DOCK_WINDOW.h });
    expect(dockBox('drawer', 'bottom')).toEqual({ w: DOCK_WINDOW.w - BAR_PX, h: OUT_DEFAULT_PX.bottom - PANEL_EDGE_PX });
  });

  it('is nothing for the left drawer and every other host, and names the harness edge', () => {
    expect(dockBox('drawer', 'left')).toBeNull();
    expect(dockBox('home', 'right')).toBeNull();
    expect(dockEdge('right')).toBe('side');
    expect(dockEdge('bottom')).toBe('bottom');
    expect(dockEdge('left')).toBeNull();
  });
});
