import type { Component } from 'svelte';

export interface DrawerSearchController {
  query: string;
  onType(): void;
  move(delta: number): void;
  pickActive(): Promise<boolean>;
  goActive?(): Promise<boolean>;
  showActions?: boolean;
  cancel(): void;
  readonly hasHits: boolean;
  readonly active: number;
  readonly suggesting?: boolean;
  readonly suggestActiveId?: string | null;
  suggestMove?(delta: number): void;
  suggestPick?(): boolean;
  suggestClose?(): void;
  onReplaceQuery?: (text: string) => void;
}

export interface DrawerSearchProvider {
  placeholderKey: string;
  labelKey: string;
  resultsId: string;
  hitIdPrefix: string;
  create(): DrawerSearchController;
  Results: Component<{ controller: DrawerSearchController }>;
}
