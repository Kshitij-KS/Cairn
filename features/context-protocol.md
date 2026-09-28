---
title: Context Protocol
type: feature
status: live
owner: __OWNER__
covers: ["scripts/mem.py"]
aliases: ["mem", "mem load", "entry protocol", "recall", "trials"]
tags: [feature]
level: L1
confidentiality: internal
created: 2026-09-23
updated: 2026-09-28
---
# Context Protocol

## Card
Context Protocol is the reader: `mem load` gives an agent the core, resolves which feature an ask is about, picks a mode, loads that mode's scope by dependency direction, caches it per session and writes one bundle; the same tool records claims, gaps, trials and retrieval evals.

## Contract
`mem load` exit codes: 0 loaded, 2 ambiguous (ask one question), 4 not permitted, 5 invalid. It never loads restricted notes for a person without restricted_read. It imports every parser from the guard, so reader and enforcer cannot disagree about a note.

## Observations
- [fact] The feature map is computed on every load, not stored, so it cannot drift from features/ ^76faba
- [fact] Explain asks that name no feature resolve to a decision; orient adds a confidently resolved feature's card; a symptom with no intent word means debug ^a1d26e
- [fact] Recall relevance is IDF-weighted over claim texts ^b8fa22
- [fact] When the kind of task or the feature is unclear, mem load asks the person with ranked options instead of guessing; mem asks reports how often the guesses were corrected ^16bd4f
- [fact] A near-tie between two features makes mem load ask which one, plan mode included; orient shows both cards ^aa532e
- [fact] Review loads the target's card and full contract, not its body; explain follows the whole supersede chain ^b28f60
- [fact] Past 40 features the bundle's feature map lists the ones near the ask and names the rest ^665a97
- [fact] The rerun line is shell-inert: only words and plain punctuation of the ask survive in it ^934f06
- [fact] Evals run without the runner's pins and mutes, and a trial fails eval --trial if it removes a passing eval or adds a failing one ^d7ddd7
- [fact] Every script prints characters the console cannot encode as escapes (backslashreplace), so a non-ASCII note title never ends a Windows run in UnicodeEncodeError ^c96d8d

## Relations
- depends_on [[Memory Guard]]
- part_of [[Core]]
- implements [[ADR-004 Context Protocol]]
