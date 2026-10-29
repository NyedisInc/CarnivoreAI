import type { Component } from 'svelte';
import { readTab, writeTab } from '../../opscenter/ui/tab-memory';
import type { BoardViewProps } from './view-props';
import SwimlanesView from './views/SwimlanesView.svelte';
import ListView from './views/ListView.svelte';
import TimelineView from './views/TimelineView.svelte';
import CalendarView from './views/CalendarView.svelte';
import ColumnsView from './views/ColumnsView.svelte';

export const BOARD_VIEWS = ['swimlanes', 'list', 'timeline', 'calendar', 'columns'] as const;
export type BoardView = (typeof BOARD_VIEWS)[number];
export const DEFAULT_VIEW: BoardView = 'swimlanes';
export const VIEW_MEMORY_KEY = 'swarm-board-view';

export const VIEW_COMPONENTS: Record<BoardView, Component<BoardViewProps>> = {
  swimlanes: SwimlanesView,
  list: ListView,
  timeline: TimelineView,
  calendar: CalendarView,
  columns: ColumnsView,
};

export function readView(): BoardView {
  return readTab(VIEW_MEMORY_KEY, BOARD_VIEWS, DEFAULT_VIEW) as BoardView;
}

export function writeView(view: BoardView): void {
  writeTab(VIEW_MEMORY_KEY, view);
}
