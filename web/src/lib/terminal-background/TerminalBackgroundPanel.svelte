
<script lang="ts">
    import ArtDensity from '../../opscenter/art/ArtDensity.svelte';
    import { t } from '../i18n/index.svelte';

    let { sessionName, palette }: { sessionName?: string | null; palette?: Record<string, string> } = $props();

    interface ThemeManifestLike {
        id: string;
        name?: string;
        source?: string;
        background?: { image?: string; dim?: number } | null;
        xterm?: Record<string, string>;
    }

    interface BackgroundApi {
        DEFAULT_DIM: number;
        minimumDim(xtermTheme: unknown): number | null;
        getActiveSession(): string | null;
        ACTIVE_SESSION_EVENT?: string;
        getOverrides(): Record<
            string,
            {
                theme_id?: string | null;
                dim?: number | null;
                disabled?: boolean;
                image?: string | null;
            }
        >;
        setOverride(
            name: string,
            patch: { theme_id: string | null; dim: number | null; disabled: boolean },
        ): Promise<unknown>;
        uploadImage(name: string, file: File): Promise<unknown>;
        clearImage(name: string): Promise<unknown>;
    }

    interface StatusError {
        status?: number;
    }

    interface ThemesApi {
        listAll(): ThemeManifestLike[];
        getActiveTerminalManifest(): ThemeManifestLike | null;
    }

    function backgroundApi(): BackgroundApi | null {
        return (globalThis as { TerminalBackground?: BackgroundApi }).TerminalBackground ?? null;
    }

    function themesApi(): ThemesApi | null {
        return (globalThis as { Themes?: ThemesApi }).Themes ?? null;
    }

    let choice = $state('theme');
    let dimPercent = $state(90);
    let saving = $state(false);
    let failed = $state(false);
    let hasUpload = $state(false);
    let busy = $state(false);
    let uploadError: string | null = $state(null);

    const api = backgroundApi();
    const themes = themesApi();

    /* the bottom bar */
    let session: string | null = $state(null);

    const withImages: ThemeManifestLike[] = (themes?.listAll() ?? []).filter(
        (m) => !!(m.background && m.background.image),
    );

    function seedFrom(name: string | null): void {
        if (!api) return;
        choice = 'theme';
        hasUpload = false;
        uploadError = null;
        dimPercent = Math.round((api.DEFAULT_DIM ?? 0.9) * 100);
        if (!name) return;
        const stored = api.getOverrides()[name];
        if (!stored) return;
        if (stored.disabled) choice = 'none';
        else if (stored.theme_id) choice = stored.theme_id;
        hasUpload = !!stored.image;
        if (typeof stored.dim === 'number') dimPercent = Math.round(stored.dim * 100);
    }


    $effect(() => {
        if (sessionName !== undefined) {
            session = sessionName;
            seedFrom(sessionName);
            return;
        }
        session = api?.getActiveSession() ?? null;
        seedFrom(session);
        const evt = api?.ACTIVE_SESSION_EVENT;
        if (!evt) return;
        const onMove = (e: Event): void => {
            const next = (e as CustomEvent<{ session: string | null }>).detail?.session ?? null;
            session = next;
            seedFrom(next);
        };
        window.addEventListener(evt, onMove);
        return () => window.removeEventListener(evt, onMove);
    });

    const floorPercent: number = $derived.by(() => {
        void session;
        const chosen = choice !== 'theme' && choice !== 'none'
            ? (withImages.find((m) => m.id === choice) ?? null)
            : null;
        const manifest = chosen ?? themes?.getActiveTerminalManifest() ?? null;
        const floor = api ? api.minimumDim(chosen?.xterm ?? palette ?? manifest?.xterm) : null;
        if (floor === null || floor === undefined) return 100;
        return Math.min(100, Math.ceil(floor * 100));
    });

    const effectivePercent = $derived(Math.max(floorPercent, dimPercent));
    const clamped = $derived(effectivePercent > dimPercent);
    const canPaint = $derived(hasUpload || withImages.length > 0);

    async function commit(): Promise<void> {
        if (!api || !session || saving) return;
        saving = true;
        failed = false;
        const isDefaultDim = dimPercent === Math.round((api.DEFAULT_DIM ?? 0.9) * 100);
        try {
            await api.setOverride(session, {
                theme_id: choice === 'theme' || choice === 'none' ? null : choice,
                dim: choice === 'theme' && isDefaultDim ? null : dimPercent / 100,
                disabled: choice === 'none',
            });
        } catch {
            failed = true;
        } finally {
            saving = false;
        }
    }

    async function chooseImage(event: Event): Promise<void> {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files && input.files[0];
        if (!api || !session || !file || busy) return;
        busy = true;
        uploadError = null;
        try {
            await api.uploadImage(session, file);
            hasUpload = true;
        } catch (err) {
            const status = (err as StatusError)?.status;
            uploadError =
                status === 413
                    ? 'terminal.background.too_large'
                    : status === 415
                      ? 'terminal.background.wrong_type'
                      : 'terminal.background.upload_failed';
        } finally {
            busy = false;
            input.value = '';
        }
    }

    async function useThemeImage(): Promise<void> {
        if (!api || !session || busy) return;
        busy = true;
        uploadError = null;
        try {
            await api.clearImage(session);
            hasUpload = false;
        } catch {
            uploadError = 'terminal.background.upload_failed';
        } finally {
            busy = false;
        }
    }
