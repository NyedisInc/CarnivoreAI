import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

function theme(id: string, name: string, vars: Record<string, string>): unknown {
  return {
    id,
    name,
    description: `${name} colours`,
    author: null,
    version: '1.0.0',
    cssVars: vars,
    xterm: {},
    source: 'builtin',
  };
}

export const themesFixtures: WidgetFixtures = {
  data: {
    'GET /themes': [
      theme('amber-terminal', 'amber terminal', { '--color-bg-page': '#14100a', '--color-border': '#4a3a1a', '--color-accent': '#f0a030', '--color-success': '#8cc84b', '--color-warning': '#e0c040', '--color-danger': '#d8503c', '--color-fg': '#e8d8b0' }),
      theme('harbor-blue', 'harbor blue', { '--color-bg-page': '#0b1420', '--color-border': '#23405e', '--color-accent': '#4aa3df', '--color-success': '#4cc38a', '--color-warning': '#e6b84a', '--color-danger': '#e5604d', '--color-fg': '#cfe3f3' }),
      theme('meridian-green', 'meridian green', { '--color-bg-page': '#0a1510', '--color-border': '#1f4a35', '--color-accent': '#3ecf8e', '--color-success': '#7ad35a', '--color-warning': '#d9b84a', '--color-danger': '#d9534f', '--color-fg': '#cde8d8' }),
      theme('paper-light', 'paper light', { '--color-bg-page': '#f4f1ea', '--color-border': '#c9c2b2', '--color-accent': '#2f6fb5', '--color-success': '#2e8b57', '--color-warning': '#b8860b', '--color-danger': '#b83a3a', '--color-fg': '#2a2a26' }),
      theme('plum-night', 'plum night', { '--color-bg-page': '#150d1c', '--color-border': '#43275a', '--color-accent': '#b57be0', '--color-success': '#6fcf97', '--color-warning': '#e2b955', '--color-danger': '#e0607e', '--color-fg': '#e3d4f0' }),
      theme('slate-mono', 'slate mono', { '--color-bg-page': '#16181b', '--color-border': '#3a3f45', '--color-accent': '#9aa7b4', '--color-success': '#7fb88a', '--color-warning': '#c9b068', '--color-danger': '#c46a6a', '--color-fg': '#d5dae0' }),
    ],
    'GET /sessions/list': sessionList(),
  },
  empty: {
    'GET /themes': [],
    'GET /sessions/list': [],
  },
};
