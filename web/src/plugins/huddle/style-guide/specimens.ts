import type { Component } from 'svelte';
import type { PluginSpecimen } from '../../sdk';
import BubbleKinds from './BubbleKinds.svelte';
import CharacterBoard from './CharacterBoard.svelte';
import ChatEntries from './ChatEntries.svelte';
import ExpressionBoard from './ExpressionBoard.svelte';
import SwarmPageBoard from './SwarmPageBoard.svelte';
import SwarmPanelBoard from './SwarmPanelBoard.svelte';

function as(component: unknown): Component<Record<string, unknown>> {
  return component as Component<Record<string, unknown>>;
}

export const TASK_MANAGER_SPECIMENS: readonly PluginSpecimen[] = [
  { id: 'sg-live-swarm-characters', component: as(CharacterBoard), props: { part: 'theme' } },
  { id: 'sg-live-swarm-characters-pixel', component: as(CharacterBoard), props: { part: 'pixel' } },
  { id: 'sg-live-swarm-expressions', component: as(ExpressionBoard) },
  { id: 'sg-live-swarm-panel', component: as(SwarmPanelBoard) },
  { id: 'sg-live-swarm-page', component: as(SwarmPageBoard) },
  { id: 'sg-live-chat-entries', component: as(ChatEntries) },
  { id: 'sg-live-huddle-bubbles', component: as(BubbleKinds) },
];
