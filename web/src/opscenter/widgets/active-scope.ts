/* the bottom rail */
import { sessions } from '../api';
import { activeTerminalSessionId } from '../lib/active-terminal';
import { scopeForWidget, sessionScopeFor, type SessionScope } from './session-scope';
import type { WidgetManifest } from './types';

export function activeScopeFor(manifest: Pick<WidgetManifest, 'scope'> | undefined): SessionScope | null {
  if (manifest?.scope !== 'session') return null;
  return scopeForWidget(manifest, sessionScopeFor(sessions.data, activeTerminalSessionId()));
}
