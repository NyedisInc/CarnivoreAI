import { ago, MIN } from './clock';
import type { WidgetFixtures } from './types';

function browser(state: 'live' | 'stopped', viewers: number): unknown {
  return {
    id: 'fx-browser',
    label: 'docs preview',
    url: 'https://docs.example.com/guide',
    state,
    viewers,
    created_at: ago(40 * MIN),
    updated_at: ago(2 * MIN),
  };
}

export const browserFixtures: WidgetFixtures = {
  data: { 'GET /browsers': { browsers: [browser('live', 1)] } },
  empty: { 'GET /browsers': { browsers: [browser('stopped', 0)] } },
};
