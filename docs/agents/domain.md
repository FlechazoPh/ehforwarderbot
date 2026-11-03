# Domain Docs

How engineering skills should consume this repository's domain documentation.

## Before exploring, read these

- `CONTEXT-MAP.md` at the repo root, then each relevant context's `CONTEXT.md`
- `docs/adr/` for system-wide decisions
- Each relevant context's `docs/adr/` for context-specific decisions

If these files do not exist, proceed silently. The domain-modeling skill creates them lazily when concepts or decisions are resolved.

## File structure

Multi-context repository:

/
├── CONTEXT-MAP.md
├── docs/adr/              ← system-wide decisions
└── <context>/
    ├── CONTEXT.md
    └── docs/adr/          ← context-specific decisions

## Use the glossary's vocabulary

When naming a domain concept, use the term defined in the relevant `CONTEXT.md`. If the concept is missing, note the gap for domain modeling.

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly instead of silently overriding it.
