import type { Component } from 'svelte';
import type { HuddleItem } from './huddle-model';

export const DETAIL_SLOT: unique symbol = Symbol('task-manager-detail-slot');

export type DetailSlot = Component<{ item: HuddleItem; detailed?: boolean }>;
