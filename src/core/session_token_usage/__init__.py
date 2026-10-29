"""Per-session token spend, cost estimate and context headroom.

Four readers and a dispatch, all synchronous file I/O:

  ``claude_reader``  sums ``message.usage`` over one jsonl transcript,
                     de-duplicated by ``message.id`` and resumed from the
                     incremental cache.
  ``codex_reader``   reads the last ``token_count`` event off the tail of
                     a rollout and converts codex's INCLUSIVE input count
                     into the disjoint shape everything else here uses.
  ``model_table``    published list prices and context windows, matched
                     by longest model-id prefix. Estimates, revised by
                     hand.
  ``cache``          where the last read of an append-only transcript
                     stopped, so the next one reads only the tail.
  ``reader``         the family dispatch and the one response shape.

The whole package is contracted NEVER TO RAISE and never to fabricate a
zero. Three outcomes only: measured (``ok``), measured absent
(``absent``), could not measure (``unchecked``).

Full model: ``docs/session-token-usage.md``.
"""