</script>

<div class="tbg">
    <ArtDensity />
    <div class="tbg__head">{t('terminal.background.heading')}</div>

    {#if !session}
        <div class="tbg__note">{t('terminal.background.needs_session')}</div>
    {:else}
        <!-- display: none -->
        <div class="tbg__row">
            <span class="tbg__label">{t('terminal.background.source')}</span>
            <label class="tbg__file oc-focus-host">
                <input
                    class="tbg__fileinput"
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp,image/avif"
                    disabled={busy}
                    onchange={chooseImage}
                />
                <span>{busy ? t('terminal.background.choosing') : t('terminal.background.choose')}</span>
            </label>
        </div>

        {#if hasUpload}
            <div class="tbg__row">
                <span class="tbg__label">{t('terminal.background.source.uploaded')}</span>
                <button class="tbg__btn" type="button" disabled={busy} onclick={useThemeImage}>
                    {t('terminal.background.use_theme')}
                </button>
            </div>
        {/if}

        {#if uploadError}
            <div class="tbg__note tbg__note--bad">{t(uploadError)}</div>
        {/if}

        {#if withImages.length > 0}
            <label class="tbg__row tbg__row--stacked">
                <span class="tbg__label">{t('terminal.background.source.theme')}</span>
                <select class="tbg__select" bind:value={choice} onchange={commit}>
                    <option value="theme">{t('terminal.background.source.theme')}</option>
                    <option value="none">{t('terminal.background.source.none')}</option>
                    {#each withImages as manifest (manifest.id)}
                        <option value={manifest.id}>{(manifest.name || manifest.id).toLowerCase()}</option>
                    {/each}
                </select>
            </label>
        {/if}

        {#if canPaint}
            <label class="tbg__row">
                <span class="tbg__label">{t('terminal.background.dim')}</span>
                <input
                    class="tbg__range"
                    type="range"
                    min={floorPercent}
                    max="100"
                    step="1"
                    disabled={choice === 'none' || floorPercent >= 100}
                    bind:value={dimPercent}
                    onchange={commit}
                />
                <span class="tbg__value">{effectivePercent}%</span>
            </label>

            {#if floorPercent >= 100}
                <div class="tbg__note">{t('terminal.background.unmeasurable')}</div>
            {:else if clamped}
                <div class="tbg__note">
                    {t('terminal.background.clamped', { percent: floorPercent })}
                </div>
            {:else}
                <div class="tbg__note">
                    {t('terminal.background.floor', { percent: floorPercent })}
                </div>
            {/if}
        {:else}
            <div class="tbg__note">{t('terminal.background.none_installed')}</div>
        {/if}

        {#if failed}
            <div class="tbg__note tbg__note--bad">{t('terminal.background.save_failed')}</div>
        {/if}
    {/if}
</div>

<style>
  @layer components {
      .tbg {
          border-top: 1px solid var(--oc-line-panel);
          padding: var(--oc-space-2) 10px 10px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          font-family: var(--font-mono);
          font-size: var(--oc-fs-body);
          color: var(--oc-text-primary);
      }

      .tbg__head {
          color: var(--oc-text-secondary);
          text-transform: lowercase;
          letter-spacing: 0.04em;
      }

      .tbg__row {
          display: flex;
          align-items: center;
          gap: var(--oc-space-2);
      }

      .tbg__label {
          flex: none;
          min-width: 44px;
          color: var(--oc-text-secondary);
      }

      .tbg__row--stacked {
          flex-direction: column;
          align-items: stretch;
          gap: 3px;
      }

      /* max-width: 100% */
      .tbg__select {
          flex: 1;
          min-width: max-content;
          max-width: 100%;
          background: var(--oc-ground-raised);
          color: var(--oc-text-primary);
          border: 1px solid var(--oc-line-panel);
          border-radius: var(--oc-radius-sm);
          font-family: inherit;
          font-size: inherit;
          padding: 3px var(--oc-space-1);
      }

      .tbg__range {
          flex: 1;
          min-width: 0;
          accent-color: var(--oc-coral);
      }

      .tbg__value {
          flex: none;
          min-width: 34px;
          text-align: right;
          color: var(--oc-text-secondary);
      }

      .tbg__note {
          color: var(--oc-text-secondary);
          line-height: 1.35;
      }

      .tbg__note--bad {
          color: var(--oc-coral);
      }

      .tbg__file,
      .tbg__btn {
          flex: 1;
          min-width: 0;
          box-sizing: border-box;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: var(--oc-ground-raised);
          color: var(--oc-text-primary);
          border: 1px solid var(--oc-line-panel);
          border-radius: var(--oc-radius-sm);
          font-family: inherit;
          font-size: inherit;
          padding: 3px var(--oc-space-1);
          min-height: 24px;
          cursor: pointer;
      }

      .tbg__file:hover,
      .tbg__btn:hover {
          border-color: var(--oc-coral);
      }

      .tbg__btn:disabled {
          cursor: default;
          color: var(--oc-text-secondary);
      }

      /*  hidden
 display: none */
      .tbg__fileinput {
          position: absolute;
          width: 1px;
          height: 1px;
          padding: 0;
          margin: -1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
          border: 0;
      }

      /* display: none */
      @media (pointer: coarse) {
          .tbg__file,
          .tbg__btn {
              min-height: 44px;
          }

          .tbg__range {
              height: 44px;
          }
  }
  }
</style>
