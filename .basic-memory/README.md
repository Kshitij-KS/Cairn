# .basic-memory/

`project.json` is **our** manifest, read by `scripts/sync-memory.*` and `scripts/new-project-memory.*`.

Basic Memory itself (v0.23.x) has no per-repo config file: projects are registered globally in
`~/.basic-memory/config.json` (`basic-memory project add <name> <path>`), and its SQLite index
lives in `~/.basic-memory/memory.db`. Nothing Basic Memory writes lands inside this repo.

The sync script's `pre` step reads `name` from this manifest and, if `basic-memory` is on PATH,
registers this clone as that project when it is not already registered. Dot-folders are ignored
by Basic Memory's indexer, so this folder never shows up as a note.
