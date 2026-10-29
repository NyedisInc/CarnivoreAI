<script lang="ts">
    import { onMount } from 'svelte';
    import Continuity from './Continuity.svelte';
    import InstallCommand from './InstallCommand.svelte';
    import './site.css';

    const download = 'https://github.com/NyedisInc/CarnivoreAI/releases/download/v1.16.2/Carnivore-1.16.2-arm64.dmg';
    const source = 'https://github.com/NyedisInc/CarnivoreAI';

    onMount(() => {
        const engine = (window as Window & { ScrollCraft?: { mount: (root: Document) => void } }).ScrollCraft;
        if (engine) engine.mount(document);
    });
</script>

<svelte:head>
    <title>Carnivore | the work keeps going</title>
    <meta name="description" content="Carnivore keeps AI coding sessions running on your Mac and gives you the live terminal from your phone. Download for macOS Apple Silicon." />
</svelte:head>

<div class="site-shell">
    <header class="site-header tw:mx-auto tw:flex tw:items-center tw:justify-between tw:gap-4">
        <a href="#top" class="brand-link" aria-label="Carnivore home">
            <img src="/assets/wordmark-700.webp" width="700" height="138" alt="Carnivore" fetchpriority="high" />
        </a>
        <nav aria-label="site" class="site-nav tw:flex tw:items-center tw:gap-5">
            <a href="#product">product</a>
            <a href="#continuity">continuity</a>
            <a href="#download">download</a>
        </nav>
    </header>

    <main id="top">
        <section class="hero" aria-labelledby="hero-title" data-sc-act="flow">
            <div class="hero-field" aria-hidden="true" data-sc-parallax="-0.35"></div>
            <div class="hero-art" aria-hidden="true">
                <div class="art-ring" data-sc-parallax="-0.7"></div>
                <img class="hero-claw" src="/assets/claw.webp" width="517" height="500" alt="" data-sc-parallax="0.55" />
                <div class="art-edge" data-sc-parallax="1.05"></div>
            </div>
            <div class="hero-content tw:mx-auto tw:flex tw:flex-col tw:justify-center">
                <p class="site-kicker">carnivore / for macos</p>
                <h1 id="hero-title">the work<br /><em>keeps going.</em></h1>
                <p class="hero-lede">run claude code and codex on your mac. stay in control from your phone.</p>
                <div class="hero-actions tw:flex tw:flex-wrap tw:items-center tw:gap-3">
                    <a class="site-button site-button--primary" href={download} aria-describedby="hero-download-detail">download for macos</a>
                    <a class="text-link" href="#product">see how it works</a>
                </div>
                <p id="hero-download-detail" class="hero-detail">v1.16.2 · apple silicon · macos 13+</p>
                <InstallCommand />
            </div>
            <div class="hero-base" aria-hidden="true"><span>local process</span><span>remote view</span></div>
        </section>

        <section id="product" class="principle site-wrap" data-sc-act="flow" aria-labelledby="principle-title">
            <div class="principle-lead tw:flex tw:flex-col tw:gap-5" data-sc-in>
                <h2 id="principle-title">the session lives<br />on your mac.</h2>
                <p>carnivore runs a real terminal session in tmux and streams its output to a browser. you can watch, type and respond from another screen while the process stays on the host. link your other computers into one pack and see every session in one place. <a class="text-link" href="/link/">link a computer</a> <a class="text-link" href="/pack/">use your pack</a></p>
            </div>
            <div class="principle-rail tw:grid" data-sc-in>
                <div class="principle-item tw:flex tw:flex-col tw:gap-2">
                    <span>at the machine</span>
                    <strong>the process keeps its place.</strong>
                    <p>your agent and terminal remain in the mac's session, even when the browser is gone.</p>
                </div>
                <div class="principle-item tw:flex tw:flex-col tw:gap-2">
                    <span>in your hand</span>
                    <strong>the same terminal opens again.</strong>
                    <p>reconnect from your phone to read output, send input and continue where you left off.</p>
                </div>
            </div>
        </section>

        <Continuity />

        <section class="interface site-wrap" data-sc-act="flow" aria-labelledby="interface-title">
            <div class="interface-intro tw:flex tw:flex-col tw:gap-5" data-sc-in>
                <h2 id="interface-title">real sessions.<br />room to work.</h2>
                <p>keep projects and sessions in view, then open a terminal with panes and tabs arranged for the task. on a phone, terminal panes become a swipeable strip.</p>
            </div>
            <figure class="interface-figure" data-sc-reveal="up" data-sc-reveal-at="0.1 0.58">
                <div class="interface-frame">
                    <img src="/assets/interface-terminal.png" width="1440" height="900" loading="lazy" alt="carnivore development interface showing the project and session rail beside a terminal tab with its menu open." />
                </div>
                <figcaption>interface preview from a development fixture. example projects and session shown.</figcaption>
            </figure>
            <div class="interface-notes tw:grid">
                <p><strong>one session, many views.</strong> the desktop and phone connect to work that stays on the mac.</p>
                <p><strong>your layout.</strong> arrange terminal tabs and panes around concurrent tasks.</p>
            </div>
        </section>

        <section id="download" class="download" data-sc-act="flow" aria-labelledby="download-title">
            <div class="download-inner site-wrap tw:flex tw:flex-col">
                <p class="site-kicker">ready when you are</p>
                <h2 id="download-title">put the work<br />in motion.</h2>
                <p class="download-copy">install carnivore on your mac. open a session there, then reach it from your phone.</p>
                <div class="download-action tw:flex tw:flex-wrap tw:items-center tw:gap-4">
                    <a class="site-button site-button--primary" href={download} aria-describedby="download-detail">download for macos</a>
                    <a class="text-link" href={source} target="_blank" rel="noopener noreferrer">view source <span class="sr-only">(opens in a new tab)</span></a>
                </div>
                <p id="download-detail" class="download-detail">v1.16.2 / apple silicon / macos 13+ / .dmg</p>
                <InstallCommand label="install from terminal" />
                <p class="install-note">installing by hand: open the dmg and drag carnivore to applications. session persistence uses tmux 3.2 or newer.</p>
            </div>
        </section>
    </main>

    <footer class="site-footer site-wrap tw:flex tw:flex-wrap tw:items-center tw:justify-between tw:gap-4">
        <a href="https://carnivore.ai/#download">carnivore.ai / download carnivore</a>
        <nav aria-label="legal" class="tw:flex tw:flex-wrap tw:gap-4">
            <a href="/terms/2026-10-01/">terms</a>
            <a href="/privacy/">privacy</a>
            <a href="/link/">link a computer</a>
            <a href="/pack/">use your pack</a>
            <a href="/content-policy/">content policy</a>
        </nav>
    </footer>
</div>
