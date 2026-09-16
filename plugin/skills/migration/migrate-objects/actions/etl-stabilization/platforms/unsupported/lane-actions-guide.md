# Lane Actions Guide (transformation equivalent for the unsupported profile)

Named platforms use a transformation guide to extract dataflow logic (sources, transforms,
column expressions) from a source file. This profile has no source file, so its transformation
counterpart is: **what is this profile allowed to do with each brief item, per lane.**

This is a P0 contract document. The loop that actually executes it is `I-16b` (SS13.4 P1) —
this pack does not run brief-driven repairs yet. Do not implement an acting loop against this
guide as part of landing the pack; it only needs to exist and be correct.

## Allowed / forbidden actions per lane

Mirrors `etl-aifirst/scripts/remediation_brief.py`'s `ALLOWED_ACTIONS` — this profile must not
invent new verbs the brief-writer does not already use.

| lane | allowed actions | who they belong to |
|---|---|---|
| `conversion_emitter` | `fix_emitter_ref_resolution`, `emit_value_from_ir`, `re_run_migrator` | AI-First — **return to convert** |
| `conversion_ir` | `extend_identification`, `add_ir_sidecar`, `re_run_identify` | AI-First — **return to convert** |
| `stabilization_repair` | `repair_emitted_sql_under_profile`, `re_verify_gate_b` | this profile |
| `stabilization_harden` | `apply_platform_hardening_procedure` | this profile |
| `residual` | `file_aim_or_eng_ticket` | neither — register, do not silently pass |

Forbidden everywhere: `hand_edit_output_tree_outside_mechanisms`,
`invent_source_intent_without_pointer`.

## Rules

1. **`conversion_*` lanes are not this profile's job.** Recognize them, do not attempt a fix —
   hand back to convert. Acting on them here would duplicate AI-First's own remediator and risk
   fixing the same bug two different ways under two different names.
2. **`stabilization_repair` / `stabilization_harden` are the only lanes this profile touches.**
   Use only the brief's `intent_excerpt`, `element_ids`/`models`, and `pointers` as context. If an
   item's `intent_excerpt.source_says` is absent, there is no source/IR pointer to repair from —
   do not guess; re-file it as `residual` instead (SS13.3: "refuse repair without source/IR
   pointer when brief says so").
3. **`residual` means explicit, not silent.** Register it against the AIM/ENG channel the brief
   already names in `from[]`. A residual item must never be marked `stabilization` "completed" —
   `findings/61` SS14 ties CUR write timing to an honest ledger, not a clean-looking one.
4. **Re-verify, don't declare.** After acting on an item, re-check every id in its `reverify`
   list (or the fuller Gate B subset if the pack's step wiring already does that for named
   platforms). "Looks fixed" is not a re-verification.
5. **No open-ended SQL rewrite.** This profile fixes what the brief's `allowed_actions` license
   for the item at hand — it is not a general dialect-repair tool.
6. **Do not bake in Alteryx (or any named platform's) shapes.** Alteryx fixtures are how this
   pack's procedures get proven (`findings/61` SS13.4 P2), not how they get written. A rule that
   only makes sense for one tool belongs in that tool's own `platforms/<id>/` pack later, not
   here.
