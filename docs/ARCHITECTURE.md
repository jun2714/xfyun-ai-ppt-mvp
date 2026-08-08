# SparkDeck 007 architecture

Dependencies point inward:

`Interfaces → Application → Domain/Packages ← Infrastructure adapters`

The Scene Graph is the only render truth. Web preview, commands, quality evaluation and PPTX export consume it. The PPTX adapter performs no layout decisions.

Every presentation artifact carries `schemaVersion`, `revision`, `contentHash` and upstream hashes. Design, composition, assets and quality remain separate observable jobs. Paid model calls have a cost preflight and are never retried automatically.

Production stop lines are enforced by tests: no scenario/role/page-number layout dispatch, layout IDs, first-block-only consumption, or execution of generated code.
