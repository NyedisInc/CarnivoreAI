from __future__ import annotations

from .color_utils import Pairing

NORMAL = 4.5
LARGE = 3.0

PAIRINGS: list[Pairing] = [
    Pairing("body text", "color-fg", "color-bg", NORMAL, "styles.css:234-243 body{background:--color-bg;color:--color-fg}"),
    Pairing("header title", "color-fg", "color-bg-page", NORMAL, "styles.css:247-251 .header{background:--color-bg-page}, h1 inherits --color-fg"),

    Pairing("sidebar toggle icon", "color-fg-muted", "color-bg-elevated", NORMAL, "session-sidebar.css:33,71"),
    Pairing("sidebar pin icon", "color-fg-muted", "color-bg-elevated", NORMAL, "session-sidebar.css:138,71"),
    Pairing("sidebar close icon", "color-fg-muted", "color-bg-elevated", NORMAL, "session-sidebar.css:195,71"),
    Pairing("sidebar empty state", "color-fg-subtle", "color-bg-elevated", NORMAL, "session-sidebar.css:216,71"),
    Pairing("sidebar row name", "color-fg", "color-bg-elevated", NORMAL, "session-sidebar.css:252,71"),
    Pairing("sidebar row badge", "color-fg-faint", "color-bg-elevated", NORMAL, "session-sidebar.css:265,71"),
    Pairing("sidebar mark-unread icon", "color-fg-faint", "color-bg-elevated", NORMAL, "session-sidebar.css:360,71"),
    Pairing("sidebar delete icon", "color-fg-faint", "color-bg-elevated", NORMAL, "session-sidebar.css:401,71"),
    Pairing("sidebar title", "color-accent", "color-bg-elevated", LARGE, "session-sidebar.css:176,71 .session-sidebar-title bold"),

    Pairing("home bar button label", "color-fg-muted", "color-bg-elevated", NORMAL, "home-bar.css:113,147"),
    Pairing("home bar version label", "color-fg-faint", "color-bg-elevated", NORMAL, "home-bar.css:113,212"),

    Pairing("toast body text", "color-fg", "color-bg-card", NORMAL, "toast.css:38 bg:--color-bg-card"),
    Pairing("toast muted text", "color-fg-muted", "color-bg-card", NORMAL, "toast.css:38,75"),
    Pairing("toast title", "color-fg", "color-bg-elevated", NORMAL,
            "toast.css:140 .toast__title{color:--oc-text-primary} on .toast{background:--oc-ground-raised}"),

    Pairing("prompt header text", "color-fg-muted", "color-bg-card", NORMAL,
            "PromptHeader.svelte .prompt-header{background:--oc-ground-card;color:--oc-text-secondary}"),

    Pairing("config editor body text", "color-fg", "color-bg", NORMAL, "config-editor.css:97 on modal bg:--color-bg (config-editor-modal.css:30)"),
    Pairing("config editor muted text", "color-fg-muted", "color-bg", NORMAL, "config-editor.css:62,86,123 on modal bg"),
    Pairing("config editor subtle text", "color-fg-subtle", "color-bg", NORMAL, "config-editor.css:104,183 on modal bg"),
    Pairing("config drawer muted text", "color-fg-muted", "color-bg-elevated", NORMAL, "config-drawer.css:106 (drawer surface bg-elevated)"),

    Pairing("slash command chip hint", "color-fg-faint", "color-bg-elevated", NORMAL, "slash-command-chips.css:32,83,96,138"),

    Pairing("terminal tools muted icon", "color-fg-muted", "color-bg-elevated", NORMAL, "terminal-tools.css:53,239,329"),
    Pairing("terminal tools body text", "color-fg", "color-bg-elevated", NORMAL, "terminal-tools.css:229,365"),

    Pairing("badge owned", "color-badge-owned-fg", "color-badge-owned-bg", NORMAL, "styles.css:97-98,2341"),
    Pairing("badge tmux", "color-badge-tmux-fg", "color-badge-tmux-bg", NORMAL, "styles.css:99-100,2341"),
    Pairing("badge external", "color-badge-external-fg", "color-badge-external-bg", NORMAL, "styles.css:101-102,2342"),

    Pairing("success text", "color-success", "color-bg", NORMAL, "styles.css:71, used as text color e.g. server-status.css"),
    Pairing("warning text", "color-warning", "color-bg", NORMAL, "styles.css:72, config-editor.css:389, session-sidebar.css:380"),
    Pairing("danger text", "color-danger", "color-bg", NORMAL, "styles.css:73, config-editor.css:168, session-sidebar.css:409"),
    Pairing("info text", "color-info", "color-bg", NORMAL, "styles.css:74, styles.css:930"),

    Pairing("accent link on bg", "color-accent", "color-bg", LARGE, "styles.css:53 --color-accent used as link/icon color"),
    Pairing("accent link on elevated", "color-accent", "color-bg-elevated", LARGE, "styles.css:53, many .row:hover states land on elevated surfaces"),
    Pairing("on-accent button text", "color-on-accent", "color-accent", NORMAL, "styles.css:65 text painted on a solid accent fill (primary buttons)"),


    Pairing("help link (visited/hover)", "color-accent-strong", "color-bg-elevated", NORMAL,
            "styles.css .adopt-disclosure-body a:visited / :hover on --color-bg-elevated"),
    Pairing("help link focus ring", "color-accent", "color-bg-elevated", LARGE,
            "styles.css .adopt-disclosure-body a:focus-visible outline on --color-bg-elevated"),

    Pairing("focus indicator", "color-accent", "color-bg-elevated", LARGE, "session-sidebar.css:373 focus-visible box-shadow accent on row/panel bg"),
    Pairing("input focus border", "color-accent", "color-bg", LARGE, "matrix theme.css:44-49 focus border must read against field bg, generalised fleet-wide"),
]
