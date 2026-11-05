import { hostWindow } from './sessions/env';
import type { LegacyApiShape } from './legacy-api-names';
import type { SessionSidebarController } from './drawer/controller';

export class LegacyGlobalMissing extends Error {
  constructor(readonly globalName: LegacyGlobalName) {
    super(`legacy_global_missing:${globalName}`);
  }
}

export type LegacyGlobalName =
  | 'API'
  | 'Auth'
  | 'Preferences'
  | 'Themes'
  | 'UIFlags'
  | 'App'
  | 'Launchpad'
  | 'ListingPush'
  | 'NavigationGeneration'
  | 'TerminalPrimaryHold'
  | 'DeepLinkTarget'
  | 'LayoutDeepLinkTarget'
  | 'TerminalController'
  | 'TerminalInputOwnership'
  | 'ClipboardTools'
  | `SessionSidebar${string}`;

export function legacyGlobal<T = unknown>(name: LegacyGlobalName): T | undefined {
  return (hostWindow() as unknown as Record<string, T | undefined> | undefined)?.[name];
}

export function requireLegacyGlobal<T = unknown>(name: LegacyGlobalName): T {
  const found = legacyGlobal<T>(name);
  if (found === undefined) throw new LegacyGlobalMissing(name);
  return found;
}

export function legacyApi<T extends LegacyApiShape<T>>(): T {
  return requireLegacyGlobal<T>('API');
}

export function legacyAuth<T extends object>(): T {
  return requireLegacyGlobal<T>('Auth');
}

export function sessionSidebar<T = unknown>(suffix = ''): T | undefined {
  return legacyGlobal<T>(`SessionSidebar${suffix}`);
}

export type SidebarPick<K extends keyof SessionSidebarController> = Pick<SessionSidebarController, K>;
