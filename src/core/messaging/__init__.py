"""Messaging providers: an outside text service (the imsg bridge first) bound to sessions (issue #1499).

A provider serves the CPP v1 contract (``docs/messaging.md`` section 8). A conversation on it is BOUND to one or more
sessions, ``in``, ``out`` or ``both``. Inbound texts are held while a dialog is open and delivered as one dated batch;
outbound texts leave only through ``messaging_send`` from a bound session. This is not a notification system: nothing
here touches the notification engine except to reuse its guarded HTTP client and Keychain helpers.

Module map: ``contract`` (pure CPP parsing), ``accept`` (the inbound ladder), ``routing`` (which session),
``batch`` (the dated backlog), ``ddl`` and ``store`` (the tables and their one writer), ``secrets`` (Keychain),
``client`` (REST), ``stream`` (the dial-out event stream), ``events`` (one event's decision), ``delivery`` (the
drain), ``outbound`` (``messaging_send``), ``notices`` (Carnivore's own fixed texts), ``runtime`` (boot wiring).
"""
