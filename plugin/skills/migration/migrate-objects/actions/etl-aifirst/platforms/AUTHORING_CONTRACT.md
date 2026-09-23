# Platform-table authoring contract

Create `platform_table.json` for the requested platform by reading the source document and the
non-target prior-art tables in this view. You may also write `authoring_notes.md`.

The JSON table is provisional, but it must be executable by the deterministic identification
framework:

- `platform` must exactly equal the requested platform identity in `REQUEST.md`.
- Follow the same top-level and nested data shapes demonstrated by the prior-art tables.
- Describe source vocabulary only in the table. Do not assume changes to framework code.
- Every `structure.levels` entry must identify records through structural queries and stable keys.
- Every record in the projected document must be accounted for as an identified element, a keyless
  level match, a named exclusion, or an inventoried unknown.
- Exclusions must be named, deterministic, and explain why the matched records are not elements.
- Dispatch, role, edge, naming, port, type, expression, and residue policies must be explicit.
- Prefer an honest unsupported or residue outcome over invented semantics.
- Do not copy a prior-art platform identity or claim source behavior not supported by the document.

## Six things the consumers require that the shapes above do not show

Each of these was authored wrong by a table that satisfied every rule above, and each cost a
downstream failure that named a symptom far from its cause. Prior art demonstrates all six, but
only for the platforms that already needed them, so reading shapes alone will not surface them.

**`kind_attr` reads one flat attribute on the element node.** It is `node.get(name)`, so an
attribute one level below the node — Alteryx keeps the tool kind in `GuiSettings/@Plugin` — does
not resolve and every element dispatches as unknown. Hoist a descendant attribute onto the node
with a `LIFT_XML` rule first, then name the lifted attribute in `kind_attr`.

**A connection's endpoints are rarely children of either endpoint.** Every platform here states
its dataflow in a third element that names both sides — an Alteryx `<Connection>` with
`Origin/@ToolID` and `Destination/@ToolID`, a Pentaho `<hop>`, an SSIS `<path>` — so an author
that looks for the downstream reference underneath the upstream element finds nothing and matches
no connection at all. Those endpoint attributes usually sit one level below the connection too, so
they need lifting before `from_field_attr`/`to_field_attr` can read them. A representation with
elements and no edges is refused: nothing downstream can order or wire it, and it is the one
defect whose symptom appears three stages later as a consumer that hydrated nothing.

The declaration path is exact: lifting is a document front-end, so rules belong only at
`structure.document_model.lift_rules`, and `structure.document_model.kind` must be `LIFT_XML`.
Putting `lift_rules` at the table root, at the `structure` root, or inside a level/edge level is
ignored configuration and is rejected even if the canonical list also exists. Rules at
`structure.document_model.lift_rules` are themselves inactive unless `kind` is `LIFT_XML`; a
missing kind, `XML`, or a non-LIFT kind such as `CHILD_TEXT_XML` will not apply them. COPY rules
use `on_tag`, `from_child`, `from_attr`, and `onto_attr` — not `xpath`/`attr`/`as`. This generic
example lifts child endpoint attributes onto the edge element that the framework reads (the names
are illustrative, not platform vocabulary):

```json
{
  "structure": {
    "document_model": {
      "kind": "LIFT_XML",
      "lift_rules": [
        {
          "on_tag": "FlowLink",
          "from_child": "SourceEndpoint",
          "from_attr": "ref",
          "onto_attr": "from_ref"
        },
        {
          "on_tag": "FlowLink",
          "from_child": "TargetEndpoint",
          "from_attr": "ref",
          "onto_attr": "to_ref"
        }
      ]
    },
    "edge_levels": [
      {
        "name": "flow-links",
        "xpath": ".//FlowLink",
        "endpoint_kind": "PORT_REF",
        "from_attr": "from_ref",
        "to_attr": "to_ref",
        "label_attr": null
      }
    ]
  }
}
```

For a source fragment such as
`<FlowLink><SourceEndpoint ref="n1"/><TargetEndpoint ref="n2"/></FlowLink>`, those rules copy
`SourceEndpoint/@ref` and `TargetEndpoint/@ref` onto the in-memory `FlowLink`; they do not rewrite
the source. `from_attr`/`to_attr` (or the field variants required by the chosen endpoint kind) then
name the lifted attributes because edge reads are flat. COPY rules are one child level deep and
use `on_tag`, `from_child`, `from_attr`, and `onto_attr`; the first non-empty rule for an
`onto_attr` wins.

