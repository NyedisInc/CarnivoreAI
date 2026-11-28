
export const HAS_BUNDLED_CATALOG = false;

export function createFallbackI18n(_options?: { locale?: string }) {
    return {
        t(key: string): string {
            return typeof key === 'string' ? key : '';
        },
        setLocale(): boolean {
            return false;
        },
        onLocaleChange(): () => void {
            return () => {};
        },
        availableLocales(): string[] {
            return ['en'];
        },
        extendCatalog(): number {
            return 0;
        },
        get locale(): string {
            return 'en';
        },
        get problems(): string[] {
            return [];
        },
    };
}

export function registerLocalFragment(_pluginId: string, _messages: Record<string, unknown>): number {
    return 0;
}

export function fallbackCatalogKeys(): string[] {
    return [];
}
