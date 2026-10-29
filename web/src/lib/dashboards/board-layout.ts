import { homeLayout } from '../../opscenter/engine/layout.svelte';
import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import type { Layout } from '../../opscenter/engine/types';

export function dashboardLayout(id: string): Layout | undefined {
  return id === (homeBoards.viewing ?? homeBoards.active) ? (homeLayout.state.layout as Layout) : homeBoards.layouts?.[id];
}
