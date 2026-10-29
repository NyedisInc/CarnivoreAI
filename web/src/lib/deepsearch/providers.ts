import { groupedSearchApi } from './deepsearch-api';
import DeepSearchResults, { HIT_ID_PREFIX, RESULTS_ID } from './DeepSearchResults.svelte';
import { DeepSearchController } from './deepsearch.svelte';
import type { DrawerSearchProvider } from './provider-types';

export interface GroupedSearchRequest {
  path: string;
  placeholderKey: string;
  labelKey: string;
  noMatchesKey: string;
  promptStyle?: boolean;
}

export function groupedProvider({ path, placeholderKey, labelKey, noMatchesKey, promptStyle = false }: GroupedSearchRequest): DrawerSearchProvider {
  return {
    placeholderKey,
    labelKey,
    resultsId: RESULTS_ID,
    hitIdPrefix: HIT_ID_PREFIX,
    create: () => {
      const controller = new DeepSearchController(groupedSearchApi(path), undefined, noMatchesKey);
      controller.promptStyle = promptStyle;
      return controller;
    },
    Results: DeepSearchResults as DrawerSearchProvider['Results'],
  };
}

export function contextProvider(): DrawerSearchProvider {
  return {
    placeholderKey: 'deepsearch.placeholder',
    labelKey: 'deepsearch.label',
    resultsId: RESULTS_ID,
    hitIdPrefix: HIT_ID_PREFIX,
    create: () => {
      const controller = new DeepSearchController();
      controller.showActions = true;
      return controller;
    },
    Results: DeepSearchResults as DrawerSearchProvider['Results'],
  };
}