**A transform normalises one reading; it must not merge two.** `UNQUALIFIED_TAIL` exists because
SSIS states a destination as `[dbo].[CUSTOMER_SUMMARY]` and the unqualified tail is the table, so
it splits on `.` and takes the last part. Declared on a value that is not a dotted identifier it
silently means something else: on `\\fileshare\ETL\Orders_Online.csv` the part after the last dot
is the file EXTENSION, and every file element in the document resolves to the relation `csv`. The
models stay individually correct and all read the same table, which is why this surfaces only in
the executor, as columns missing from a relation that three different files were merged into.
Acceptance refuses a transform that maps two distinct readings onto one value; if a field needs
the file name, read the part the document actually states.

**One fact rule per distinct source reading.** The emitter asserts that no two `no_slot_facts`
rules read the same source location, and rejects the whole table when two do. Two rules that
happen to share an XPath are a duplicate reading, not two facts.

**`column_propagation` decides whether a mapped element resolves its upstream at all.** Omit it
and the mode is `NONE`: an element that declares no output columns projects nothing, its
successor's column-driven source lookup returns null, and the emitted model reads
`{{ ref('int_NOT_FOUND') }}` — a dbt1005 at run time, two floors from the empty column list that
caused it. Declare `ACCUMULATE` when an element states only the columns it ADDS to an inbound
buffer, `FILL_WHEN_UNDECLARED` when a declared list is exhaustive and only its absence means
"whatever arrives here". `stop_at_kinds` is for elements that genuinely define a new output shape,
and listing a kind that declares no output shape of its own is worse than omitting it: the walk
stops at an element that states nothing, and every mapped successor is starved of the columns it
needed. An aggregate belongs there. A union that declares no output port site does not.

**The platform identity must match a source-element counting rule.** `coverage_gate.RULES` keys
Gate A's denominator by the identity string, and an identity with no rule leaves coverage
UNMEASURED for the whole run — not failed, not passed, unmeasurable, which is the one outcome this
pipeline treats as worse than a bad number. The keys are `SqlServerIntegrationServices`,
`InformaticaPowerCenter`, `PentahoDataIntegration`, `IbmInfoSphereDataStage` and `alteryx`. They
are not uniformly cased and are not derivable from the platform's name; use the requested identity
in `REQUEST.md` verbatim, and if it is a platform with no rule yet, say so in
`authoring_notes.md` rather than inventing a near miss.

## `dialect.expression_translation` — optional, and all-or-nothing

Omit this block and every expression is emitted by the **verbatim flat path**: each scanned token
is re-emitted as written, column references are resolved, nothing else is rewritten, and the slot
carries residue naming what was not understood. That is the correct choice for a platform whose
expressions you have not modelled, and it is what most tables here do.

Declare the block and you turn on a structural translator over the same token stream — ternaries,
operator precedence levels, unary forms, casts, and function calls. Everything it knows comes from
this block: it holds **all** source-language vocabulary (operator spellings, type names, function
names, index bases, format letters) because the reader contains none and branches on no platform.

Keys the reader looks for: `argument_separator` and `function_translations` (required once the
block exists), plus `null_literal`, `max_expression_span_depth`, `ternary_operators`,
`null_comparison_rewrite`, `binary_operator_levels`, `operator_residue_notes`,
`unary_operator_forms`,
`string_concat_operator`, `string_concat_target_operator`, `string_concat_detection`,
`string_value_class`, `numeric_value_class`, `value_class_by_datatype`,
`leaf_passthrough_characters`, `template_operand_delimiters`, `call_name_strip_prefixes`,
`cast_types`, `cast_value_classes`,
`date_part_literals`,
`date_format_pattern_map`, `date_format_letter_characters`, `date_format_literal_characters`,
`date_format_quote_character`, `date_format_quoted_literal_template`. **Any other key is rejected**,
because every reader here is a `.get`: a misspelled key is not a smaller declaration, it is a
constraint that silently does not apply on a path whose entire output is plausible-looking SQL.

An **overloaded additive operator** — one spelling that is arithmetic on numbers and concatenation on
strings, declared as `string_concat_operator` with its target as `string_concat_target_operator` — is
resolved one **pairwise step** at a time, left to right, which is what `string_concat_detection:
"typed_operands_left_associative"` names. So every source statement of a value class matters, and
there are four: `value_class_by_datatype` over a referenced column's declared type,
`function_translations[*].returns` for a call this table translates, `cast_value_classes` for an
explicit cast, and the fold itself for a sub-chain or a parenthesised group. A step whose two classes
are both stated is emitted as one reading or the other; a step on the overloaded operator the table
cannot read is emitted as the source spelling **and carries a residue reason**, because those are the
cases with two readings and nothing to choose between them. There are two of them, and they are
reported separately because the author's fix differs: a side the table states **no** class for means
declare the datatype, while two classes that are both stated and give the operator **neither** reading
— a boolean and a number, a date and a number — means the source expression itself needs a decision.
Leaving a class undeclared is therefore safe, and declaring a wrong one is not. `cast_value_classes` keys must all
name declared `cast_types`, or the class is authored for a cast the reader never recognises.

**Write every template as if its `{N}` received a bare operand, and the reader will make that
true.** One `{N}` — in a `function_translations[*].template`, in a `cast_types` entry, in a
`unary_operator_forms` entry — is spliced by ONE substitution site, which parenthesises the operand
unless it is already a single value (one primary, or one numeric literal) or unless the placeholder
sits between two of the characters `template_operand_delimiters` declares. That set must contain the
declared `argument_separator`, since a placeholder between two separators is delimited by
construction; `(` and `)` belong there too. So `F({0}, {1})` never gains a parenthesis, while
`({1} * {2})` and `{0} IS NULL` group whatever they receive. Do not hand-parenthesise a placeholder
in a template to compensate — the guard already applies, and the second pair of parentheses is
noise on every call.

**`operator_residue_notes`** is keyed by a **source operator spelling** and states a divergence that
survives translating it: the note is attached once per distinct operator wherever a level splits on
it, including inside a template's operands. Use it for an operator whose target spelling is right and
whose *meaning* is not exactly the source's — integer division truncating toward zero in the source
but not in the target is the case it was authored for, where the operands' run-time types decide and
the document does not state them. Every key must name an operator some `binary_operator_levels` level
declares, or the note is never attached to anything. Keep a note free of `; `, which separates one
residue reason from the next.

**Two adjacent values with no operator between them are declined, not joined.** `string_value_class`,
`numeric_value_class` and `leaf_passthrough_characters` are what let the reader tell one leaf value
from the next, and a run of them with nothing declared in between is a source the lexer could not
read: it crosses **verbatim, in the source's own spelling, with a residue reason**, rather than being
re-quoted or folded into a single value the source never stated. This costs you nothing to declare and
is the reason a mis-lexed `1 2` cannot ship as `12`.

**A documentation string must never sit inside a map the reader looks a source value up in.** Every
key of `cast_types`, `cast_value_classes`, `date_part_literals`, `date_format_pattern_map` and
`function_translations` is
DATA — a source cast type, a source date part, a source pattern run, a source function name — so an
inline `"_comment"` is reachable as data. Declare it as a sibling `"_<key>_comment"` instead. A
`_`-prefixed key is skipped everywhere the block is read and validated.

One `function_translations` entry is keyed by the source call name **after**
`call_name_strip_prefixes` has been applied, and the key must be spellable as one scanned identifier
(a letter or `_`, then letters, digits, `_`, and `expression_syntax.identifier_extra_chars`) or no
call can ever match it. It may declare:

| key | meaning |
| --- | --- |
| `template` | required; the target spelling, with `{N}` naming source argument N |
| `arity` | required; the EXACT argument count. A call stating any other count is emitted untranslated |
| `returns` | this call's value class, for resolving an overloaded operator around it |
| `date_part_args` | argument positions holding a source date-part literal, resolved via `date_part_literals` |
| `date_format_args` | argument positions holding a source date/time pattern, resolved via `date_format_pattern_map` |
| `argument_adjustments` | per-placeholder linear correction: `offset`, or `source_index_base`+`target_index_base`, plus optional `argument_coefficients` over source positions. Integer-literal arguments fold into the constant; anything else is emitted as explicit arithmetic. An integer literal below the declared `source_index_base` is one the SOURCE rejects, and the shift would map it onto an index the target accepts, so the correction is still emitted and the literal is named in residue |
| `unused_arguments` | positions the translation does not represent, each with the reason, emitted as residue |
| `residue_note` | a divergence that survives translation, emitted as residue on every call |

**Every argument position below `arity` must be accounted for exactly once** — reached by a template
placeholder, referenced by an `argument_adjustments` coefficient, or declared in `unused_arguments`
with a non-empty reason. The validator refuses an entry that leaves one out, because that entry
renders as a translated call with one of the source's arguments having no effect on the result and
nothing in the slot naming the loss. A translation that cannot be written faithfully must **decline**
— it is emitted with its call name and shape unchanged and a residue reason naming the specific
cause — never fitted to the template by dropping or inventing an argument.

Write JSON only to `platform_table.json`. The caller validates the table, runs deterministic
identification over the source, and builds the representation before accepting it. A
representation that builds is not yet one a consumer can use, so acceptance also asks that the
document's elements be wired to each other and that at least one of them arrive at a kind —
whether a translated kind or an honestly degraded one.

## If your table comes back

The validator reports the FIRST failure it finds, and you may be handed your own table back with
that message and asked to fix it. When that happens the file is unchanged and still in this
directory: repair the specific defect named and rewrite it. Expect to be told about a later
failure next — that is the validator working forward, not your fix being rejected — and do not
restructure anything it has not objected to. If a message names a key or a block this document
did not prepare you for, that is a gap in this document; note it in `authoring_notes.md` so it
stops costing the next author an attempt.
