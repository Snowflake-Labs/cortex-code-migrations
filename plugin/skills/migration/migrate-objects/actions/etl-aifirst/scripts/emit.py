"""Emit the producer IR JSON, plus per-field provenance for the fit score.

Schema target: AiFirstProducerIrHydrator.Hydrate -- nodes[{id,type,modelName,
element{$kind,Name,InputColumns,OutputColumns}}], edges[{from,to,label?}].

PLATFORM NEUTRALITY CONTRACT (added by the SSIS generalisation pass)
--------------------------------------------------------------------
No source-vocabulary literal appears in this file. The IR field names
($kind, Name, InputColumns, OutputColumns, Precision, Scale) DO appear -- they
are the contract, which is the same for every platform, and they are the one
thing that is legitimately hardcoded here.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from identify import (CONTAINER_ROLES, DERIVED, MISSING, MODEL, NO_SLOT,
                      NO_SLOT_DETAIL_VOCABULARY, RESIDUE, SOURCE, TABLE,
                      Identification, Port, TableSection)
from source_sql import attach_source_sql

PLACEHOLDER_KIND = "UnsupportedTransformation"

#: The one `string_concat_detection` this file implements. A table declaring
#: anything else raises rather than silently getting this reading -- the same
#: "a declared value must be dispatched on" rule identify.validate_table exists
#: for, applied to the one key whose value decides whether an overloaded
#: operator becomes arithmetic or concatenation.
CONCAT_DETECTION_TYPED_LEFT_ASSOCIATIVE = "typed_operands_left_associative"


class _ExprCtx(NamedTuple):
    """Everything the structural expression translator carries down one
    expression, so a new one (`sdepth`) does not have to be threaded through ten
    signatures to be added.

    `depth` is local-variable INLINING depth, shared with `resolve`; `sdepth` is
    SPAN nesting depth, which is what bounds the recursive descent.

    `gaps` holds the index of every token the source SEPARATED from its
    predecessor by whitespace. The token list itself has whitespace dropped
    (`resolve`), because adjacency is what the structural readers match on -- but
    dropping it also destroys the one thing that distinguishes a numeric literal
    spelled over several tokens (`1.5`) from two literals written side by side
    (`1 . 5`), and the adjacency check in `_translate_leaf_span` is the reader
    that needs it back.
    """
    el: Any
    rename: dict
    by_lower: dict
    connected_in: set
    depth: int
    et: dict
    sdepth: int = 0
    gaps: frozenset = frozenset()

    def deeper(self) -> "_ExprCtx":
        return self._replace(sdepth=self.sdepth + 1)


def table_data_only(value):
    """A table sub-object with its `_`-prefixed DOCUMENTATION keys removed, recursively.

    Every checked-in table states its notes as `_`-prefixed keys, and nearly all of
    them sit BESIDE the block they describe. The ones authored INSIDE a lookup map
    share that map's namespace with data, and the maps under
    `dialect.expression_translation` are keyed by SOURCE SPELLINGS -- a cast type, a
    date-part literal, a function name -- so a source expression can NAME the note and
    get it back. MEASURED on the reviewed table, which held one inside `cast_types`
    and one inside `date_part_literals`: `(_comment) src.A` emitted the cast-type
    paragraph as that column's whole Expression, and
    `TalendDate.addDate(src.D, 1, "_comment")` emitted
    `DATEADD(<the date-part paragraph>, 1, src.D)`.

    Stripped once, at the block, rather than at each of a dozen lookup sites, so a map
    added later is covered the day it is added. The section's location is preserved,
    since a missing key must still name the block it was read from.
    """
    if isinstance(value, dict):
        stripped = {k: table_data_only(v) for k, v in value.items()
                    if not (isinstance(k, str) and k.startswith("_"))}
        return (TableSection(stripped, value.table_path)
                if isinstance(value, TableSection) else stripped)
    if isinstance(value, list):
        return [table_data_only(v) for v in value]
    return value


def render_detail(rule: dict, tpl: str, values: dict) -> str:
    """Render a table-authored `detail` template against a CLOSED keyword set.

    Two jobs, and the first is the reason this is a function rather than three
    `tpl.format(...)` calls. `identify.validate_table` rejects a template naming anything
    outside `NO_SLOT_DETAIL_VOCABULARY[rule['from']]`, which is only sound while that
    declaration and the keywords passed HERE say the same thing. A framework change that
    adds a keyword to a call site and forgets the declaration would make the validator
    reject legal tables; one that removes a keyword would make it accept a template that
    crashes at emission. So the parity is asserted rather than trusted -- the declaration
    is the check, and this keeps the check honest.

    The second job is the message. A template that slips past validation must still not
    surface as a bare `KeyError` naming one word and no rule."""
    declared = NO_SLOT_DETAIL_VOCABULARY[rule["from"]]
    assert set(values) == set(declared), (
        f"{rule['from']} detail vocabulary drifted: identify.py declares "
        f"{sorted(declared)}, emit.py supplies {sorted(values)}. "
        f"identify.validate_table checks author templates against the declaration, so "
        f"the two must agree.")
    if not tpl:
        return ""
    try:
        return tpl.format(**values)
    except KeyError as ex:
        raise ValueError(
            f"no_slot_facts[{rule.get('id')!r}].detail names {ex.args[0]!r}, which its "
            f"{rule['from']} formatter does not supply. It may name only "
            f"{list(declared)}.") from ex


# FRAMEWORK CHANGE 66: THE HYDRATOR'S CONTRACT, CHECKED BEFORE WE HAND IT A KIND.
#
# Mirrors the `kind switch` in
# `../callable-entrypoint/Producer/AiFirstProducerIrHydrator.cs:254-330`. That switch is
# the SOURCE OF TRUTH; this is a guard in front of it, and a kind added there must be
# added here or it will be refused (which is the safe direction).
#
# WHY THIS EXISTS. A sidecar-supplied `$kind` used to be promoted unchecked, on the
# reasonable-sounding ground that the model had asserted it. Two ways that loses a
# document rather than an element:
#
#   1. A kind the switch has no arm for -- `RouterTransformation`, `JoinTransformation` --
#      falls through to its `_ => throw`.
#   2. An accepted kind whose REQUIRED payload is absent: `FilterTransformation` with no
#      `FilterConditions` reaches `RequiredString`, which throws.
#
# Either throw happens during hydration of ONE element and takes THE WHOLE DOCUMENT with
# it -- every other element, every edge, the lineage, the reports. The blast radius is the
# reason this is checked here and not left to the hydrator's own exception.
#
# This is the SAME RULE the deterministic path already follows: a payload-dependent kind
# whose required field cannot resolve DEGRADES rather than emitting a hollow element
# (`element_fields`, FRAMEWORK CHANGE 47). It held for table-declared kinds and not for
# sidecar-declared ones -- one rule honoured in one place and not its sibling, which is
# the shape of defect this project keeps finding. Unreachable while sidecars were
# hand-authored; reachable the moment `sidecar_producer.py` began producing them.
#
# `sidecar_producer.py` carries its own `KIND_CONTRACT` so it can refuse a bad answer at
# production time and re-prompt. That is a DIFFERENT job -- refuse early, before the file
# exists -- and this guard must not be deleted in favour of it: a sidecar can be
# hand-edited, produced by an older build, or written by something that is not our
# producer at all. Both copies cite the hydrator; the hydrator is what settles a
# disagreement.
HYDRATOR_KIND_CONTRACT = {
    "SourceQualifier": (),
    "ExpressionTransformation": (),
    "FilterTransformation": ("FilterConditions",),
    "TargetTransformation": ("TableName",),
    "UnsupportedTransformation": (),
}


@dataclass
class Slot:
    """One fit obligation: a field the contract wants, or a fact with no field."""

    element: str
    path: str          # dotted path into the emitted JSON, or the source fact name
    provenance: str
    where: str         # xpath, table rule id, or algorithm name
    detail: str = ""

    @property
    def satisfied(self) -> bool:
        return self.provenance in (SOURCE, TABLE, DERIVED)


# ---------------------------------------------------------------------------
# expression handling: a hand-rolled scanner over the expression string.
# Deliberately NOT a regex. Identifiers resolve against a CLOSED set of port
# names read from the document; delimited references resolve against a CLOSED
# set of column identities read from the document.
#
# FRAMEWORK CHANGE 19: v1 hardcoded the single-quote string literal and knew no
# delimited-reference form. SSIS uses double quotes and wraps every column
# reference in #{...} around a full lineage id, which the v1 scanner would have
# shredded into a dozen bogus identifiers.
# ---------------------------------------------------------------------------

_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")


def scan(text: str, quotes=("'",), ref_delims=None, extra="$", escape=None
         ) -> list[tuple[str, str]]:
    """-> [(kind, lexeme)] where kind is 'ident', 'str', 'str_open', 'ref', 'other'.

    `escape` is the platform's own in-literal escape character, declared by
    `expression_syntax.string_escape_char` and None for a platform that states
    none -- so a table that says nothing lexes exactly as it did before. Without
    it `"a\\"b"` closes at the ESCAPED quote, and every token after it is read in
    the wrong context.

    'str_open' is a literal the text never closes. It carries the same lexeme a
    closed one would, so joining the lexemes is still lossless, and it is a
    DISTINCT kind because a consumer that rewrites a literal (re-quoting it for
    another dialect) must be able to refuse: rewriting a mis-lexed literal turns
    a lexing limit into corrupted output.
    """
    body = _IDENT_START | set("0123456789") | set(extra)
    out: list[tuple[str, str]] = []
    open_d, close_d = (ref_delims or (None, None))
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if open_d and text.startswith(open_d, i):
            j = text.find(close_d, i + len(open_d))
            if j == -1:
                out.append(("other", c))
                i += 1
                continue
            out.append(("ref", text[i + len(open_d): j]))
            i = j + len(close_d)
        elif c in quotes:
            j = i + 1
            while j < n and text[j] != c:
                if escape and text[j] == escape:
                    j += 2
                    continue
                j += 1
            out.append(("str" if j < n else "str_open", text[i: j + 1]))
            i = j + 1
        elif c in _IDENT_START:
            j = i
            while j < n and text[j] in body:
                j += 1
            out.append(("ident", text[i:j]))
            i = j
        else:
            out.append(("other", c))
            i += 1
    return out


class Emitter:
    def __init__(self, idn: Identification):
        self.idn = idn
        self.table = idn.table
        self.pol = self.table["port_policy"]
        self.syn = self.table["expression_syntax"]
        # None for every platform that declares no such block, which is what gates the
        # structural expression translator. Documentation keys are stripped here, once
        # -- see table_data_only for the defect that requires it.
        self.et = table_data_only(self.table["dialect"].get("expression_translation"))
        self.slots: list[Slot] = []
        # (ir_field, raw, transformed) per element_fields read that a declared transform
        # rewrote. Kept because a transform is the one place a table can destroy the
        # distinction between two elements, and the loss is invisible afterwards: only
        # the OUTPUT reaches the IR. See collapsed_transforms.
        self.transformed_reads: list[tuple[str, str, str]] = []
        self.ai = self._load_sidecar()
        self._assert_fact_rules_distinct()
        self._assert_attr_residue_usable()

    def collapsed_transforms(self) -> dict[tuple[str, str], list[str]]:
        """Transformed fields where two or more distinct source readings became one value.

        A table declares a transform to normalise a reading, not to merge readings, so
        this is always information the table destroyed. MEASURED on the blind Alteryx
        table of 2026-08-24: `TableName` took `UNQUALIFIED_TAIL`, a dotted-identifier
        stripper meant for `[dbo].[CUSTOMER]`, and applied it to
        `\\\\corp-fileshare\\ETL\\Sales\\Orders_Online.csv`. The tail after the last dot
        is the file EXTENSION, so all three inputs and all three outputs resolved to one
        relation named `csv`, every model read `source('raw', 'csv')`, and two of them
        selected columns that relation could not have.
        """
        by_value: dict[tuple[str, str], set[str]] = {}
        for ir_field, raw, value in self.transformed_reads:
            by_value.setdefault((ir_field, value), set()).add(raw)
        return {key: sorted(raws) for key, raws in by_value.items() if len(raws) > 1}

    # -- FRAMEWORK CHANGE 66 (a): TWO RULES, ONE READING ---------------------

    def _fact_read_key(self, rule: dict) -> str | None:
        """A canonical description of WHERE a no_slot_facts rule reads from.

        Two rules with the same read key read the SAME value out of the SAME
        document node, so at most one of them can be a distinct obligation. The
        key is computed from the table alone and contains no source vocabulary:
        the site xpath and attribute names come from the platform's own
        `attr_site` declaration.

        WHY ELEMENT_ATTR NEEDS TRANSLATING. `record_no_slot_facts`'s ELEMENT_ATTR
        branch does not read an XML attribute -- it reads `el.table_attrs`, the
        property bag that `_read_table_attrs` fills FROM the def site's declared
        `attr_site`. So on a platform whose properties are child name/value pairs,
        `ELEMENT_ATTR attr=X` and a CHILD_* rule pointed at that same pair are the
        same reading spelled two ways, and nothing detected it.

        Returns None for rule kinds whose target is not a single named node
        (GROUP, PORT, FIELD_EDGE, HARVEST, CONTAINER, ATTR_RESIDUE): those fan out
        over many keyed facts and two of them cannot silently be one obligation.
        ATTR_RESIDUE additionally cannot COLLIDE with a named rule by construction --
        it is the complement of exactly the set this method's callers describe -- so
        `_assert_attr_residue_usable` is what guards it instead.
        """
        src = rule["from"]
        if src in ("ELEMENT_ATTR", "DEF_SITE_ATTR"):
            at = self._attr_site()
            if at is None:
                return f"SELF_ATTR/@{rule['attr']}"
            if at.get("value_from") == "SELF_ATTRS":
                return f"SELF_ATTR/@{rule['attr']}"
            site = f"{at['xpath']}[@{at['name_attr']}='{rule['attr']}']"
            if at.get("value_from") == "TEXT":
                return f"CHILD_TEXT {site}/text()"
            return f"CHILD_ATTR {site}/@{at.get('value_attr')}"
        if src == "CHILD_TEXT":
            return f"CHILD_TEXT {rule['xpath']}/text()"
        if src == "CHILD_TEXT_TEMPLATE":
            parts = ",".join(f"{k}={v}" for k, v in sorted(rule["parts"].items()))
            return f"CHILD_TEXT_TEMPLATE {parts}/text()"
        if src == "CHILD_ATTR":
            return f"CHILD_ATTR {rule['xpath']}/@{rule['attr']}"
        return None

    def _attr_site(self) -> dict | None:
        """The declared property site, from whichever def site declares one.

        Read across every def site rather than only the default, because the bag
        the ELEMENT_ATTR census branch consults is filled by whichever site the
        element's kind resolves to.
        """
        st = self.table["structure"]
        cands = [st.get("self_def_site") or {}]
        cands += list((st.get("def_sites") or {}).values())
        for c in cands:
            if isinstance(c, dict) and c.get("attr_site"):
                return c["attr_site"]
        return None

    def _assert_fact_rules_distinct(self) -> None:
        """Raise when two no_slot_facts rules are the same reading.

        MEASURED DEFECT THIS CATCHES, and the reason it raises rather than warns.
        `platform_ssis.json` declared `open_rowset` (ELEMENT_ATTR @OpenRowset) and
        `oledb_open_rowset` (CHILD_TEXT ./properties/property[@name='OpenRowset']).
        The second is the rule `element_fields` promotes into `element.TableName`,
        and promotion suppresses only the promoted id -- so `!open_rowset` was
        still reported as an UNMET obligation citing the same location, with the
        same value, on an element whose TableName was populated from it. A FALSE
        unmet obligation: the document states the fact and the IR carries it.

        It raises because a table typo of this shape is invisible in the output --
        it looks exactly like a genuine coverage gap, which is the direction this
        framework must never fail in.
        """
        seen: dict[str, str] = {}
        for rule in self.table["no_slot_facts"]:
            k = self._fact_read_key(rule)
            if k is None:
                continue
            if k in seen:
                raise ValueError(
                    f"no_slot_facts rules '{seen[k]}' and '{rule['id']}' are the SAME "
                    f"reading ({k}). Two ids for one document value make one of them a "
                    f"FALSE unmet obligation: the census reports the un-promoted id as "
                    f"slotless while the promoted id fills an IR field from the same node. "
                    f"Delete one, or give them different sites.")
            seen[k] = rule["id"]

    def _load_sidecar(self) -> dict:
        """FRAMEWORK CHANGE 61: THE MODEL-AUTHORED SIDECAR — tier 2 of the fallback ladder.

        WHY THIS EXISTS. Leaning on the engine's IR made the IR a GATE on generation
        rather than a carrier for it. An element kind outside the vocabulary, a predicate
        no rule kind can scrape, an expression in a dialect no translator lowers -- each
        terminated in a NULL placeholder. On an unsupported platform every one of those is
        the expected case, so "nothing" was the normal output of an AI-first migrator.
        That is the wrong outcome: imperfect-and-marked beats absent.

        THE SIDECAR IS WHERE THE MODEL'S ANSWER LANDS. `<document>.ai.json`, keyed by
        element name, supplying exactly the things deterministic identification cannot get:

            {"elements": {"<element name>": {
                "$kind": "ExpressionTransformation",        # a kind the table has none for
                "FilterConditions": "BirthYear >= 1990",    # a predicate no rule can scrape
                "OutputColumns": [                          # expressions in Snowflake dialect
                    {"Name": "FullName", "Expression": "..."}]}}}

        A FILE AND NOT AN INLINE CALL, for three reasons that matter more than convenience:
        it is inspectable and diffable, so a reviewer can see exactly what the model
        asserted; it is replayable, so a run is reproducible without re-invoking a model;
        and it keeps the deterministic half deterministic -- identification never depends
        on a network call.

        EVERY FACT FROM HERE IS RECORDED AS `MODEL` PROVENANCE, never SOURCE. The document
        does not say these things. That distinction is the entire reason this framework
        tracks provenance at all, and collapsing it to make the fit number look better
        would defeat the purpose of having the number.
        """
        path = Path(str(self.idn.xml_path) + ".ai.json")
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("elements") or {}

    def ai_for(self, el) -> dict:
        """The sidecar entry for an element, matched on its display name then its key."""
        if not self.ai:
            return {}
        for key in (self.element_name(el), getattr(el, "name", None), el.where):
            if key and key in self.ai:
                return self.ai[key]
        return {}

    # -- naming ------------------------------------------------------------

    def model_name(self, el) -> str:
        """FRAMEWORK CHANGE 20: modelName came from the element key, because in
        Informatica the key IS the human name. An SSIS component key is a
        backslash-delimited path (`Package\\Data Flow Task\\Derived Column`), so
        the naming source and whitespace handling must be table-driven.

        FRAMEWORK CHANGE 57: a model name had no notion of the scope it lives in.
        On DataStage that was a MEASURED data-loss defect, not a hazard: one .dsx
        holds 12 jobs, stage display names repeat across them, and 29 data-flow
        nodes collapsed onto 9 names. `DbtModelsWriter` wraps its write in
        try/catch and only logs, so 20 models were silently overwritten -- and the
        SQLite-backed ObjectReferences calculator deduplicated the same collision
        down to 6 of 18 lineage rows. `qualify_with_container` prefixes the
        enclosing element's name, which is the only scope the DOCUMENT states."""
        np = self.table["naming_policy"]
        name = el.display_name if np.get("name_from") == "DISPLAY_NAME" else el.instance_name
        qualify = np.get("qualify_with_container")
        if qualify and el.container:
            # The container's own name, normalised the same way, so the two halves
            # of the qualified name cannot disagree about case or whitespace.
            name = qualify["separator"].join([self._normalise(el.container, np),
                                              self._normalise(name, np)])
            return name
        return self._normalise(name, np)

    @staticmethod
    def _normalise(name: str, np: dict) -> str:
        if np["lowercase"]:
            name = name.lower()
        sep = np.get("replace_whitespace_with")
        if sep is not None:
            name = sep.join(name.split())
        return Emitter._sanitise(name, np)

    @staticmethod
    def _sanitise(name: str, np: dict) -> str:
        """FRAMEWORK CHANGE 58: whitespace was the only illegal character handled.

        MEASURED on Pentaho: the step `Dummy (do nothing)` produced the model name
        `dummy_(do_nothing)` and the transformation `safe-stop-gen-rows` kept its
        hyphens. Neither is a legal UNQUOTED Snowflake or dbt identifier, so both
        emit a model reference that does not compile.

        Every character outside the table's declared allowed set becomes ONE
        replacement character -- deliberately not a collapsed run, because
        collapsing merges `a--b` into `a_b` and merging two distinct names is the
        exact defect FRAMEWORK CHANGE 57 removed. A name that cannot START a bare
        identifier is PREFIXED rather than trimmed, for the same reason: prefixing
        is injective, trimming is not.

        Residual merges are still possible in principle (`a-b` and `a_b` both map to
        `a_b`), so this rule is NOT trusted on its own -- `emit` asserts injectivity
        over the whole document and fails loudly if two names collapse into one.
        """
        rule = np.get("sanitize_identifier")
        if not rule:
            return name
        allowed = set(rule["allowed_chars"])
        repl = rule["replace_illegal_with"]
        out = "".join(c if c in allowed else repl for c in name)
        if out and out[0] not in set(rule["allowed_leading_chars"]):
            out = rule["leading_prefix"] + out
        return out

    def node_type_of(self, el, role_prov: str) -> tuple[str, str, str]:
        """FRAMEWORK CHANGE 51: the role -> node.type lookup, made total.

        Returns (node_type, provenance, detail). A role the table maps keeps the
        provenance the caller computed (TABLE, or DERIVED when the role itself was
        derived from structure). A role the table does NOT map returns the declared
        placeholder with provenance MISSING, so `fit.score` counts the obligation
        and scores it zero -- the same treatment an unmapped element KIND gets. The
        emitter no longer decides anything here; the table does."""
        rmap = self.table["role_to_node_type"]
        if el.role in rmap:
            return rmap[el.role], role_prov, f"{el.role} -> {rmap[el.role]}"
        placeholder = rmap.get("unmapped_role_node_type")
        if placeholder is None:
            raise KeyError(
                f"role_to_node_type has no entry for role {el.role!r} and no "
                "'unmapped_role_node_type' fallback. Add the role, or declare the "
                "fallback -- the emitter will not choose a node type itself.")
        return placeholder, MISSING, (
            f"{el.role} -> {placeholder}: role_to_node_type states no mapping for "
            f"'{el.role}', so node.type asserts nothing")

    def is_orchestration_container(self, el) -> bool:
        """True when the table names this kind as a container, not a data-flow gap."""
        entry = self.table.get("kind_dispatch", {}).get(el.kind_raw)
        if isinstance(entry, dict) and entry.get("ir_kind") is None and not entry.get("degrade_to"):
            return True
        return (el.role or "").upper() in CONTAINER_ROLES

    def element_name(self, el) -> str:
        return (el.display_name if self.table["naming_policy"].get("element_name_from")
                == "DISPLAY_NAME" else el.instance_name)

    def ir_element_name(self, el) -> str:
        """element.Name as it reaches the IR/engine, not as a display label: engine
        translators print this value as a bare SQL correlation name (e.g.
        FilterTranslator's incoming-entity alias), so a platform whose element_name is
        not already a legal identifier (naming_policy.sanitize_element_name) gets it run
        through the same sanitize_identifier rule as model_name. ai_for()'s sidecar
        lookup keeps using the raw element_name() -- this helper is IR-assignment only."""
        name = self.element_name(el)
        np = self.table["naming_policy"]
        return self._normalise(name, np) if np.get("sanitize_element_name") else name

    # -- port classification ----------------------------------------------

    def is_output(self, p: Port) -> bool:
        return p.porttype in self.pol["output_porttypes"]

    def is_input(self, p: Port) -> bool:
        return p.porttype in self.pol["input_porttypes"]

    def is_local(self, p: Port) -> bool:
        return p.porttype == self.pol["local_variable_porttype"]

    # -- FRAMEWORK CHANGE 66 (b): WHERE InputColumns COME FROM ---------------

    def _input_columns_policy(self) -> str:
        """The table's declared mechanism for the RECEIVING column list.

        Defaulted to FIELD_EDGES so a table that says nothing keeps the
        pre-change behaviour byte-for-byte, and an undeclared value RAISES rather
        than silently emitting nothing -- the direction this framework must never
        fail in.
        """
        mech = self.pol.get("input_columns_from", "FIELD_EDGES")
        if mech not in ("FIELD_EDGES", "INPUT_PORTS", "NONE"):
            raise ValueError(
                f"port_policy.input_columns_from {mech!r} is not implemented. "
                "Declared mechanisms are FIELD_EDGES, INPUT_PORTS and NONE.")
        return mech

    def input_columns(self, name: str, el, by_lower: dict) -> list[dict]:
        """InputColumns, by the mechanism the PLATFORM declares.

        MEASURED DEFECT THIS FIXES. This was unconditionally FIELD_EDGES -- the
        list was built by walking inbound field-level lineage and reading the local
        port each edge lands on. Informatica states field lineage (CONNECTOR names
        both fields) and SSIS states it (an inputColumn carries the upstream
        outputColumn's lineageId), so on those two platforms it is right. A .dsx
        states NO field-level lineage at all: a link record names its Partner pin
        and nothing finer. So `idn.field_edges` is 0 on DataStage and
        `InputColumns` was structurally EMPTY on every element of every .dsx --
        29 of 29 nodes on MaskDemo.dsx, 4 of 4 on CustomerSummaryDerive.dsx.

        WHY THAT MATTERED EVEN THOUGH TRANSLATORS PROJECT FROM OutputColumns. Any
        verification that reads InputColumns read an empty list on this platform
        and passed, so the DataStage column check was weaker than it looked while
        appearing to pass -- the failure mode this whole spike exists to surface.

        THE EVIDENCE FOR INPUT_PORTS, and it is what decided this rather than
        declaring the field not-applicable. CustomerSummaryDerive.dsx STATES the
        receiving column list, on the element's own INPUT LINK RECORD, with a
        citable location for each column:
            V0S2P1 (CTrxInput)  FirstName, MiddleName, LastName, BirthDate
            V0S3P1 (CustomInput) FullName, BirthYear
            V0S4P1 (CustomInput) FullName, BirthYear
        The framework ALREADY READS all eight as INPUT ports -- `structure`
        declares three input port sites -- and the emitter then discarded every one
        of them because no field edge pointed at them. So this is not new data and
        not a derivation: it is a reading the producer was already making and
        throwing away. Provenance stays SOURCE for exactly that reason, cited at
        the column subrecord.

        NONE is declared where the platform states neither: a Kettle <hop> names
        two steps and no fields (a step's own <fields> are its OUTPUT schema), and
        an ADF dependsOn is orchestration order over activities that state no
        columns anywhere. Both measure 0 field edges AND 0 input ports today, so
        NONE is byte-identical for them -- it is declared to make the
        not-applicability a reviewable table entry instead of an accident of the
        algorithm.

        The `element.InputColumns` MISSING obligation is NOT retired by any of
        this. Where it fires it states a fact about the DOCUMENT -- a link in this
        direction and no column list on it -- and that fact is unchanged.
        """
        mech = self._input_columns_policy()
        inputs: list[dict] = []
        if mech == "NONE":
            return inputs
        if mech == "INPUT_PORTS":
            for p in el.ports:
                if not self.is_input(p) or self.is_local(p):
                    continue
                if self.excluded_group(el, p):
                    continue
                inputs.append(self.column_json(p, p.name, None))
                self.record_column_slots(
                    name, f"element.InputColumns[{len(inputs) - 1}]", p, None)
            return inputs
        for fe in self.idn.inbound(name):
            local = by_lower.get(fe.to_field.lower())
            if local is None:
                continue
            upstream_named = self.pol["input_column_naming"] == "UPSTREAM_FIELD"
            col_name = fe.from_field if upstream_named else local.name
            inputs.append(self.column_json(local, col_name, None))
            # INDEX FROM `inputs`, NOT FROM enumerate(inbound). The loop used
            # `enumerate`, so every field edge whose `to_field` resolved to no local port
            # advanced the index while `inputs` did not -- and from that point on the slot
            # path `element.InputColumns[i]` addressed a DIFFERENT column of the emitted
            # IR than the one whose reading it recorded. Neither fixture exercises the
            # skip today (measured: the path set is unchanged by this fix), which is the
            # only reason it was never wrong in an artifact; it is still an address
            # computed from the wrong sequence.
            self.record_column_slots(
                name, f"element.InputColumns[{len(inputs) - 1}]", local, None,
                name_where=fe.from_field_where if upstream_named else None)
        return inputs

    def excluded_group(self, el, p: Port) -> bool:
        """FRAMEWORK CHANGE 21: v1 had no notion that some output groups are not
        part of the projection. Every SSIS component carries an error output whose
        columns (ErrorCode, ErrorColumn) must not become derived columns.

        `exclude_unwired_output_groups` (Talend competence TK-02 follow-up) reads
        which group is real straight off the document's own wiring (a live outgoing
        `<connection>`), which is authoritative whenever the element states ANY
        usable outgoing edge label at all -- so it decides ALONE in that case.

        `exclude_port_groups_name_matches` (Talend competence TK-02) only runs as a
        FALLBACK, when the element states no wiring evidence whatsoever (tMap's
        reject output is a Studio NAMING convention, not an attribute, so there is
        no flag to fall back to either). A business table can share tMap's reject
        vocabulary as an ordinary word -- `fact_workorder_rejects`,
        `dim_rejectcodes` -- so the match is against a whole, delimiter-bounded
        token of the group's name (split on non-alphanumerics), never a raw
        substring: `reject_out` has a `reject` token and matches, `rejects` folded
        into `fact_workorder_rejects` is the token `rejects`, distinct from the
        declared `reject`/`rejects` patterns only when the compound name's tokens
        don't happen to coincide with one -- wiring, checked first, is what
        actually resolves that case when it states any edge at all.

        THE NAME PREDICATE NEVER FIRES ON AN ELEMENT'S ONLY GROUP. MEASURED on the
        34-item AdW2017 corpus: three tMaps (dim_rejectcodes, fact_purchase_rejects,
        load_fworkorderrejects_Copy) each declare exactly ONE <outputTables>, and its
        NAME is the real, sole target table -- a dimension of reject reason codes, a
        fact table of purchase-order rejections -- not a secondary catch-all flow
        beside some other "main" output. Excluding it emptied OutputColumns entirely,
        and this table's own `column_propagation.mode=FILL_WHEN_UNDECLARED` then
        silently BACKFILLED it from the upstream element's columns -- a fabricated
        mapping, exactly what this project's own conventions refuse to emit. A name
        match can only be trusted to mean "the OTHER output" when there provably is
        another one. THE WIRING PREDICATE SHARES THE SAME GUARD, for the same
        reason: an element's only group is definitionally the real target, wired or
        not stated as wired.
        """
        if p.group is None:
            return False
        g = next((g for g in el.groups if g["name"] == p.group), None)
        if g is None:
            return False
        flag = self.pol.get("exclude_port_groups_with_flag")
        if flag and g["flags"].get(flag):
            return True
        if self.pol.get("exclude_unwired_output_groups") and len(el.groups) > 1:
            labels = self._outgoing_group_labels(el)
            # `labels is None` means the element has NO usable outgoing edge label at
            # all -- absence of wiring EVIDENCE, not evidence that nothing is wired.
            # Treating it as "everything is stale" would empty OutputColumns exactly
            # the way the sole-reject-target bug above did, so this predicate falls
            # through to the name-match fallback below rather than guess.
            if labels is not None:
                return (g["name"] or "").lower() not in labels
        patterns = self.pol.get("exclude_port_groups_name_matches")
        if patterns and len(el.groups) > 1:
            tokens = re.split(r"[^0-9a-z]+", (g["name"] or "").lower())
            if any(pat.lower() in tokens for pat in patterns):
                return True
        return False

    def _outgoing_group_labels(self, el) -> set[str] | None:
        """Case-insensitive labels of every real outgoing edge from this element,
        or None when the element states no usable label at all.

        `element_edges()` already resolves a Talend <connection>'s `source`/`target`
        to the owning element (TK-01's `_owner_element_of`), so an edge whose `from`
        matches this element's resolved instance is one this element itself emits
        into -- and its `label` (connection/@label) is the SAME string as the
        `<outputTables>` group name it was drawn from, per this table's edge_policy.
        """
        resolved = self.idn.resolved_instance(el.instance_name)
        labels = {e["label"].lower() for e in self.idn.element_edges()
                  if e["from"] == resolved and e.get("label")}
        return labels or None

    # -- expression resolution --------------------------------------------

    def _scan(self, text):
        rd = self.syn.get("reference_delimiters")
        return scan(text, quotes=tuple(self.syn["string_quotes"]),
                    ref_delims=tuple(rd) if rd else None,
                    extra=self.syn.get("identifier_extra_chars", ""),
                    escape=self.syn.get("string_escape_char"))

    def _normalize_expression_syntax(self, value: str) -> str:
        """Rewrite a platform expression into SQL-ish delimiters via expression_syntax.

        I-19/SNOW-3936576: Alteryx FilterConditions carry [Field] refs and double-quoted
        string literals. Reuses the SAME tokenizer `resolve()` already runs Formula
        expressions through, so we do not invent a second grammar here.
        """
        parts = []
        for kind, lex in self._scan(value):
            if kind == "ref":
                parts.append(f'"{lex}"')
            elif kind == "str":
                parts.append("'" + lex[1:-1].replace("'", "''") + "'")
            else:
                parts.append(lex)
        return "".join(parts)

    def _divergence(self, out: list[str]) -> str | None:
        """FRAMEWORK CHANGE 22: the divergent-operator check was a literal
        two-character lookback for '|'. Operator length is now table-driven, which
        is what lets SSIS flag its single-character '+' concatenation."""
        div = self.table["dialect"]["syntactically_identical_semantically_divergent"]
        for ln in self.table["dialect"].get("divergent_operator_lengths", [1, 2]):
            if len(out) >= ln:
                op = "".join(out[-ln:])
                if op in div:
                    return f"operator '{op}': {div[op]}"
        return None

    def _resolve_ident_or_ref(self, kind, lex, el, rename: dict[str, str],
                              by_lower: dict[str, Port], connected_in: set[str],
                              depth: int) -> tuple[str, list[str], list[str]]:
        """One 'ref' or 'ident' token -> (text, residue_reasons, table_rules_applied).

        The single definition of port/local-variable/default-value resolution,
        shared by the flat per-token loop (every platform without
        `dialect.expression_translation`) and the structural Java-expression
        translator (TK-03, Talend only) -- so the two never drift into two
        readings of what an identifier resolves to.
        """
        if kind == "ref":
            up = self.idn._lineage_index.get(lex)
            if up is None:
                return lex, [f"unresolved column reference '{lex}'"], []
            return up[1], [], ["lineage_reference_resolution"]
        ci = self.syn.get("case_insensitive_resolution", True)
        target = by_lower.get(lex.lower() if ci else lex)
        if target is None:
            return lex, [f"unknown identifier '{lex}' (function or unresolved reference)"], []
        if self.is_local(target) and depth < 8:
            inner, r, tr = self.resolve(el, target, rename, by_lower, connected_in, depth + 1)
            return f"({inner})", r, tr + ["port_policy.inline_local_variables"]
        if self.is_input(target):
            if target.name in rename:
                return rename[target.name], [], []
            if target.name not in connected_in and target.default_value:
                dv = target.default_value
                pfx = self.table["default_value_policy"]["error_function_prefix"]
                if pfx and dv.startswith(pfx):
                    return target.name, \
                        [f"unconnected input '{target.name}' with error-function default"], []
                return dv, [], ["default_value_policy.literal_default_on_unconnected_input"]
            return target.name, [], []
        return target.name, [], []

    def resolve(self, el, p: Port, rename: dict[str, str],
                by_lower: dict[str, Port], connected_in: set[str],
                depth: int = 0) -> tuple[str, list[str], list[str]]:
        """Resolve column references to upstream projected names and inline local
        variables. Returns (text, residue_reasons, table_rules_applied).

        TK-03: a platform whose table declares `dialect.expression_translation`
        additionally gets its raw expression run through `_translate_span` -- ONE
        structural pass over the SAME token stream `_scan` already produces, so a
        Java function call, a ternary or a `+` used for string concatenation is
        rewritten into Snowflake SQL in the SAME walk that resolves column
        references. This is deliberate: it is never a second pass over
        already-emitted SQL, which is the #5117 regression (see
        `_normalize_expression_syntax`'s docstring and
        TestAlreadyFinalSqlIsNeverRescanned) -- a value that is ALREADY final SQL
        (the model-authored sidecar path, FRAMEWORK CHANGE 61 (d)) never reaches
        `resolve` or `_scan` at all.
        """
        if p.expression is None:
            return p.name, [], []
        et = self.et
        if not et:
            return self._resolve_flat(el, p.expression, rename, by_lower, connected_in, depth)
        # Structural recognition below is adjacency-based (a call is an
        # ident immediately followed by '(', a cast is '(' TypeName ')'
        # immediately followed by a primary, ...), and `_scan` emits every
        # whitespace character as its own 'other' token -- so source
        # formatting ("ISNULL (x)" vs "ISNULL(x)") would otherwise decide
        # whether a construct is recognised at all. Whitespace carries no
        # meaning in this grammar outside a string literal (already one
        # opaque 'str' token, unaffected), so it is dropped once, up front.
        # WHERE it was dropped is remembered (`gaps`), because for one reader it
        # is the only evidence there is: a numeric literal lexes as one 'other'
        # token PER CHARACTER, so `1.5` and `1 . 5` are the same token list, and
        # the second one states two literals side by side. See `_ExprCtx.gaps`.
        tokens: list = []
        gaps: set[int] = set()
        separated = False
        for t in self._scan(p.expression):
            if t[0] == "other" and t[1].isspace():
                separated = True
                continue
            if separated:
                gaps.add(len(tokens))
            tokens.append(t)
            separated = False
        # A literal the scanner cannot close is a MALFORMED source value, and the
        # corpus proves such values exist (a truncated `Numeric.sequence("s1",1,1`
        # in fact_workorder_Copy_0.1.item). The translated path REWRITES a literal
        # into SQL quoting, so translating one would turn a lexing limit into
        # corrupted SQL -- and, worse, SQL carrying DERIVED provenance, which reads
        # as a clean derivation. The whole expression takes the verbatim flat path
        # instead, and says why.
        open_lit = next((lex for kind, lex in tokens if kind == "str_open"), None)
        if open_lit is not None:
            return self._flat_fallback(
                el, p.expression, rename, by_lower, connected_in, depth,
                f"unterminated string literal {open_lit[:24]!r}: the expression is "
                f"emitted verbatim, untranslated")
        ctx = _ExprCtx(el, rename, by_lower, connected_in, depth, et, 0,
                       frozenset(gaps))
        try:
            return self._translate_span(tokens, 0, len(tokens), ctx)
        except RecursionError:
            # The declared span-depth cap normally degrades a deeply nested
            # expression long before this. Kept as the outer net because the cost
            # of being wrong about that is aborting `emit()` for the whole
            # document over one column.
            return self._flat_fallback(
                el, p.expression, rename, by_lower, connected_in, depth,
                "expression nesting exhausted the interpreter's recursion limit: "
                "the expression is emitted verbatim, untranslated")

    def _flat_fallback(self, el, expression, rename, by_lower, connected_in, depth,
                       reason: str):
        """The verbatim flat reading of an expression the translator declines,
        plus the reason it declined. Never silently: the reason is what keeps the
        slot's provenance RESIDUE instead of DERIVED."""
        text, residue, rules = self._resolve_flat(el, expression, rename, by_lower,
                                                  connected_in, depth)
        return text, residue + [reason], rules

    def _resolve_flat(self, el, expression, rename, by_lower, connected_in, depth):
        """The per-token reading every platform without
        `dialect.expression_translation` uses, and the fail-safe the translated
        path falls back to."""
        residue: list[str] = []
        rules: list[str] = []
        out: list[str] = []
        for kind, lex in self._scan(expression):
            if kind not in ("ref", "ident"):
                out.append(lex)
                d = self._divergence(out)
                if d:
                    residue.append(d)
                continue
            text, r, tr = self._resolve_ident_or_ref(kind, lex, el, rename, by_lower,
                                                     connected_in, depth)
            out.append(text)
            residue.extend(r)
            rules.extend(tr)
        return "".join(out), residue, rules

    # -- TK-03: structural source-expression -> Snowflake SQL translation ---
    #
    # Every name, operator spelling, type name and template below is read from
    # `dialect.expression_translation` -- this file names no source-language
    # vocabulary. The mechanism is generic (gated on the table declaring the
    # block, not on `self.table["platform"]`), so any future platform whose
    # expressions need the same class of rewrite can opt in the same way.
    #
    # ONE scan of the raw expression (`_scan`, already shared with `resolve`
    # and `_normalize_expression_syntax`) feeds a small recursive-descent walk
    # over the token list, in the SOURCE's own precedence order: ternary looser
    # than every `binary_operator_levels` entry (declared loosest first) looser
    # than a prefix operator / cast / call / group / leaf. Each level either
    # finds ITS OWN unambiguous structural marker at paren depth 0 or falls
    # through to the next; the terminal leaf case always renders SOMETHING, so
    # there is no separate "give up" path to keep in sync with the flat loop
    # above -- an unrecognised construct degrades to exactly what
    # `_resolve_flat` already does for it, token by token, plus a residue reason
    # naming what was not understood.
    #
    # Declaring a level per operator is NOT what keeps this honest -- what does is
    # the operator nobody enumerated, since a source logical-OR spelled `||` is
    # valid SQL meaning string concatenation. `leaf_passthrough_characters` is
    # the closed set of characters that may reach the artifact silently.

    @staticmethod
    def _paren_delta(tok) -> int:
        return 1 if tok == ("other", "(") else (-1 if tok == ("other", ")") else 0)

    @staticmethod
    def _op_tokens(op: str) -> tuple:
        """An operator's source spelling as the tokens `_scan` produces for it.
        Every operator character lexes as its own one-character 'other' token, so
        a two-character operator is two adjacent tokens and nothing here can be
        matched by comparing one lexeme."""
        return tuple(("other", ch) for ch in op)

    @classmethod
    def _operator_hits(cls, tokens, lo, hi, operators):
        """[(index, op)] for every paren-depth-0 occurrence in [lo, hi) of any
        operator in `operators`, LONGEST SPELLING FIRST at each index -- so a
        declared '<=' is never read as '<' plus a stray '='."""
        by_len = sorted(operators, key=len, reverse=True)
        depth = 0
        hits = []
        i = lo
        while i < hi:
            depth += cls._paren_delta(tokens[i])
            if depth != 0:
                i += 1
                continue
            for op in by_len:
                pair = cls._op_tokens(op)
                if tuple(tokens[i:i + len(pair)]) == pair:
                    hits.append((i, op))
                    i += len(pair)
                    break
            else:
                i += 1
        return hits

    @staticmethod
    def _chain_spans(lo, hi, hits):
        """(spans, ops) for a left-associative chain over `hits`, or None when
        this level cannot read the span as a chain.

        A hit that would leave an EMPTY operand span is not a binary operator
        occurrence: a leading '-' is a PREFIX operator, and the second '-' of
        `a - -b` belongs to the operand. Dropping those is what stops a unary
        '+' from rendering as a leading, unparseable ' + 1 + x'. A chain that
        would END on an operator is declined outright, so a truncated
        expression degrades through the leaf case (with a residue reason) rather
        than emitting a trailing operator."""
        spans, ops, start = [], [], lo
        for i, op in hits:
            if i <= start:
                continue
            spans.append((start, i))
            ops.append(op)
            start = i + len(op)
        if not ops or start >= hi:
            return None
        spans.append((start, hi))
        return spans, ops

    @classmethod
    def _primary_end(cls, tokens, lo, hi):
        """The end of the ONE primary starting at `lo` -- a call, a parenthesised
        group, or a single token.

        Two readers need it, both for the same reason: a construct that binds
        tighter than every binary operator must not absorb the operators after
        it. A cast's operand is the next primary, so `(int) x - 1` casts `x`
        (the source's own grouping) rather than `x - 1`; and a call-shaped span
        is only a call when the ')' at its end is the one that closes ITS OWN
        argument list."""
        if lo >= hi:
            return lo
        i = lo
        if tokens[i][0] == "ident" and i + 1 < hi and tokens[i + 1] == ("other", "("):
            i += 1
        if tokens[i] == ("other", "("):
            depth = 0
            for j in range(i, hi):
                depth += cls._paren_delta(tokens[j])
                if depth == 0:
                    return j + 1
            return hi
        return lo + 1

    @classmethod
    def _find_ternary_split(cls, tokens, lo, hi, et):
        """(q, colon) for the FIRST top-level condition separator in [lo, hi) and
        its MATCHING branch separator -- the source's ternary is
        right-associative (`a?b:c?d:e` == `a?b:(c?d:e)`), so the match is found
        by counting nested ternaries, not by taking the first separator seen.
        None when the span has no top-level ternary, or when the table declares
        no ternary at all."""
        ops = et.get("ternary_operators") or {}
        cond_op, branch_op = ops.get("condition_separator"), ops.get("branch_separator")
        if not cond_op or not branch_op:
            return None
        cond_tok, branch_tok = ("other", cond_op), ("other", branch_op)
        depth = tdepth = 0
        q = None
        for i in range(lo, hi):
            depth += cls._paren_delta(tokens[i])
            if depth != 0:
                continue
            if tokens[i] == cond_tok:
                if q is None:
                    q = i
                else:
                    tdepth += 1
            elif tokens[i] == branch_tok and q is not None:
                if tdepth == 0:
                    return q, i
                tdepth -= 1
        return None

    def _translate_span(self, tokens, lo, hi, ctx):
        cap = ctx.et.get("max_expression_span_depth")
        if cap is not None and ctx.sdepth > cap:
            txt, res, rules = self._translate_leaf_span(tokens, lo, hi, ctx)
            return txt, res + [
                f"expression nesting exceeds expression_translation"
                f".max_expression_span_depth ({cap}): the remainder is emitted "
                f"verbatim, untranslated"], rules
        split = self._find_ternary_split(tokens, lo, hi, ctx.et)
        if split is None:
            return self._translate_binary(tokens, lo, hi, ctx)
        q, c = split
        ops = ctx.et["ternary_operators"]
        inner = ctx.deeper()
        coalesce_tmpl = ops.get("coalesce_template")
        coalesced = coalesce_tmpl and self._coalesce_shape(
            tokens, lo, q, q + 1, c, c + 1, hi, ctx.et)
        if coalesced is not None:
            x_lo, x_hi, other_lo, other_hi = coalesced
            x_txt, x_res, x_rules = self._translate_span(tokens, x_lo, x_hi, inner)
            other_txt, other_res, other_rules = self._translate_span(
                tokens, other_lo, other_hi, inner)
            rules = x_rules + other_rules + ["expression_translation.null_coalesce"]
            text = self._substitute(
                coalesce_tmpl, {0: (x_txt, True), 1: (other_txt, True)}, ctx.et)
            return text, x_res + other_res, rules
        then_txt, then_res, then_rules = self._translate_span(tokens, q + 1, c, inner)
        else_txt, else_res, else_rules = self._translate_span(tokens, c + 1, hi, inner)
        cond_txt, cond_res, cond_rules = self._translate_span(tokens, lo, q, inner)
        residue = cond_res + then_res + else_res
        rules = cond_rules + then_rules + else_rules + ["expression_translation.ternary"]
        # case_template is read positionally, not through _substitute: its WHEN/THEN/
        # ELSE/END keywords bound each operand the way template_operand_delimiters'
        # characters bound a call's arguments, so no operand here risks re-associating
        # with what the template puts around it either way.
        text = ops["case_template"].format(cond_txt, then_txt, else_txt)
        return text, residue, rules

    def _coalesce_shape(self, tokens, cond_lo, cond_hi, then_lo, then_hi, else_lo, else_hi, et):
        """When the condition is EXACTLY `<X> <null comparison> <null literal>`
        (both spellings table-declared) and the branch taken when X is non-null
        repeats X's OWN raw tokens verbatim, the ternary is a null default and
        reads better -- and no less correctly -- as COALESCE(X, other). Returns
        (x_lo, x_hi, other_lo, other_hi) -- span bounds only, so the caller
        translates each side exactly once -- or None when the shape does not
        hold; CASE WHEN is always correct either way, so this is a
        simplification, never a requirement."""
        null_lit = et.get("null_literal")
        for op, spec in (et.get("null_comparison_rewrite") or {}).items():
            hits = self._operator_hits(tokens, cond_lo, cond_hi, {op: spec})
            if not hits:
                continue
            op_at = hits[0][0]
            x_lo, x_hi = cond_lo, op_at
            rhs = tokens[op_at + len(op):cond_hi]
            if not (len(rhs) == 1 and rhs[0] == ("ident", null_lit)):
                continue
            # The branch that repeats X is the one taken when X is NOT null,
            # which is the THEN branch exactly when the comparison is false for
            # null -- the table states which of its comparisons that is.
            matches_null = bool(spec.get("matches_null"))
            same_lo, same_hi = (else_lo, else_hi) if matches_null else (then_lo, then_hi)
            other_lo, other_hi = (then_lo, then_hi) if matches_null else (else_lo, else_hi)
            if tokens[same_lo:same_hi] != tokens[x_lo:x_hi]:
                continue
            return x_lo, x_hi, other_lo, other_hi
        return None

    def _translate_binary(self, tokens, lo, hi, ctx, level=0):
        """The declared binary operator levels, loosest first. A level that finds
        no readable chain of its own operators falls through to the next; past
        the last level the span is a single operand."""
        levels = ctx.et.get("binary_operator_levels") or []
        for li in range(level, len(levels)):
            operators = levels[li]["operators"]
            split = self._chain_spans(lo, hi, self._operator_hits(tokens, lo, hi, operators))
            if split is None:
                continue
            spans, ops = split
            # A note states a property of the SOURCE operator, so it is read ONCE here
            # rather than at each of the three places below that write a target
            # spelling, and once per distinct operator rather than per occurrence.
            declared = ctx.et.get("operator_residue_notes") or {}
            notes = [declared[op] for op in dict.fromkeys(ops) if op in declared]
            nulls = self._null_comparison_chain(tokens, spans, ops, operators, ctx, li)
            if nulls is not None:
                n_txt, n_res, n_rules = nulls
                return n_txt, notes + n_res, n_rules
            rendered: list[str] = []
            residue: list[str] = []
            rules: list[str] = []
            for s_lo, s_hi in spans:
                txt, res, rl = self._translate_binary(tokens, s_lo, s_hi, ctx, li + 1)
                rendered.append(txt)
                residue.extend(res)
                rules.extend(rl)
            text, c_res, c_rules = self._concat_chain(
                tokens, spans, ops, rendered, operators, ctx)
            if text is not None:
                return text, notes + residue + c_res, rules + c_rules
            parts = [rendered[0]]
            for op, txt in zip(ops, rendered[1:]):
                parts.extend((operators[op], txt))
            return " ".join(parts), notes + residue + c_res, rules + c_rules + [
                "expression_translation.binary_operator:" + levels[li]["id"]]
        return self._translate_operand(tokens, lo, hi, ctx)

    def _null_comparison_chain(self, tokens, spans, ops, operators, ctx, level):
        """(text, residue, rules) for a chain in which the declared null literal is an
        operand of a declared null comparison, folded left-associatively the way the
        source folds it -- or None when none is, which is an ordinary comparison the
        caller renders itself.

        `X == null` in SQL is `X IS NULL`: the rewritten comparison would be
        `= NULL`, which is never true, so it does not FAIL -- it inverts the branch.
        This is the whole reason the null literal is table-declared.

        WHY A FOLD RATHER THAN A TWO-OPERAND CASE. Both shapes a two-operand test
        misses ship that `= NULL`, MEASURED: a longer equality chain
        (`f == null == g` emitted `src.F = NULL = src.G`) and a parenthesised null
        (`a == (null)` emitted `src.A = (NULL)`), each with no residue reason and a
        CASE that therefore always took its ELSE branch."""
        nullcmp = ctx.et.get("null_comparison_rewrite") or {}
        nulls = [self._is_null_literal(tokens, s, ctx.et) for s in spans]
        if not any(op in nullcmp and (nulls[i] or nulls[i + 1])
                   for i, op in enumerate(ops)):
            return None
        residue: list[str] = []
        rules: list[str] = ["expression_translation.null_check"]

        def rendered(i):
            txt, res, rl = self._translate_binary(
                tokens, spans[i][0], spans[i][1], ctx, level + 1)
            residue.extend(res)
            rules.extend(rl)
            return txt

        text = rendered(0)
        # A null predicate is postfix, so the next operator has to be told where it
        # ends: `a IS NULL = g` reads the target's own way, not the source's.
        predicate, left_is_null = False, nulls[0]
        for i, op in enumerate(ops):
            spec = nullcmp.get(op)
            if spec is not None and nulls[i + 1] and not left_is_null:
                text = f"({text}) {spec['target']}" if predicate \
                    else f"{text} {spec['target']}"
            elif spec is not None and left_is_null:
                # `null == X` states the same thing about X the other way round.
                text = f"{rendered(i + 1)} {spec['target']}"
            else:
                right = rendered(i + 1)
                text = f"({text}) {operators[op]} {right}" if predicate \
                    else f"{text} {operators[op]} {right}"
                predicate, left_is_null = False, False
                continue
            predicate, left_is_null = True, False
        return text, residue, rules

    @classmethod
    def _is_null_literal(cls, tokens, span, et):
        """True when an operand span states the declared null literal and nothing
        else, through any number of enclosing parentheses -- `(null)` is the same
        statement, and an equality against one exact token list called it an ordinary
        comparison and rewrote it to `= NULL`."""
        null_tok = ("ident", et.get("null_literal"))
        lo, hi = span
        while (hi - lo >= 2 and tokens[lo] == ("other", "(")
               and cls._primary_end(tokens, lo, hi) == hi):
            lo, hi = lo + 1, hi - 1
        return tokens[lo:hi] == [null_tok]

    def _concat_chain(self, tokens, spans, ops, rendered, operators, ctx):
        """(text, residue, rules) for a chain at the level that declares the
        concatenation-capable operator, resolved the way the SOURCE resolves it:
        one PAIRWISE STEP at a time, left to right, by operand value class. `text`
        is None when no step reads as concatenation, so the caller's plain operator
        join stands -- with any residue this reading produced still returned.

        The operator is overloaded in the source (numeric addition OR string
        concatenation) and not in the target, so SOMETHING has to decide. The source
        decides per step, left to right, on the class of that step's two operands --
        so a step whose left side is already a string concatenates, and every step
        before it is still whatever ITS operands said.

        WHY PER STEP AND NOT PER CHAIN. Deciding once for the whole chain needs the
        whole chain to be the same operator, and the level that declares `+` also
        declares `-`. Rejecting the mixed chain outright (the previous version)
        classified nothing at all, so neither the concatenation nor the ambiguity
        reason fired and the arithmetic shipped verbatim: MEASURED, a single minus
        anywhere silently lost the classification -- `src.QTY - 1 + src.A` emitted
        `src.QTY - 1 + src.A`, which computes 11 where the source concatenates to
        '47', with no reason naming it. A step this reader cannot classify still
        reports, so nothing ships silently off the mixed-operator path."""
        et = ctx.et
        concat_op = et.get("string_concat_operator")
        target = et.get("string_concat_target_operator")
        if not concat_op or not target or concat_op not in ops:
            return None, [], []
        detection = et.get("string_concat_detection")
        if detection != CONCAT_DETECTION_TYPED_LEFT_ASSOCIATIVE:
            raise ValueError(
                f"dialect.expression_translation.string_concat_detection is "
                f"{detection!r}; this reader implements "
                f"{CONCAT_DETECTION_TYPED_LEFT_ASSOCIATIVE!r} only. A declared value no "
                f"reader dispatches on is a table that reads as coverage with nothing "
                f"behind it.")
        unstated = (
            f"operator '{concat_op}' is overloaded in the source (arithmetic or "
            f"concatenation) and the source states no value class for every operand: "
            f"emitted as '{concat_op}', NOT as '{target}'")

        def unusable(left, right):
            return (
                f"operator '{concat_op}' is overloaded in the source (arithmetic or "
                f"concatenation) and the source states value classes {left!r} and "
                f"{right!r}, which give it neither reading: emitted as '{concat_op}', "
                f"NOT as '{target}'")
        residue: list[str] = []
        text = rendered[0]
        acc = self._value_class(tokens, spans[0][0], spans[0][1], ctx)
        # None until an operator has actually been applied: the first step has no
        # accumulated reading to be grouped against.
        kind = None
        concatenated = False
        for i, op in enumerate(ops):
            right = self._value_class(tokens, spans[i + 1][0], spans[i + 1][1], ctx)
            left, is_concat, acc, ambiguous = (
                acc, *self._additive_step_class(acc, right, op, et))
            if ambiguous:
                residue.append(unstated if left is None or right is None
                               else unusable(left, right))
            step = "concat" if is_concat else "arith"
            if kind is not None and kind != step:
                # Parenthesised because the earlier reading really is a
                # sub-expression of this one, whatever the target's own precedence
                # between the two operators turns out to be.
                text = f"({text})"
            text = "%s %s %s" % (
                text, target if is_concat else operators[op], rendered[i + 1])
            kind = step
            concatenated = concatenated or is_concat
        if not concatenated:
            return None, residue, []
        return text, residue, ["expression_translation.string_concat"]

    @staticmethod
    def _additive_step_class(left, right, op, et):
        """(is_concatenation, resulting value class, ambiguous) for ONE pairwise step
        of a chain at the concatenation-capable level, from the two operand classes
        the source states -- None for either meaning it states none.

        `ambiguous` is True whenever the step's operator is the OVERLOADED one and
        NEITHER reading applied -- whether because a side is unstated or because the
        classes the source DID state give the operator no reading at all. A stated
        class is not a resolved one: MEASURED, a boolean or date left side against a
        numeric right side (`src.FLAG + src.QTY`, `src.D + src.QTY`) shipped a verbatim
        overloaded operator with zero reasons, because only an unstated class was
        counted as ambiguous. A step on the level's other operators has exactly one
        reading in the target, so it needs no reason -- but it still yields an unstated
        class, which makes any later overloaded step report."""
        string_class = et.get("string_value_class")
        numeric_class = et.get("numeric_value_class")
        overloaded = op == et.get("string_concat_operator")
        if overloaded and string_class is not None and string_class in (left, right):
            return True, string_class, False
        if numeric_class is not None and left == numeric_class == right:
            return False, numeric_class, False
        return False, None, overloaded

    @staticmethod
    def _cast_at(tokens, lo, hi, et):
        """The `cast_types` key a span's leading parenthesised cast names, or None when
        the span does not open with one: '(' TypeName ')' immediately followed by ONE
        primary that ends the span -- the one shape a plain parenthesised
        sub-expression can never take. Requiring the primary to end the span is what
        keeps the cast from absorbing the operators after it."""
        casts = et.get("cast_types") or {}
        if (hi - lo >= 4 and tokens[lo] == ("other", "(") and tokens[lo + 1][0] == "ident"
                and tokens[lo + 1][1] in casts and tokens[lo + 2] == ("other", ")")
                and Emitter._primary_end(tokens, lo + 3, hi) == hi):
            return tokens[lo + 1][1]
        return None

    def _value_class(self, tokens, lo, hi, ctx):
        """The value class the SOURCE states for one operand span, or None when it
        states none. Every side is data: `value_class_by_datatype` classifies a
        referenced column's own declared type, `function_translations[*].returns` a
        translated call's result, `cast_value_classes` the type a cast states outright.
        None means UNSTATED and is never quietly promoted to a class -- the caller
        reports it.

        A CAST, A PARENTHESISED GROUP AND A SUB-CHAIN ALL STATE A CLASS, and reading
        the span as an opaque non-atom instead loses it: MEASURED, `(int) src.QTY + 1`
        reported a value-class ambiguity on output that was already right, and
        `src.QTY + (src.A)` lost the concatenation entirely because the parentheses
        hid the string."""
        et = ctx.et
        if hi - lo <= 0:
            return None
        forms = et.get("unary_operator_forms") or {}
        if tokens[lo][0] == "other" and tokens[lo][1] in forms:
            return self._value_class(tokens, lo + 1, hi, ctx)
        if all(k == "other" and (lex.isdigit() or lex == ".") for k, lex in tokens[lo:hi]):
            return et.get("numeric_value_class")
        if hi - lo == 1:
            kind, lex = tokens[lo]
            if kind == "str":
                return et.get("string_value_class")
            if kind in ("ident", "ref"):
                return self._reference_value_class(lex, ctx)
            return None
        # Before the group test below, since a cast OPENS with a parenthesis that is
        # not the group's.
        cast = self._cast_at(tokens, lo, hi, et)
        if cast is not None:
            return (et.get("cast_value_classes") or {}).get(cast)
        key = self._call_key(tokens, lo, hi, ctx)
        if key is not None:
            return ((et.get("function_translations") or {}).get(key) or {}).get("returns")
        if tokens[lo] == ("other", "(") and self._primary_end(tokens, lo, hi) == hi:
            return self._value_class(tokens, lo + 1, hi - 1, ctx)
        return self._chain_value_class(tokens, lo, hi, ctx)

    def _chain_value_class(self, tokens, lo, hi, ctx):
        """The class a span that is itself a chain at the concatenation-capable level
        states, folded the same pairwise way the emitted text is -- or None, which
        means unstated and makes the caller report."""
        et = ctx.et
        concat_op = et.get("string_concat_operator")
        level = next((lv for lv in et.get("binary_operator_levels") or []
                      if concat_op in (lv.get("operators") or {})), None)
        if level is None:
            return None
        operators = level["operators"]
        split = self._chain_spans(lo, hi, self._operator_hits(tokens, lo, hi, operators))
        if split is None:
            return None
        spans, ops = split
        acc = self._value_class(tokens, spans[0][0], spans[0][1], ctx)
        for i, op in enumerate(ops):
            right = self._value_class(tokens, spans[i + 1][0], spans[i + 1][1], ctx)
            _, acc, _ = self._additive_step_class(acc, right, op, et)
        return acc

    def _reference_value_class(self, lex, ctx):
        classes = ctx.et.get("value_class_by_datatype") or {}
        ci = self.syn.get("case_insensitive_resolution", True)
        port = ctx.by_lower.get(lex.lower() if ci else lex)
        datatype = port.datatype if port is not None else None
        return classes.get(datatype) if datatype else None

    def _call_key(self, tokens, lo, hi, ctx):
        """The `function_translations` key a call-shaped span names, prefixes
        stripped, or None when the span is not one call."""
        if not (hi - lo >= 3 and tokens[lo][0] == "ident"
                and tokens[lo + 1] == ("other", "(") and tokens[hi - 1] == ("other", ")")
                and self._primary_end(tokens, lo, hi) == hi):
            return None
        key = tokens[lo][1]
        for pfx in ctx.et.get("call_name_strip_prefixes") or []:
            if key.startswith(pfx):
                return key[len(pfx):]
        return key

    def _translate_operand(self, tokens, lo, hi, ctx):
        et = ctx.et
        if hi <= lo:
            return "", [], []
        # A prefix operator, declared with the FULL target form it renders as --
        # so an identity prefix (a unary '+') renders as its operand and cannot
        # emit a leading operator, and a logical negation can become a keyword
        # with its operand parenthesised.
        forms = et.get("unary_operator_forms") or {}
        if hi - lo >= 2 and tokens[lo][0] == "other" and tokens[lo][1] in forms:
            inner, res, rl = self._translate_operand(tokens, lo + 1, hi, ctx)
            operand = [(inner, self._is_atom(tokens, (lo + 1, hi), ctx))]
            return self._substitute(forms[tokens[lo][1]], operand, et), res, \
                rl + ["expression_translation.unary_operator"]
        # A parenthesised cast: '(' TypeName ')' immediately followed by ONE
        # primary that ends the span -- the one shape a plain parenthesised
        # sub-expression can never take. Requiring the primary to end the span
        # is what keeps the cast from absorbing the operators after it.
        cast = self._cast_at(tokens, lo, hi, et)
        if cast is not None:
            inner_txt, res, rl = self._translate_operand(tokens, lo + 3, hi, ctx)
            operand = [(inner_txt, self._is_atom(tokens, (lo + 3, hi), ctx))]
            return (self._substitute(et["cast_types"][cast], operand, et), res,
                    rl + ["expression_translation.cast"])
        # Function call: an ident immediately followed by the '(' whose own match
        # ends the span. ALWAYS recurses into the argument list, known name or
        # not -- an unrecognised outer wrapper (Integer.parseInt(...) in the
        # AdW2017 corpus) must not hide a recognised call nested inside it.
        if (hi - lo >= 3 and tokens[lo][0] == "ident" and tokens[lo + 1] == ("other", "(")
                and tokens[hi - 1] == ("other", ")")
                and self._primary_end(tokens, lo, hi) == hi):
            return self._translate_call_or_unsupported(tokens, lo, hi, ctx)
        # Parenthesised group spanning the WHOLE remaining span.
        if (hi - lo >= 2 and tokens[lo] == ("other", "(")
                and self._primary_end(tokens, lo, hi) == hi):
            inner_txt, res, rl = self._translate_span(tokens, lo + 1, hi - 1, ctx.deeper())
            return f"({inner_txt})", res, rl
        return self._translate_leaf_span(tokens, lo, hi, ctx)

    def _split_args(self, tokens, arg_lo, arg_hi, et):
        """Top-level-separator-separated argument spans between a call's parens."""
        if arg_hi <= arg_lo:
            return []
        sep = et["argument_separator"]
        bounds = [i for i, _ in self._operator_hits(tokens, arg_lo, arg_hi, {sep: sep})]
        starts = [arg_lo] + [a + len(sep) for a in bounds]
        stops = bounds + [arg_hi]
        return list(zip(starts, stops))

    def _translate_call_or_unsupported(self, tokens, lo, hi, ctx):
        """A call-shaped span, [lo, hi) == name '(' args ')'.

        Renders the table-declared template when the table declares the name, the
        call states EXACTLY the declared `arity`, and every argument the entry
        constrains (a date part, a date/time format pattern) resolves against its
        own declared map. Otherwise the call name is threaded through with its own
        argument list still recursively translated -- so a recognised call nested
        inside an unsupported wrapper (`Integer.parseInt(routines.TalendDate
        .formatDate(...))` in the AdW2017 corpus) is not hidden by the wrapper
        around it.

        REFUSING IS THE WHOLE POINT OF THE SECOND HALF. Residue is provenance and
        not a gate: whatever text this returns becomes the column's Expression. So
        a call that cannot be translated FAITHFULLY has to come back looking
        untranslated, never looking translated with an argument quietly missing --
        MEASURED before `arity` existed, `StringHandling.LEFT(a, 3, 4)` emitted
        `LEFT(a, 3)` and `TalendDate.parseDate(p, s, "en_US")` emitted
        `TRY_TO_DATE(s, p)`, neither carrying any residue about the argument it
        discarded. Each refusal names its own
        cause, because "unknown identifier 'TalendDate.addDate'" on a call whose
        FUNCTION is declared and whose date-part LITERAL is not sends the reader
        looking for the wrong thing.
        """
        et = ctx.et
        raw_name = tokens[lo][1]
        key = self._call_key(tokens, lo, hi, ctx)
        spec = (et.get("function_translations") or {}).get(key)
        args = self._split_args(tokens, lo + 2, hi - 1, et)
        # Every argument recurses FIRST, whether or not the call itself resolves.
        rendered: list[str] = []
        residue: list[str] = []
        rules: list[str] = []
        inner = ctx.deeper()
        for span in args:
            txt, res, rl = self._translate_span(tokens, span[0], span[1], inner)
            rendered.append(txt)
            residue.extend(res)
            rules.extend(rl)
        body = ", ".join(rendered)
        verbatim = f"{raw_name}({body})"
        if spec is None:
            source_args = "".join(lex for _, lex in tokens[lo + 2:hi - 1])
            if body.replace(" ", "") == source_args.replace(" ", ""):
                residue.append(f"unknown identifier '{raw_name}' (function or unresolved "
                               f"reference): emitted verbatim, untranslated")
            else:
                # The arguments of an untranslatable call are NOT untouched, and
                # saying they are is the kind of wrong that stops a reader looking.
                # A string literal is re-quoted for SQL and a nested known call is
                # rewritten, both of which change the text inside the parentheses.
                residue.append(
                    f"unknown identifier '{raw_name}' (function or unresolved "
                    f"reference): its name and call shape are emitted unchanged, but "
                    f"its ARGUMENTS are translated rather than copied -- "
                    f"{source_args!r} became {body!r}")
            return verbatim, residue, rules
        arity = spec["arity"]
        if len(args) != arity:
            residue.append(
                f"'{key}' is declared taking exactly {arity} argument(s) and this call "
                f"states {len(args)}: the whole call is emitted untranslated rather "
                f"than fitted to the declared template by dropping or inventing one")
            return verbatim, residue, rules
        # (text, atomic) per argument -- `atomic` is what `_substitute` needs to decide
        # grouping, and it is read off the SOURCE span, never by re-lexing the rendered
        # SQL (the #5117 class). A mapped date part or format pattern is one literal, so
        # it is atomic by construction; `_adjusted_argument` states its own.
        values = [(txt, self._is_atom(tokens, span, ctx))
                  for txt, span in zip(rendered, args)]
        for pos in spec.get("date_part_args") or []:
            mapped, why = self._mapped_date_part(tokens, args[pos], et)
            if mapped is None:
                residue.append(
                    f"'{key}' IS declared here -- it is argument {pos} that is not: "
                    f"{why}. The whole call is emitted untranslated")
                return verbatim, residue, rules
            values[pos] = (mapped, True)
        for pos in spec.get("date_format_args") or []:
            mapped, why = self._mapped_date_format(tokens, args[pos], et)
            if mapped is None:
                residue.append(
                    f"'{key}' IS declared here -- it is its format-pattern argument "
                    f"{pos} that is not: {why}. The whole call is emitted "
                    f"untranslated, because a format string the target reads "
                    f"differently is valid syntax producing the wrong text")
                return verbatim, residue, rules
            values[pos] = (mapped, True)
        for placeholder, adj in (spec.get("argument_adjustments") or {}).items():
            residue.extend(
                self._out_of_domain_index(key, int(placeholder), adj, tokens, args))
            values[int(placeholder)] = self._adjusted_argument(
                int(placeholder), adj, rendered, tokens, args, ctx)
        for pos, why in sorted((spec.get("unused_arguments") or {}).items()):
            residue.append(f"argument {pos} of '{key}' is not represented in the "
                           f"translation: {why}")
        note = spec.get("residue_note")
        if note:
            residue.append(note)
        return self._substitute(spec["template"], values, et), residue, rules + \
            ["expression_translation.function_call:" + key]

    @staticmethod
    def _literal_body(tokens, span):
        """The body of an argument span that is ONE string literal, else None -- the
        shape a table-declared literal argument (a date part, a format pattern) must
        have to be looked up in a declared map at all."""
        a_lo, a_hi = span
        if a_hi - a_lo == 1 and tokens[a_lo][0] == "str":
            return tokens[a_lo][1][1:-1]
        return None

    def _mapped_date_part(self, tokens, span, et):
        """(target date part, None) for one declared date-part argument, or
        (None, why it does not resolve)."""
        literal = self._literal_body(tokens, span)
        if literal is None:
            return None, ("it is not a single string literal, so no declared "
                          "date_part_literals key can be matched against it")
        mapped = (et.get("date_part_literals") or {}).get(literal)
        if mapped is None:
            return None, (f"it names {literal!r}, which dialect.expression_translation"
                          f".date_part_literals does not declare")
        return mapped, None

    def _mapped_date_format(self, tokens, span, et):
        """(target format string as a quoted SQL literal, None) for one declared
        date/time format-pattern argument, or (None, why it does not resolve).

        WHY ONE UNMAPPED ELEMENT DECLINES THE WHOLE CALL. A format string is
        POSITIONAL: an element that comes out the wrong width moves every character
        after it, so there is no partial translation worth emitting. And the failure
        is silent by construction, because the source's pattern letters and the
        target's are both letters -- an untranslated pattern is a VALID target
        pattern meaning something else. MEASURED before this existed:
        `TalendDate.formatDate("HH:mm:ss", d)` emitted `TO_CHAR(d, 'HH:mm:ss')`,
        which Snowflake reads as hour, MONTH, second.

        Every character class is declared: the letters the SOURCE reserves as
        pattern letters, the runs that have a target spelling, the unquoted
        characters that mean themselves in both models, and how each model spells a
        quoted literal section.
        """
        pattern = self._literal_body(tokens, span)
        if pattern is None:
            return None, ("it is not a single string literal, so its pattern letters "
                          "cannot be read at all")
        letters = et.get("date_format_letter_characters") or ""
        literals = et.get("date_format_literal_characters") or ""
        quote = et.get("date_format_quote_character")
        quoted_tpl = et.get("date_format_quoted_literal_template") or "{0}"
        delimiters = set(quoted_tpl.replace("{0}", ""))
        declared = et.get("date_format_pattern_map") or {}
        out: list[str] = []
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if quote and ch == quote:
                end = pattern.find(quote, i + 1)
                if end < 0:
                    return None, (f"it opens a quoted literal section at offset {i} "
                                  f"that the pattern never closes")
                # An immediately doubled quote is the escaped quote character itself,
                # not an empty literal section.
                section = pattern[i + 1:end] or quote
                if delimiters & set(section):
                    return None, (f"its quoted literal section {section!r} contains the "
                                  f"target format model's own literal delimiter, which "
                                  f"there is no second escape level to express")
                out.append(quoted_tpl.format(section))
                i = end + 1
                continue
            if ch in letters:
                run = i
                while run < len(pattern) and pattern[run] == ch:
                    run += 1
                element = pattern[i:run]
                mapped = declared.get(element)
                if mapped is None:
                    return None, (f"it uses the pattern letter run {element!r}, which "
                                  f"dialect.expression_translation"
                                  f".date_format_pattern_map does not declare")
                out.append(mapped)
                i = run
                continue
            if ch in literals:
                out.append(ch)
                i += 1
                continue
            return None, (f"it contains {ch!r}, which is neither a pattern letter the "
                          f"source reserves nor one of the characters "
                          f"date_format_literal_characters lets cross unchanged")
        return "'" + "".join(out).replace("'", "''") + "'", None

    @staticmethod
    def _integer_literal(tokens, span):
        """The value of an argument span that is one integer literal, else None.
        `_scan` emits each digit as its own 'other' token, so the span is read
        rather than a single lexeme."""
        a_lo, a_hi = span
        if a_hi > a_lo and tokens[a_lo] == ("other", "-"):
            return -(Emitter._integer_literal(tokens, (a_lo + 1, a_hi)) or 0) or None
        digits = [lex for kind, lex in tokens[a_lo:a_hi] if kind == "other"]
        if a_hi <= a_lo or len(digits) != a_hi - a_lo or not all(d.isdigit() for d in digits):
            return None
        return int("".join(digits))

    def _out_of_domain_index(self, key, placeholder, adj, tokens, args):
        """A reason for every LITERAL index argument of a declared index adjustment that
        lies outside the index domain the source itself counts from.

        The correction is linear, so it translates an index the source would never accept
        as readily as one it would: MEASURED, `StringHandling.SUBSTR(name, -1, 3)`
        emitted `SUBSTR(name, 0, 4)`, which RETURNS text where the source raises at run
        time -- a wrong value with nothing naming it. Only a literal is decidable here,
        and only `source_index_base` states where the domain starts."""
        base = adj.get("source_index_base")
        if base is None:
            return []
        positions = [int(p) for p in (adj.get("argument_coefficients")
                                      or {str(placeholder): 1})]
        out = []
        for pos in sorted(positions):
            literal = self._integer_literal(tokens, args[pos])
            if literal is not None and literal < int(base):
                out.append(
                    f"argument {pos} of '{key}' is the literal {literal}, below the "
                    f"index base {base} the source counts from: the source rejects that "
                    f"index at run time, and the linear correction translates it into a "
                    f"target index that returns a value instead")
        return out

    def _adjusted_argument(self, placeholder, adj, rendered, tokens, args, ctx):
        """(text, atomic) for one template placeholder under a declared LINEAR
        adjustment -- `atomic` as `_substitute` means it, so the ONE grouping
        decision downstream is made about the text this actually returns.

        The constant is `offset`, or `target_index_base - source_index_base`;
        `argument_coefficients` maps SOURCE argument positions to integer
        coefficients when the target's argument combines several source ones
        (default: this placeholder's own position, coefficient 1).

        Two renderings, and both are required. Every referenced argument that IS an
        integer literal folds into the constant, so the ordinary literal call stays
        exactly as readable as it was (`SUBSTR(s, 1, 3)` -> `SUBSTR(s, 2, 2)`). An
        argument that is a column reference cannot be folded at translate time, so
        the adjustment is emitted as explicit, parenthesised arithmetic instead
        (`SUBSTR(s, src.S, src.E)` -> `SUBSTR(s, (src.S + 1), (src.E - src.S))`).
        The alternative -- declining the call whenever an index is not a literal --
        would refuse the very calls that need the correction most.

        AN ARGUMENT THAT IS NOT AN ATOM IS PARENTHESISED before it goes into that
        arithmetic, because the argument text is spliced into an expression this
        reader wrote and the source's own grouping does not survive the splice:
        MEASURED, `SUBSTR(name, src.S - 1, src.E)` emitted a length of
        `(src.E - src.S - 1)`, one term of which had its sign inverted, so the
        result was two characters short with nothing reporting it.
        """
        constant = (int(adj["offset"]) if "offset" in adj
                    else int(adj["target_index_base"]) - int(adj["source_index_base"]))
        coefficients = {int(k): int(v) for k, v in
                        (adj.get("argument_coefficients")
                         or {str(placeholder): 1}).items()}
        terms: list[str] = []
        sole = None
        for pos, c in coefficients.items():
            literal = self._integer_literal(tokens, args[pos])
            if literal is not None:
                constant += c * literal
                continue
            raw = rendered[pos]
            atomic = self._is_atom(tokens, args[pos], ctx)
            text = raw if atomic else f"({raw})"
            if not terms:
                if c == 1:
                    sole = (raw, atomic)
                terms.append(text if c == 1 else
                             (f"-{text}" if c == -1 else f"{c} * {text}"))
                continue
            sign, magnitude = ("+" if c > 0 else "-"), abs(c)
            terms.append(f"{sign} {text}" if magnitude == 1
                         else f"{sign} {magnitude} * {text}")
        if not terms:
            # A folded constant is an atom only while it has no sign of its own: a
            # leading `-` re-associates after a `*` exactly as a `+` term would.
            return str(constant), constant >= 0
        if constant:
            terms.append(("+ %d" if constant > 0 else "- %d") % abs(constant))
        if len(terms) == 1 and sole is not None and not constant:
            # Nothing was added to it, so the argument passes through exactly as
            # the source wrote it -- including its own grouping, or absence of one.
            return sole
        return "(" + " ".join(terms) + ")", True

    def _is_atom(self, tokens, span, ctx):
        """True when an operand span carries NO top-level operator that splicing it into
        generated text could re-associate: ONE primary -- a literal, a reference, a call,
        an already-parenthesised group -- or ONE numeric literal, which `_scan` spells
        one token PER CHARACTER and `_primary_end` therefore stops in the middle of."""
        a_lo, a_hi = span
        if a_hi <= a_lo:
            return False
        if self._primary_end(tokens, a_lo, a_hi) == a_hi:
            return True
        passthrough = ctx.et.get("leaf_passthrough_characters") or ""
        return (all(k == "other" and lex in passthrough for k, lex in tokens[a_lo:a_hi])
                and not any(i in ctx.gaps for i in range(a_lo + 1, a_hi)))

    def _substitute(self, template, operands, et):
        """THE ONE PLACE A RESOLVED OPERAND IS SPLICED INTO A TABLE-AUTHORED TEMPLATE,
        and therefore the one place the grouping decision is made. Every template
        family goes through here -- `function_translations[*].template`, `cast_types`,
        `unary_operator_forms` -- so a template added later inherits the decision
        instead of needing its own repair.

        `operands` maps a placeholder position to (text, atomic), where `atomic` says
        the text is ONE primary and so has no top-level operator of its own.

        WHY THE DECISION HAS TO LIVE HERE. This defect class has now recurred three
        times, and the mechanism was identical each time: operand text spliced into a
        generated arithmetic or predicate context, where the source's own grouping did
        not survive the splice. Each round fixed the INSTANCE it was shown. The
        instances left over were exactly the ones a per-instance fix structurally
        cannot reach -- a template that declares no `argument_adjustments` at all
        (`Numeric.sequence`'s `{2}`, spliced straight after a `*`: MEASURED,
        `Numeric.sequence("s", 100, src.N + 1)` emitted
        `(100 + (ROW_NUMBER() OVER () - 1) * src.N + 1)`, which with N=5 steps by 5
        from 101 where the source steps by 6 from 100), and a template that wraps ITSELF but
        not its operand (`Relational.ISNULL`'s `({0} IS NULL)`: `!src.FLAG` emitted
        `(NOT src.FLAG IS NULL)`, which Snowflake reads as `NOT (FLAG IS NULL)`).

        WHAT IS NOT GROUPED, AND WHY THAT IS READ OFF THE TEMPLATE. Wrapping every
        non-atom unconditionally is correct and unreadable -- it puts parentheses
        round every argument of every comma-delimited call. A placeholder whose two
        neighbours in the template are both `template_operand_delimiters` characters
        (or the template's own ends) is already delimited by construction: nothing
        the template generates can bind across a delimiter, so `ABS({0})` and
        `SUBSTR({0}, {1}, {2})` splice exactly as before. A placeholder with anything
        ELSE beside it -- an operator, a keyword, a cast marker -- is in a context the
        template generates, and a non-atom goes in parenthesised."""
        delimiters = set(et.get("template_operand_delimiters") or "")
        out: list[str] = []
        at = 0
        for match in re.finditer(r"\{(\d+)\}", template):
            text, atomic = operands[int(match.group(1))]
            out.append(template[at:match.start()])
            at = match.end()
            out.append(text if atomic or self._delimited_in_template(
                template, match.start(), match.end(), delimiters) else f"({text})")
        out.append(template[at:])
        return "".join(out)

    @staticmethod
    def _delimited_in_template(template, start, end, delimiters):
        """True when BOTH sides of a template placeholder are a declared delimiter
        character or the template's own end, so whatever is spliced in cannot
        re-associate with the text around it. Whitespace is not a delimiter: ` IS
        NULL` binds to the operand before it exactly as `+` does."""
        before, after = template[:start].rstrip(), template[end:].lstrip()
        return ((not before or before[-1] in delimiters)
                and (not after or after[0] in delimiters))

    def _undeclared_adjacencies(self, toks, lo, ctx, passthrough):
        """offset -> the reason it declines, for every token of a run of ADJACENT
        VALUES with no declared operator between them.

        ONE numeric literal is the exception, and it is the only reason `gaps` exists:
        `_scan` emits one token PER CHARACTER for a number, so `1.5` and `1 . 5` reach
        this reader as the same three tokens and only the dropped whitespace tells
        them apart -- the first is one value, the second states two."""
        et = ctx.et
        numeric = et.get("numeric_value_class")
        kinds = [self._leaf_value_kind(t, et, passthrough) for t in toks]
        out: dict[int, str] = {}
        for i in range(1, len(toks)):
            left, right = kinds[i - 1], kinds[i]
            if left is None or right is None:
                continue
            if left == right == numeric and (lo + i) not in ctx.gaps:
                continue
            out[i] = out[i - 1] = (
                f"{self._adjacent_values(left, right)} are stated with nothing between "
                f"them, which no dialect.expression_translation level reads as an "
                f"operator: the run is emitted verbatim, untranslated, rather than "
                f"joined into one value the source does not state")
        return out

    @staticmethod
    def _leaf_value_kind(token, et, passthrough):
        """The generic noun for a leaf token that is a VALUE, or None -- punctuation
        and undeclared operators are what separate values, and report themselves."""
        kind, lex = token
        if kind == "str":
            return et.get("string_value_class")
        if kind == "other":
            return et.get("numeric_value_class") if lex in passthrough else None
        return "reference" if kind in ("ref", "ident") else None

    @staticmethod
    def _adjacent_values(left, right):
        """`two string literals`, `a numeric literal and a reference` -- the value
        classes come from the table; the nouns around them name no language."""
        def noun(kind, plural=False):
            if kind == "reference":
                return "references" if plural else "reference"
            return f"{kind} literals" if plural else f"{kind} literal"
        if left == right:
            return "two " + noun(left, True)
        return f"a {noun(left)} and a {noun(right)}"

    def _translate_leaf_span(self, tokens, lo, hi, ctx):
        """The terminal case: no ternary, no declared operator, no cast, call or
        group was found in [lo, hi). Renders token by token via the SAME
        `_resolve_ident_or_ref` the flat (non-translated) path uses, so an
        unresolved reference degrades to exactly the residue `_resolve_flat`
        already reports for it -- plus three things a bare per-token pass would
        get wrong for a source string emitted as Snowflake SQL:

        - the null literal is the SQL keyword NULL, not an unknown identifier;
        - a source string literal -- single- OR double-quoted, whichever
          `expression_syntax.string_quotes` allows -- is always re-quoted as a
          single-quoted SQL literal with internal quotes doubled, because
          Snowflake reads a double-quoted token as a case-sensitive IDENTIFIER,
          not a string. An in-literal escape before a quote is consumed here
          (`string_escape_char`), since doubling is the target's own escape and
          the two must not stack;
        - an operator character that reached this point is one NO declared level
          understood. It is still emitted verbatim (dropping it would change the
          expression silently) but it carries a residue reason naming it, which
          is the only reason an operator nobody enumerated cannot look
          translated. `leaf_passthrough_characters` is the closed set that may
          pass without one.

        ANY TWO ADJACENT VALUES ARE DECLINED, not joined. Rendering each one and
        concatenating the results is how the per-token pass reads them, and the result
        is a single VALID target value stating something the source never did:
        MEASURED, `"a""b"` shipped as `'a''b'`, which reads `a'b`, and `1 2` shipped as
        `12`, both as clean DERIVED with no reason. What makes them wrong is not their
        kind, it is that NO declared level reads the gap between them as an operator --
        so the test is on adjacency, and the run crosses verbatim and reports, the same
        way an unknown operator does.
        """
        et = ctx.et
        null_lit = et.get("null_literal")
        passthrough = et.get("leaf_passthrough_characters") or ""
        escape = self.syn.get("string_escape_char")
        toks = tokens[lo:hi]
        adjacent = self._undeclared_adjacencies(toks, lo, ctx, passthrough)
        out: list[str] = []
        residue: list[str] = []
        rules: list[str] = []
        for offset, (kind, lex) in enumerate(toks):
            if offset in adjacent:
                # the dropped gap is restored HERE and nowhere else: `1 2` joined without
                # it is the single valid value `12`, which is the defect being declined.
                out.append((" " if (lo + offset) in ctx.gaps else "") + lex)
                residue.append(adjacent[offset])
                continue
            if kind == "str":
                body = lex[1:-1]
                if escape:
                    for q in self.syn["string_quotes"]:
                        body = body.replace(escape + q, q)
                out.append("'" + body.replace("'", "''") + "'")
                continue
            if kind == "ident" and lex == null_lit:
                out.append("NULL")
                rules.append("expression_translation.null_literal")
                continue
            if kind in ("ref", "ident"):
                text, r, tr = self._resolve_ident_or_ref(kind, lex, ctx.el, ctx.rename,
                                                         ctx.by_lower, ctx.connected_in,
                                                         ctx.depth)
                out.append(text)
                residue.extend(r)
                rules.extend(tr)
                continue
            out.append(lex)
            if kind == "other" and lex not in passthrough:
                residue.append(
                    f"operator or punctuation '{lex}' is declared by no "
                    f"dialect.expression_translation level: emitted verbatim, "
                    f"untranslated")
        return "".join(out), residue, rules

    # -- columns -----------------------------------------------------------

    def column_json(self, p: Port, name: str, expr: str | None) -> dict:
        """FRAMEWORK CHANGE 23: Precision and Scale were emitted unconditionally
        because every Informatica port states both. SSIS states `length` for
        strings, `precision`/`scale` for numerics, and NOTHING for i4 or dbDate."""
        c: dict = {}
        if expr is not None:
            c["$kind"] = "ColumnExpression"
            c["Expression"] = expr
        c["Name"] = name
        c["DataType"] = p.datatype
        if p.precision is not None:
            c["Precision"] = p.precision
        if p.scale is not None and (self.pol["emit_scale_when_zero"] or p.scale):
            c["Scale"] = p.scale
        return c

    def record_column_slots(self, el_name: str, path: str, p: Port,
                            expr_prov: tuple[str, str, str] | None,
                            name_where: str | None = None) -> None:
        # FRAMEWORK CHANGE 51 (ARCHITECTURAL A6, all call sites in this file):
        # "/@" + attr became self.idn.attr_ref(node, attr). Three sites here, plus
        # node.id and element.Name in emit_node and the CHILD_ATTR rule in
        # record_no_slot_facts -- six in total, all under this number.
        # See Identification.attr_ref.
        #
        # FRAMEWORK CHANGE 63 (b): `name_where` OVERRIDES the citation for `.Name` ONLY.
        # An InputColumns entry takes its datatype, precision and scale from the LOCAL
        # port and its NAME from the UPSTREAM field (port_policy.input_column_naming =
        # UPSTREAM_FIELD on every table), so one `where` cannot be right for all four.
        # It was the local port's for all four, which is wrong exactly where a
        # transformation renames a port -- five citations on MappingForTest.XML, found by
        # the provenance audit the moment it could read an XML front-end at all. Passed
        # rather than inferred here, because only the caller knows which naming policy
        # produced the value.
        ref = self.idn.attr_ref
        self.slots.append(Slot(el_name, f"{path}.Name", SOURCE,
                               name_where if name_where
                               else p.where + ref(p.node, p.name_attr)))
        self.slots.append(Slot(el_name, f"{path}.DataType", SOURCE,
                               p.where + (ref(p.node, p.datatype_attr)
                                          if p.datatype_attr else "/@?")))
        for ir_field, val, attr in (("Precision", p.precision, p.precision_attr),
                                    ("Scale", p.scale, p.scale_attr)):
            if val is not None:
                self.slots.append(Slot(el_name, f"{path}.{ir_field}", SOURCE,
                                       p.where + ref(p.node, attr)))
            else:
                # The contract wants this field; the platform never states it for
                # this data type. v1 had no provenance value for that direction.
                self.slots.append(Slot(
                    el_name, f"{path}.{ir_field}", MISSING, p.where,
                    f"platform states no {ir_field.lower()} for type '{p.datatype}'"))
        if expr_prov is not None:
            prov, where, detail = expr_prov
            self.slots.append(Slot(el_name, f"{path}.Expression", prov, where, detail))

    # -- no-slot source facts ---------------------------------------------

    def record_no_slot_facts(self, el, promoted: frozenset = frozenset()) -> None:
        """FRAMEWORK CHANGE 24: this method WAS the Informatica fact list, in
        Python: it named 'Sql Query', 'Select Distinct', 'OUTPUT/DEFAULT',
        'ERROR(', REUSABLE, TARGETLOADORDER and the string 'SOURCE'/'TARGET'
        roles inline. It is now an interpreter over declarative rules.

        FRAMEWORK CHANGE 59 (ENG-014 spike): `promoted` names rule ids that the
        element's KIND can now hold as real IR fields, so they must not also be
        reported as NO_SLOT. The promotion itself happens in emit_node, which is
        where the kind is known; this method only has to stop double-counting.
        Passing an id that the table does not promote is a no-op, and passing one
        that IS promoted while emitting no slot for it would LOWER the obligation
        count instead of satisfying it -- so emit_node asserts it emitted one."""
        nd = self.table["neutral_defaults"]
        dvp = self.table["default_value_policy"]
        name = el.instance_name
        connected_in = {fe.to_field for fe in self.idn.inbound(name)}
        connected_out = {fe.from_field for fe in self.idn.outbound(name)}
        attr_tpl = (self.table["structure"].get("attr_where_template")
                    or "attribute[@name='{key}']")

        def add(rid, key, prov, where, detail=""):
            path = f"!{rid}[{key}]" if key is not None else f"!{rid}"
            # FRAMEWORK CHANGE 38: detail was always emitted whole, because in XML
            # a source fact is a short attribute value. A record-block value can be
            # an entire embedded document: the XMLProperties value on a DataStage
            # connector stage is a 4 KB XML blob holding the SELECT statement, the
            # table name and the write mode. Truncation is table-declared so the
            # limit is a reviewable policy rather than a magic number, and the
            # untruncated length is reported so nothing is silently shortened.
            lim = self.table["structure"].get("detail_max_chars")
            if lim and detail and len(detail) > lim:
                detail = f"{detail[:lim]}... [{len(detail)} chars total, truncated]"
            self.slots.append(Slot(name, path, prov, where, detail))

        for rule in self.table["no_slot_facts"]:
            if rule["id"] in promoted:
                continue
            src = rule["from"]
            prov = RESIDUE if rule.get("provenance") == "RESIDUE" else NO_SLOT
            sfx = rule.get("where_suffix", "")
            tpl = rule.get("detail", "")

            if src == "HARVEST":
                if el.harvested:
                    add(rule["id"], None, prov, el.harvested["where"],
                        tpl.format(**el.harvested))

            elif src == "ELEMENT_ATTR":
                v = el.table_attrs.get(rule["attr"])
                if v and v != nd.get(rule["attr"]):
                    # FRAMEWORK CHANGE 42 (call site): prefer the LOCATED where
                    # recorded while reading the attr site; fall back to the
                    # unlocated template only when the front-end supplies no
                    # location at all.
                    add(rule["id"], None, prov,
                        el.table_attr_where.get(rule["attr"])
                        or attr_tpl.format(key=rule["attr"]), v)

            elif src == "DEF_SITE_ATTR":
                # FRAMEWORK CHANGE 63 (a): declared here as well as in resolve_fact.
                # A rule kind implemented on only ONE of the two paths is how
                # `inf_filter_condition_UNREACHABLE` stayed invisible: a rule that
                # fires on an element the table did NOT promote it for must still
                # appear as an unmet obligation rather than vanish.
                v = el.table_attrs.get(rule["attr"])
                if v and v != nd.get(rule["attr"]):
                    add(rule["id"], None, prov, self.def_attr_where(el, rule["attr"]), v)

            elif src == "ATTR_RESIDUE":
                # FRAMEWORK CHANGE 68 (a) -- THE RESIDUAL PROPERTY SWEEP.
                #
                # THE DEFECT. Every other rule kind here is a WHITELIST: it names one
                # key, or one xpath, or one porttype. So a property the table does not
                # name is not reported as uncovered -- it is not reported at all. That
                # is the shape of the measured loss on CustomerSummaryDerive.dsx: V0S4
                # states `write_method "write"` (dsx:319-320) and `write_mode "append"`
                # (dsx:323-324), and neither reached the IR, nor a no_slot fact, nor any
                # residue line. A mart materialized as a table REPLACES its rows every
                # run while the document says APPEND, so from run 2 the migration and the
                # original disagree about the target's contents with nothing saying so.
                # The same hole on SSIS swallows `FastLoadKeepNulls false` (dtsx:439-442),
                # whose own @description states that a NULL arriving from the pipeline
                # inserts the destination column's DEFAULT instead of NULL.
                #
                # THIS RULE IS THE COMPLEMENT, not another whitelist: every key in the
                # element's declared property bag that no OTHER rule in this table reads
                # and whose value is not the table's declared neutral default. A property
                # name nobody has thought of yet is therefore reported BY CONSTRUCTION,
                # which is the only form that cannot go quiet on the next document.
                #
                # SUPPRESSION IS `neutral_defaults` AND NOTHING ELSE. There is no
                # per-rule ignore list, deliberately: a curated list of "properties that
                # do not matter" is exactly what the coarse census exclusion was, and it
                # is what swallowed write_mode. `neutral_defaults` is the one declared,
                # reviewable, per-key knob, and it may only be used where the value is a
                # VERIFIED vendor default carrying no design intent. NOTE THE TRAP, which
                # is why that wording is narrow: FastLoadKeepNulls's material value IS
                # its default (false), so "equals the vendor default" does NOT imply "no
                # design intent" and that key must never be declared neutral.
                keys_read = self._attr_keys_read_by_rule()
                for key in sorted(el.table_attrs):
                    if key in keys_read:
                        continue
                    v = el.table_attrs[key]
                    if not v or v == nd.get(key):
                        continue
                    add(rule["id"], key, prov,
                        el.table_attr_where.get(key) or attr_tpl.format(key=key), v)

            elif src == "GROUP":
                for g in el.groups:
                    if rule.get("when_type") is not None and g["type"] != rule["when_type"]:
                        continue
                    if rule.get("when_flag") and not g["flags"].get(rule["when_flag"]):
                        continue
                    if rule.get("requires") == "expression" and not g["expression"]:
                        continue
                    add(rule["id"], g["name"], prov, g["where"] + sfx,
                        tpl.format(**g) if tpl else "")

            elif src == "PORT":
                if el.role in rule.get("exclude_roles", []):
                    continue
                cls = rule.get("porttype_class")
                for p in el.ports:
                    if cls == "INPUT" and not self.is_input(p):
                        continue
                    if cls == "OUTPUT" and not self.is_output(p):
                        continue
                    if cls == "LOCAL" and not self.is_local(p):
                        continue
                    if rule.get("requires") == "default_value" and not p.default_value:
                        continue
                    # FRAMEWORK CHANGE 40: a new predicate, added because the
                    # fabrication bug the SSIS pass found inside the READER turns
                    # up on DataStage inside the SOURCE FORMAT. A .dsx column
                    # states Precision "0" and Scale "0" for a BIGINT
                    # (MaskDemo.dsx dsx:307-310), where 0 does not mean zero -- it
                    # means "not applicable to this type". Provenance cannot catch
                    # this: the value IS at that line, so SOURCE is truthful. Only
                    # a per-platform rule can say "this stated value is a
                    # placeholder", so the table states it and the cost is counted.
                    #
                    # FRAMEWORK CHANGE 52: the placeholder VALUE was hardcoded to 0
                    # by the predicate name `zero_precision`. Kettle's placeholder
                    # is -1, not 0: ValueMetaBase(name, type) delegates to
                    # this(name, type, -1, -1), so <length>-1</length> means "no
                    # length stated" and 0 would mean a real zero. Hardcoding 0
                    # would have silently reported every Kettle column as fine.
                    # The placeholder set is now table-declared.
                    if rule.get("requires") == "placeholder_precision":
                        if p.precision not in rule["placeholder_values"]:
                            continue
                    # FRAMEWORK CHANGE 53: a new predicate. Kettle's <type> inside
                    # <fields><field> is POLYSEMOUS ACROSS STEP TYPES: on a
                    # RowGenerator it is a real data type resolved through
                    # ValueMetaFactory.getIdForValueMeta, but on a SystemInfo step
                    # it is a SELECTOR naming which system value to emit
                    # ("transformation name", "kettle version") from the
                    # SystemDataTypes enum. Same element, same reader, different
                    # meaning. Provenance again cannot catch it -- the value IS at
                    # that line -- so the table declares the closed type
                    # vocabulary and anything outside it is counted as a cost.
                    if rule.get("requires") == "datatype_outside_vocabulary":
                        if p.datatype in rule["vocabulary"]:
                            continue
                    # FRAMEWORK CHANGE 55: a PORT rule could only be predicated on
                    # facts the framework already reads INTO a Port -- its default
                    # value, its precision, its connectivity. A per-column fact the
                    # framework does NOT read had no predicate at all, so a rule
                    # naming one fired on EVERY column.
                    #
                    # This was found as a live FABRICATION, not by inspection. The
                    # Kettle table declares a rule for <nullif>, a per-field null
                    # substitution with no IR slot. With no predicate it reported
                    # "field 'trans_name' declares a nullif substitution" for the
                    # two SystemInfo fields at sample_trans.ktr:92-99, which state
                    # no <nullif> element at all -- a fact present in the output and
                    # absent from the source, which is the exact bug class the SSIS
                    # precision default was. The predicate asks the port's own node.
                    if rule.get("requires") == "attr_present":
                        if p.node is None or not any(p.node.get(a) is not None
                                                     for a in rule["attrs"]):
                            continue
                    if rule.get("connectivity") == "UNCONNECTED":
                        pool = connected_in if cls == "INPUT" else connected_out
                        if p.name in pool:
                            continue
                    if rule.get("skip_excluded_groups") and self.excluded_group(el, p):
                        continue
                    disp = (dvp["discardable_label"]
                            if dvp["error_function_prefix"]
                            and p.default_value.startswith(dvp["error_function_prefix"])
                            else dvp["load_bearing_label"])
                    add(rule["id"], p.name, prov, p.where + sfx,
                        render_detail(rule, tpl, {
                            "default_value": p.default_value, "disposition": disp,
                            "name": p.name, "datatype": p.datatype,
                            "lineage": p.lineage, "group": p.group}))

            elif src == "FIELD_EDGE":
                for fe in self.idn.inbound(name):
                    if rule.get("when") == "RENAME" and fe.from_field == fe.to_field:
                        continue
                    add(rule["id"], fe.to_field, prov, fe.where + sfx,
                        render_detail(rule, tpl, {
                            "from_instance": fe.from_instance,
                            "from_field": fe.from_field, "to_field": fe.to_field}))

            elif src == "LOAD_ORDER":
                if el.load_order:
                    add(rule["id"], None, prov,
                        self.table["structure"]["load_order"]["xpath"] + sfx, el.load_order)

            elif src == "ELEMENT_FLAG":
                v = el.flags.get(rule["flag"])
                if v is not None and v != nd.get(rule["flag"]):
                    add(rule["id"], None, prov, el.where + sfx, v)

            elif src == "CONTAINER":
                if el.container:
                    add(rule["id"], None, prov, el.where,
                        render_detail(rule, tpl, {"container": el.container}))

            elif src == "CHILD_ATTR":
                # FRAMEWORK CHANGE 28: there was no rule kind for a fact carried
                # on a singleton CHILD element of the element. Informatica's
                # TABLEATTRIBUTE site covers name/value pairs only; an SSIS
                # <connection> is a child element with meaningful attributes.
                node = self.idn.node_of(el)
                for i, ch in enumerate(node.findall(rule["xpath"]), start=1):
                    v = ch.get(rule["attr"])
                    # FRAMEWORK CHANGE 56: every other rule kind checked the value
                    # against neutral_defaults before creating an obligation; this
                    # one never did, and no prior platform noticed because DataStage
                    # has exactly one CHILD_ATTR rule and no neutral default for it.
                    # Both new platforms are full of child-object defaults -- an ADF
                    # activity policy states retry 0 and retryIntervalInSeconds 30,
                    # which are Microsoft's DOCUMENTED defaults, and every Kettle
                    # step states partitioning method "none" -- so the missing check
                    # inflated NO_SLOT with facts carrying no design intent. Found by
                    # writing a neutral_defaults entry, watching the fact appear
                    # anyway, and reading the interpreter.
                    if v and v != nd.get(rule["attr"]):
                        add(rule["id"], ch.get(rule.get("key_attr") or rule["attr"]), prov,
                            f"{el.where}/{rule['xpath'].lstrip('./')}[{i}]"
                            + self.idn.attr_ref(ch, rule["attr"]), v)

            elif src == "CHILD_TEXT":
                # FRAMEWORK CHANGE 68 (c): declared in `resolve_fact` since FRAMEWORK
                # CHANGE 60 (c) and NEVER on this path -- found by the `else: raise`
                # below, not by inspection. This is the identical defect FRAMEWORK
                # CHANGE 63 (a) records for DEF_SITE_ATTR, one rule kind later: a kind
                # implemented on the PROMOTION path only fires for the kinds whose
                # `element_fields` name it, and on every other element it raised
                # nothing at all rather than an unmet obligation.
                #
                # MEASURED EXPOSURE ON THE CURRENT FIXTURES: nil. Both CHILD_TEXT rules
                # in platform_ssis.json are promoted by the only kinds whose documents
                # state the property (`oledb_open_rowset` by both OLE DB endpoints,
                # `cspl_friendly_expression` by Microsoft.ConditionalSplit), and no
                # other element in either .dtsx states either property -- so the census
                # had nothing to report and the hole was invisible. It would have opened
                # the moment a table declared a CHILD_TEXT rule it does not promote,
                # which is the ordinary case for every other rule kind here.
                node = self.idn.node_of(el)
                for i, ch in enumerate(node.findall(rule["xpath"]), start=1):
                    v = (ch.text or "").strip()
                    key = ch.get("name") or ch.tag
                    if v and v != nd.get(rule.get("neutral_key") or key, object()):
                        add(rule["id"], key, prov,
                            f"{el.where}/{rule['xpath'].lstrip('./')}[{i}]/text()", v)

            elif src == "CHILD_TEXT_TEMPLATE":
                # Declared on BOTH paths for the reason DEF_SITE_ATTR and CHILD_TEXT
                # already give: a rule fires here only for the kinds `element_fields`
                # names it for, and every other kind reading the same document shape
                # must still see an unmet obligation rather than silence.
                hit = self._resolve_child_text_template(el, rule)
                if hit is not None:
                    key, where, value = hit
                    add(rule["id"], key, prov, where, value)

            elif src == "NONE":
                # A DOCUMENTATION PSEUDO-RULE. platform_informatica.json's
                # `__comment__` entry carries the list's own rationale and reads
                # nothing. Named explicitly so the else below can raise.
                pass

            else:
                # FRAMEWORK CHANGE 68 (b): the chain used to fall off the end in
                # SILENCE. A rule whose `from` this interpreter does not implement --
                # a new kind added to a table before the interpreter, or a typo --
                # produced no fact and no error, which is indistinguishable from "the
                # document does not state it". That is the same closed-vocabulary
                # failure `_attach_definitions` raises on for an undeclared def-site
                # name and `resolve_fact` raises on for an unimplemented promotion;
                # this was the one remaining branch of the three that stayed quiet.
                raise ValueError(
                    f"no_slot_facts rule '{rule['id']}' declares from={src!r}, which "
                    f"record_no_slot_facts does not implement. A rule kind the census "
                    f"cannot read raises no obligation, which looks exactly like a fact "
                    f"the source does not state.")

    def _attr_keys_read_by_rule(self) -> frozenset:
        """Property-bag keys that some OTHER rule in this table already reads.

        Used only by ATTR_RESIDUE, which is the COMPLEMENT of this set. DERIVED from
        the rules rather than restated beside them, for the reason the
        `dsx-link-record` census exclusion gives for deriving itself from
        `edge_levels`: two hand-maintained lists of the same thing drift, and the
        drift shows up as a FALSE unmet obligation (the residual sweep re-reporting a
        key that a named rule already reports) or a FALSE silence.

        Two rule shapes name a bag key:
          ELEMENT_ATTR / DEF_SITE_ATTR -- `attr` IS the bag key.
          CHILD_ATTR / CHILD_TEXT      -- the key sits in the xpath's own predicate,
                                          `[@<name_attr>='KEY']`, where `name_attr`
                                          comes from the platform's declared
                                          `attr_site` and is never guessed here
                                          (`Name` on DataStage, `name` on SSIS,
                                          `NAME` on Informatica).
        A CHILD_* rule with no such predicate names no single key and contributes
        nothing -- correctly: it reads a site that is not the property bag."""
        at = self._attr_site()
        name_attr = (at or {}).get("name_attr") or "name"
        pat = re.compile(r"\[@" + re.escape(name_attr) + r"='([^']+)'\]")
        keys = set()
        for rule in self.table["no_slot_facts"]:
            src = rule.get("from")
            if src in ("ELEMENT_ATTR", "DEF_SITE_ATTR"):
                keys.add(rule["attr"])
            elif src in ("CHILD_ATTR", "CHILD_TEXT"):
                keys.update(pat.findall(rule.get("xpath", "")))
        return frozenset(keys)

    def _assert_attr_residue_usable(self) -> None:
        """Raise when an ATTR_RESIDUE rule cannot mean what it says.

        THREE WAYS IT CANNOT, each measured or reasoned rather than imagined:

        1. TWO SUCH RULES. The complement of one read-set is one obligation per
           unread key; two rules would raise every unread key twice and DOUBLE the
           cost of the same document fact.

        2. NO DECLARED `attr_site`. The bag is empty on every element, so the sweep
           reports nothing on a platform that may well state properties -- a gate
           incapable of firing, which this project has already found four of.
           platform_adf.json is the live case: its attr site is deliberately absent
           (an activity's own scalars are name/type/description and all three are
           already read), so it must not declare this rule.

        3. `value_from: SELF_ATTRS`. On Pentaho the bag is the STEP NODE's own
           attributes after the scalar lift, so it holds the element's IDENTITY --
           @name and @type -- beside its configuration. MEASURED: a residual sweep
           there reports `name` and `type` as unread residue on 4 of 4 elements of
           safe-stop-gen-rows.ktr, which is false twice over (both are read, and
           `name` IS the element key). Separating identity from configuration needs
           the level's key/kind/display/flag attributes excluded, which is a
           framework change this pass did not make; see the pentaho table's
           `residue.step_scalar_residue_not_swept` for the measured size of the
           family that is therefore still uncounted."""
        rules = [r for r in self.table["no_slot_facts"] if r.get("from") == "ATTR_RESIDUE"]
        if not rules:
            return
        if len(rules) > 1:
            raise ValueError(
                f"{len(rules)} ATTR_RESIDUE rules declared ({[r['id'] for r in rules]}). "
                f"ATTR_RESIDUE is the COMPLEMENT of every other rule's read set, so two "
                f"of them raise every unread property key twice.")
        at = self._attr_site()
        if at is None:
            raise ValueError(
                f"no_slot_facts rule '{rules[0]['id']}' is ATTR_RESIDUE and no def site "
                f"in this table declares an `attr_site`. The property bag is empty on "
                f"every element, so the sweep is a check that cannot fire.")
        if at.get("value_from") == "SELF_ATTRS":
            raise ValueError(
                f"no_slot_facts rule '{rules[0]['id']}' is ATTR_RESIDUE and the declared "
                f"attr_site reads value_from=SELF_ATTRS, so the bag holds the element's "
                f"own identity attributes beside its configuration. The sweep would "
                f"report the element key and kind as unread residue. Exclude the level's "
                f"key/kind/display/flag attributes first.")

    # -- FRAMEWORK CHANGE 59 (ENG-014 spike) ------------------------------

    def rule_by_id(self, rule_id: str) -> dict | None:
        for rule in self.table["no_slot_facts"]:
            if rule["id"] == rule_id:
                return rule
        return None

    def _resolve_child_text_template(self, el, rule: dict):
        """CHILD_TEXT_TEMPLATE -- a predicate assembled from SIBLING child-text
        facts, not read whole off one child.

        THE GAP THIS CLOSES. Alteryx's Filter states a Simple-mode condition as
        THREE separate children (`Simple/Field`, `Simple/Operator`,
        `Simple/Operands/Operand`) and no `<Expression>` text at all -- the shape
        `filter_expression` (CHILD_TEXT) reads for Custom mode. CHILD_TEXT cannot
        answer this: there is no single child whose whole text IS the predicate.

        Fires only when the rule's `templates` map has an entry for the read
        operator AND every placeholder that SPECIFIC template actually
        references is non-blank -- e.g. `IsNull` never looks at `operand`, so
        MEASURED junk left in that field by the Alteryx GUI (`<Operand>1</Operand>`
        on an IsNull condition) is correctly ignored rather than blocking the
        template. An operator the table does not map, or a referenced part left
        blank, returns None -- the same honest degrade every other rule kind here
        gives, never a hollow predicate."""
        node = self.idn.node_of(el)
        raw: dict[str, str] = {}
        where_of: dict[str, str] = {}
        for part, xpath in rule["parts"].items():
            ch = node.find(xpath)
            raw[part] = (ch.text or "").strip() if ch is not None else ""
            where_of[part] = f"{el.where}/{xpath.lstrip('./')}/text()"
        template = rule["templates"].get(raw.get("operator"))
        if template is None:
            return None
        needed = set(re.findall(r"\{(\w+)\}", template))
        if any(not raw.get(part) for part in needed):
            return None
        formatted = {
            part: (raw[part].replace("'", "''") if part == "operand"
                   else raw[part].replace('"', '""'))
            for part in needed
        }
        value = template.format(**formatted)
        cite_parts = ["field", "operator"] + (["operand"] if "operand" in needed else [])
        where = " + ".join(where_of[p] for p in cite_parts)
        return (raw.get("field"), where, value)

    def resolve_fact(self, el, rule_id: str):
        """Re-read a no_slot_facts rule as a POPULATED fact: (key, where, value).

        Returns None when the rule does not fire on this element, which is not an
        error -- adf_First_Pipeline.json's Copy states no storeSettings, so a
        promoted slot for one must simply not appear rather than appear empty.

        Only the rule kinds a promotion currently needs are implemented, and an
        unimplemented kind RAISES rather than returning None. Returning None would
        make a table typo look like 'the source does not state it', which is the
        fabrication direction this framework exists to prevent."""
        rule = self.rule_by_id(rule_id)
        if rule is None:
            raise ValueError(f"promoted fact '{rule_id}' is not a no_slot_facts rule")

        nd = self.table["neutral_defaults"]
        src = rule["from"]

        if src == "CHILD_ATTR":
            node = self.idn.node_of(el)
            for i, ch in enumerate(node.findall(rule["xpath"]), start=1):
                v = ch.get(rule["attr"])
                if v and v != nd.get(rule["attr"]):
                    where = (f"{el.where}/{rule['xpath'].lstrip('./')}[{i}]"
                             + self.idn.attr_ref(ch, rule["attr"]))
                    return (ch.get(rule.get("key_attr") or rule["attr"]), where, v)
            return None

        if src == "CONTAINER":
            if el.container:
                return (None, el.where, el.container)
            return None

        # FRAMEWORK CHANGE 65 (a): HARVEST -- the value is one named part of a
        # DEF-SITE HARVEST, i.e. of a definition the element only REFERENCES.
        #
        # THE GAP THIS CLOSES. Informatica states the physical source table on a
        # separate <SOURCE> definition; `collapse` absorbs it into the Source
        # Qualifier that names it as its ASSOCIATED_SOURCE_INSTANCE and carries the
        # harvest across (identify.py:986). The census could already report the
        # harvest as a NO_SLOT fact, and `resolve_fact` could not read it at all --
        # so the one platform whose document actually STATES the source table could
        # not put it in the IR, and its staging model came out with a bare `FROM`.
        #
        # `harvest_key` names WHICH part is the field, because a harvest is a tuple:
        # {database, schema, table, database_type}. Reading the whole dict would
        # force this method to decide which part is the table name, which is a
        # platform fact and belongs in the table.
        if src == "HARVEST":
            key = rule.get("harvest_key")
            if key is None:
                raise ValueError(
                    f"no_slot_facts rule '{rule_id}' is a HARVEST and states no "
                    "harvest_key, so there is no way to know which part of the "
                    "harvested tuple the IR field wants")
            v = el.harvested.get(key)
            if v and v != nd.get(key):
                return (key, el.harvested.get("where", el.where), v)
            return None

        # FRAMEWORK CHANGE 60 (c): two further rule kinds, added because the payload a
        # widened element kind needs is often NOT an attribute on a child.
        #
        # CHILD_TEXT -- the value is a child element's TEXT. This is how SSIS states
        # nearly everything interesting: a Conditional Split's predicate is the text of
        # <property name="FriendlyExpression">, and a destination's table is the text of
        # <property name="OpenRowset">. CHILD_ATTR structurally cannot read either.
        if src == "CHILD_TEXT":
            node = self.idn.node_of(el)
            for i, ch in enumerate(node.findall(rule["xpath"]), start=1):
                v = (ch.text or "").strip()
                if v and v != nd.get(rule.get("neutral_key") or "", object()):
                    where = f"{el.where}/{rule['xpath'].lstrip('./')}[{i}]/text()"
                    return (ch.get("name") or ch.tag, where, v)
            return None

        if src == "CHILD_TEXT_TEMPLATE":
            return self._resolve_child_text_template(el, rule)

        # ELEMENT_ATTR -- the value is an attribute on the element's OWN node. Already
        # a declared rule kind used by the NO_SLOT census, but never implemented here,
        # so promoting one raised. Informatica's target names its table in the
        # INSTANCE's own @NAME, and Pentaho's projection lifts leaf child elements to
        # attributes, so several platforms need exactly this and nothing more.
        if src == "ELEMENT_ATTR":
            node = self.idn.node_of(el)
            v = node.get(rule["attr"])
            if v and v != nd.get(rule["attr"]):
                return (rule["attr"], el.where + self.idn.attr_ref(node, rule["attr"]), v)
            return None

        # FRAMEWORK CHANGE 63 (a): DEF_SITE_ATTR -- the value is a named property of
        # the element's DEFINITION, not of the node the element sweep matched.
        #
        # THE GAP THIS CLOSES, exactly. Informatica states a Filter's predicate on the
        # resolved TRANSFORMATION as a property of the def-site property bag, while
        # node_of() returns the INSTANCE. None of CHILD_ATTR / CHILD_TEXT /
        # ELEMENT_ATTR / CONTAINER can cross that reference: all four query the
        # instance node. The platform table declared the field required and pointed it
        # at a rule named `..._UNREACHABLE`, so every Filter degraded to
        # UnsupportedTransformation with an EWI -- an honest encoding of a gap that was
        # never actually unreachable.
        #
        # WHY IT READS THE PROPERTY BAG RATHER THAN RE-QUERYING THE DEF NODE. The bag
        # is populated by _read_table_attrs FROM that node, under the site's own
        # table-declared attr_site -- child name/value pairs on one platform, the
        # node's own attributes on another. Re-querying here would duplicate that
        # projection and would have to name a shape, which is precisely the
        # per-platform assumption this file must not contain. The bag's contents
        # therefore follow `def_site` automatically: SELF means the element's own node,
        # a named site means the definition it references.
        #
        # NOT folded into ELEMENT_ATTR even though the NO_SLOT census's ELEMENT_ATTR
        # branch reads the same bag. The two branches of ELEMENT_ATTR already disagree
        # -- the census reads el.table_attrs, this method reads the instance node's own
        # attributes -- and an Informatica Target's TableName depends on the second
        # meaning. Overloading the name a third time would make a rule's behaviour
        # depend on which code path reached it.
        if src == "DEF_SITE_ATTR":
            v = el.table_attrs.get(rule["attr"])
            if v and v != nd.get(rule["attr"]):
                return (rule["attr"], self.def_attr_where(el, rule["attr"]), v)
            return None

        raise ValueError(f"promotion is not implemented for rule kind '{src}'")

    def def_attr_where(self, el, key: str) -> str:
        """Citation for a def-site property.

        Prefers the LOCATED where the front-end recorded while reading the attr site
        (FRAMEWORK CHANGE 42). The fallback is anchored at the def query rather than
        left as a bare relative template, because an unanchored
        `TABLEATTRIBUTE[@NAME='x']/@VALUE` is true of every definition in the file
        and so is not a citation at all."""
        located = el.table_attr_where.get(key)
        if located:
            return located
        tpl = self.table["structure"].get("attr_where_template")
        rel = tpl.format(key=key) if tpl else "@" + key
        return f"{el.def_where}/{rel}" if el.def_where else rel

    # -- FRAMEWORK CHANGE 63 (b): THE PLACEHOLDER CARRIES THE SOURCE BODY --------

    #: Jinja delimiters. dbt renders Jinja BEFORE any SQL parser sees the file, and
    #: Jinja does not respect SQL comments -- a `{{` inside a `--` line is still a
    #: template expression, and an unbalanced one fails the whole model. So these
    #: are the only sequences that have to be neutralised for a fragment to be safe
    #: inside generated SQL.
    _JINJA_ESCAPES = (("{{", "{ {"), ("}}", "} }"), ("{%", "{ %"), ("%}", "% }"),
                      ("{#", "{ #"), ("#}", "# }"))

    def unsupported_body(self, el) -> str | None:
        """The element's own source fragment, made safe to sit inside a SQL comment.

        WHY THE PLACEHOLDER NEEDED THIS. `_unsupported` carried the native kind NAME
        and nothing else, so the whole of a degraded element rendered as one line --
        `--CTransformerStage`. That names WHAT failed and states nothing about what
        was lost. Vanilla SnowConvert's not-supported path emits the original element
        commented out (see UnsupportedTransformationConfigurator.GetCommentText), and
        that is strictly more useful to both readers of the file: a human recovering
        the logic by hand, and a tier-3 model asked to replace the model it is
        reading.

        THREE PROPERTIES THIS GUARANTEES, each because the alternative was measured
        or is a known hazard:

        1. NEWLINES ARE PRESERVED, not stripped. The engine's own
           UnsupportedTransformationComments.WithSourceText splits on CRLF/CR/LF and
           emits ONE line comment per line, so a multi-line fragment renders as a
           block of `--` lines and no embedded newline ever reaches a comment node.
        2. JINJA DELIMITERS ARE NEUTRALISED. See _JINJA_ESCAPES: a SQL comment does
           not protect a `{{` from dbt's renderer, which runs first. Every escape is
           ANNOUNCED in the body, so the fragment never claims to be verbatim when
           it is not. UNVERIFIED on the current fixtures: MEASURED 0 delimiters over
           the 27 fragments the five platform tables produce across every fixture in
           runall.py plus the four blind inputs, so this path is implemented and
           unexercised. Kept anyway: an ADF pipeline expression is
           `@{concat(...)}` and an SSIS property can hold arbitrary text, so the
           first source document that carries one must not be the thing that
           discovers dbt renders comments.
        3. THE LENGTH IS CAPPED BY THE PLATFORM TABLE and the cut is ANNOUNCED. A
           DataStage connector stage carries a 4 KB XMLProperties blob and a job
           record can be the whole export; an uncapped body would turn a placeholder
           into a copy of the source file. `structure.unsupported_body_max_chars` is
           policy, declared per platform, for the same reason detail_max_chars is.

        DELIBERATELY NOT RECORDED AS A SLOT. An element's whole source text is not an
        obligation the contract has a field for, and adding it as NO_SLOT would put a
        term in every degraded element's fit DENOMINATOR -- lowering the score of
        five platforms to report an improvement in the artifact. The fit number
        measures representation, and this is a comment.

        Returns None when the front-end supplies no fragment, which the caller must
        keep distinguishable from an empty one -- the field is then simply absent and
        the consumer falls back to the kind name.
        """
        raw = self.idn.source_text(el)
        if not raw or not raw.strip():
            return None
        body = raw.replace("\r\n", "\n").replace("\r", "\n")
        escaped = 0
        for bad, safe in self._JINJA_ESCAPES:
            if bad in body:
                escaped += body.count(bad)
                body = body.replace(bad, safe)
        if escaped:
            body += (f"\n... [{escaped} Jinja delimiter(s) in the source were spaced "
                     f"apart above so dbt's renderer cannot read them as template "
                     f"syntax; this fragment is NOT verbatim] ...")
        lim = self.table["structure"].get("unsupported_body_max_chars")
        if lim and len(body) > lim:
            body = body[:lim].rstrip() + (
                f"\n... [source fragment truncated at {lim} of {len(body)} chars by "
                f"structure.unsupported_body_max_chars] ...")
        return body

    def promote_containment(self, node: dict, name: str, el) -> set:
        """FRAMEWORK CHANGE 59 (b) (ENG-001 spike).

        Runs for EVERY element, supported or not. Containment is orthogonal to
        whether the element's kind is representable: the ADF notebook and validation
        activities are unsupported and still live inside a pipeline, and the DataStage
        fixture's 31 non-job elements were unrepresentable on exactly this fact. Only
        promoting it for supported elements would close the gap where it costs least
        and leave it open where it was found."""
        promoted = set()
        for ir_field, rule_id in (self.table.get("containment_slots") or {}).items():
            hit = self.resolve_fact(el, rule_id)
            promoted.add(rule_id)
            if hit is None:
                continue
            _key, where, value = hit
            node.setdefault("container", {})[ir_field] = value
            self.slots.append(Slot(name, f"node.container.{ir_field}",
                                   SOURCE, where, value))
        return promoted

    # -- the graph ---------------------------------------------------------

    def _assert_model_names_injective(self, nodes: list[dict]) -> None:
        """FRAMEWORK CHANGE 58 (gate). Two distinct elements must never share a
        model name.

        This is a LOUD failure rather than a recorded gap, and the asymmetry is
        deliberate. A missing field costs one obligation and is visible in the fit
        score; two elements sharing a model name costs a whole MODEL and is visible
        nowhere -- `DbtModelsWriter` writes `{model.Name}.sql` with `WriteAllText`
        and logs `Successfully wrote model` for each one, so the last write wins and
        every line of the log says it worked. Measured before qualification: 29
        DataStage models became 9 files, and the same collision independently
        reduced 18 lineage rows to 6.

        Raising here also stops the two naming rules from silently undoing each
        other: qualification makes names unique and sanitisation could merge them
        again (`a-b` and `a_b` both become `a_b`)."""
        seen: dict[str, str] = {}
        for node in nodes:
            name = node["modelName"]
            if name in seen:
                raise ValueError(
                    f"naming_policy '{self.table['naming_policy']['policy_id']}' maps two distinct "
                    f"elements to one model name {name!r}: {seen[name]!r} and {node['id']!r}. "
                    "The dbt writer would overwrite one with the other and report success for both. "
                    "Widen the scope (qualify_with_container) or change the sanitisation rule -- do "
                    "not add a counter, which invents a name the document does not state.")
            seen[name] = node["id"]

    # -- column propagation ------------------------------------------------

    def _propagation_policy(self) -> dict:
        """The table's declared buffer semantics, defaulted to OFF.

        FRAMEWORK CHANGE 64 (a). A table that says nothing about propagation gets
        the pre-change behaviour byte-for-byte, so adding this section to one
        platform cannot move another.
        """
        pol = dict(self.table.get("column_propagation") or {})
        pol.setdefault("mode", "NONE")
        pol.setdefault("stop_at_kinds", [])
        pol.setdefault("stop_at_roles", [])
        pol.setdefault("algorithm_id", "predecessor_column_propagation.v1")
        if pol["mode"] not in ("NONE", "ACCUMULATE", "FILL_WHEN_UNDECLARED"):
            raise ValueError(
                f"column_propagation.mode {pol['mode']!r} is not implemented. "
                "Declared modes are NONE, ACCUMULATE and FILL_WHEN_UNDECLARED.")
        return pol

    def propagate_columns(self, nodes: list[dict]) -> None:
        """FRAMEWORK CHANGE 64: AN ELEMENT'S COLUMNS ARE NOT ONLY ITS OWN.

        WHAT WAS MISSING. Every column this producer emitted came from the
        element's OWN declarations. Nothing walked the graph, so an element that
        states no projection projected nothing, and an element that states only
        the columns it ADDS projected only those. Two measured defects were the
        same hole:

          * SSIS `CSPL Filter BirthYear` emitted InputColumns=['BirthYear'] and
            OutputColumns=[] while the synchronous buffer at that point carried
            six. Its model projected one column, so the downstream destination
            model referenced `FullName` -- absent upstream -- and the only
            correctly translated model in the tree became an orphan.
          * On DataStage, `GetSourceModelName(ctx, filter.OutputColumns, filter)`
            returns null when OutputColumns is empty, and `FilterTranslator`
            substitutes `NotFoundPlaceholder`. That is the literal cause of
            `{{ ref('int_NOT_FOUND') }}` and its dbt1005 -- an EMPTY COLUMN LIST
            breaking a MODEL REFERENCE, two floors away from where it was read.

        REFERENCE IMPLEMENTATION. `SsisProjectionContext.GetEffectiveOutputColumns`
        (Assemblies/EtlToDbt/DtsxSsis/SsisProjectionContext.cs:280) walks
        predecessor edges backwards accumulating each visited element's outputs and
        stops at elements that define their own output shape rather than passing
        input through. Its stop list is five SSIS componentClassIDs, so per this
        module's neutrality contract the list is TABLE-DECLARED here, on two axes:
        native kind (`stop_at_kinds`) and normalised role (`stop_at_roles`).

        TWO MODES, BECAUSE THE BUFFER RULE IS A PLATFORM FACT.
          ACCUMULATE -- a synchronous output carries the input buffer PLUS the
            columns the element declares. SSIS. Declaring only the new columns is
            the .dtsx's normal form, so a declared list is never exhaustive.
          FILL_WHEN_UNDECLARED -- a declared column list IS exhaustive, and only
            the absence of one means "whatever arrives here". DataStage states this
            outright (Runtime Column Propagation; `LinkHasMetaDatas "False| "`),
            and Informatica ports are explicit by construction.
        A table that declares neither gets NONE and is untouched.

        DELIBERATE DEVIATIONS FROM THE REFERENCE, both widenings:
          1. The engine follows `Edges.FirstOrDefault(x => x.To == node)` -- ONE
             predecessor. This unions ALL of them in edge order and dedupes by
             folded name, because a two-input element whose kind is not in the stop
             list would otherwise silently see half its buffer.
          2. Accumulated columns are ordered UPSTREAM-FIRST rather than self-first.
             The engine's list is consumed as a lookup set; ours becomes a SELECT
             list, and buffer order is the order the rows actually carry.

        PROVENANCE. A propagated column is NOT recorded as SOURCE. It is not read
        from the document at this element -- there is no location to cite there --
        so it earns exactly one DERIVED slot per element naming the algorithm, the
        columns added and the element each came from. Recording them as SOURCE
        would have credited five platforms' fit scores with readings no query made.

        A NODE THE HYDRATOR DROPS IS A BARRIER, not a pipe. `$kind: null` keeps a
        node out of the graph and takes every edge touching it with it, so carrying
        a buffer through one would assert lineage the emitted graph does not have.
        """
        pol = self._propagation_policy()
        mode = pol["mode"]
        if mode == "NONE":
            return
        by_id = {n["id"]: n for n in nodes}
        stop_kinds = set(pol["stop_at_kinds"])
        stop_roles = set(pol["stop_at_roles"])
        preds: dict[str, list[str]] = {}
        for e in self.idn.element_edges():
            preds.setdefault(e["to"], []).append(e["from"])

        def declared(nid: str) -> list[dict] | None:
            """The node's own OutputColumns, or None when the node is a barrier."""
            node = by_id.get(nid)
            if node is None or node["element"].get("$kind") is None:
                return None
            return list(node["element"].get("OutputColumns") or [])

        def stops(nid: str) -> bool:
            el = self.idn.elements.get(nid)
            return el is not None and (el.kind_raw in stop_kinds
                                       or el.role in stop_roles)

        memo: dict[str, list[dict]] = {}

        def carried(c: dict) -> dict:
            """A column as it ARRIVES at a downstream element.

            THE EXPRESSION IS DROPPED, and this is a correctness rule rather than
            tidiness. `FullName` is a ColumnExpression at the Derived Column that
            declares it; one hop later it is an ordinary column OF THAT MODEL, and
            copying the expression down would make the next model RE-EVALUATE
            `FirstName || ' ' || MiddleName || ' ' || LastName` against a relation
            that already has FullName in it -- silently wrong wherever the operands
            are not also projected, and duplicated work where they are. The engine's
            own accumulator does exactly this: AddColumnsFromOutput
            (SsisProjectionContext.cs:434) builds a plain `Column` from the name and
            datatype and never a ColumnExpression. Caught by the emitter reporting
            the same expression rewritten TWICE for one declaration.
            """
            return {k: v for k, v in c.items()
                    if k not in ("$kind", "Expression")}

        def effective(nid: str, seen: frozenset) -> list[dict]:
            if nid in memo:
                return memo[nid]
            if nid in seen:
                return []                      # cycle guard: a loop carries nothing
            own = declared(nid)
            if own is None:
                return []                      # barrier
            if stops(nid) or (mode == "FILL_WHEN_UNDECLARED" and own):
                memo[nid] = own
                return own
            out, taken = [], set()
            for p in preds.get(nid, []):
                for c in effective(p, seen | {nid}):
                    key = c["Name"].lower()
                    if key not in taken:
                        taken.add(key)
                        out.append(carried(c))
            # The element's OWN declaration always wins on a name collision: it may
            # carry an expression, and the upstream copy never does.
            own_names = {c["Name"].lower() for c in own}
            out = [c for c in out if c["Name"].lower() not in own_names] + own
            memo[nid] = out
            return out

        for nid, node in by_id.items():
            own = declared(nid)
            if own is None or stops(nid):
                continue
            if mode == "FILL_WHEN_UNDECLARED" and own:
                continue
            eff = effective(nid, frozenset())
            added = [c for c in eff if c["Name"].lower()
                     not in {o["Name"].lower() for o in own}]
            if not added:
                continue
            node["element"]["OutputColumns"] = [dict(c) for c in eff]
            # FRAMEWORK CHANGE 64 (c): RENUMBER THE SLOT PATHS THIS INSERTION INVALIDATED.
            #
            # `eff` is prefix + own, with the element's OWN declarations LAST (see the
            # deviation note above: buffer order is the order the rows carry). So every
            # slot path recorded while reading the declarations -- `element.OutputColumns[0]`
            # for the first declared column -- now addresses a PROPAGATED column instead.
            #
            # MEASURED on DerivedColumn.dtsx before this fix, and it is a provenance record
            # pointing at the wrong field of the shipped IR, not a cosmetic index:
            #   slot element.OutputColumns[0].Name cites outputColumn[1][@name='FullName']
            #   emitted OutputColumns[0].Name is 'FirstName'   (FullName moved to [4])
            # Four such disagreements on that one document, invisible until the provenance
            # audit gained an XML locator. `len(added)` is exactly the prefix length,
            # because `added` IS the prefix: every propagated column is by construction one
            # whose folded name is not among `own`.
            shift = len(added)
            prefix = "element.OutputColumns["
            for s in self.slots:
                if s.element != nid or not s.path.startswith(prefix):
                    continue
                head, sep, tail = s.path[len(prefix):].partition("]")
                if sep and head.isdigit():
                    s.path = f"{prefix}{int(head) + shift}]{tail}"
            origin = ", ".join(sorted({p for p in preds.get(nid, [])})) or "<none>"
            self.slots.append(Slot(
                nid, f"element.OutputColumns[+{len(added)} propagated]", DERIVED,
                pol["algorithm_id"],
                (f"{mode}: this element declares NO projection, so the {len(added)} "
                 f"column(s) it carries "
                 if not own else
                 f"{mode}: the {len(own)} column(s) this element declares are not the "
                 f"whole buffer it carries; {len(added)} more ")
                + f"({', '.join(c['Name'] for c in added)}) reached it through "
                f"predecessor {origin} and are DERIVED from the graph, not read from "
                f"the document at this element"))
            # FRAMEWORK CHANGE 64 (b): the pre-existing MISSING obligation is KEPT.
            # `element.OutputColumns` MISSING states a fact about the DOCUMENT -- a
            # supported element with a link in this direction that declares no
            # projection -- and that fact is still true. Retiring it would have
            # turned every propagation into a free +1 and hidden the DataStage
            # measurement FRAMEWORK CHANGE 37 exists to surface (28 of 29 stages
            # carry no column metadata). Its detail line is amended instead, so a
            # reader cannot conclude the emitted model projects nothing.
            for s in self.slots:
                if (s.element == nid and s.path == "element.OutputColumns"
                        and s.provenance == MISSING):
                    s.detail += ("; the IR field IS populated, by "
                                 f"{pol['algorithm_id']} -- this obligation stays "
                                 "unmet because the DOCUMENT states no projection here")

    def emit(self) -> dict:
        nodes = [self.emit_node(n, el) for n, el in self.idn.elements.items()]
        self._assert_model_names_injective(nodes)
        self.propagate_columns(nodes)
        edges = []
        mech = self.table["edge_policy"]["element_edges_from"]
        derivation = ("EXPLICIT_EDGE_ELEMENT" if mech == "EXPLICIT_EDGE_ELEMENTS"
                      else self.table["edge_policy"]["collapse_connectors_by"])
        eprov = SOURCE if mech == "EXPLICIT_EDGE_ELEMENTS" else DERIVED
        for e in self.idn.element_edges():
            ej = {"from": e["from"], "to": e["to"]}
            if e["label"] is not None:
                ej["label"] = e["label"]
            edges.append(ej)
            where = e.get("where") or derivation
            for endpoint in ("from", "to"):
                self.slots.append(Slot("<edges>", f"edge[{e['from']}->{e['to']}].{endpoint}",
                                       eprov, where))
            if e["label"] is not None:
                self.slots.append(Slot("<edges>", f"edge[{e['from']}->{e['to']}].label",
                                       SOURCE,
                                       e.get("where")
                                       or self.table["edge_policy"]["label_source"]))
        # FRAMEWORK CHANGE 63: THE IR NOW STATES WHICH PLATFORM PRODUCED IT.
        #
        # WHY THIS FIELD EXISTS, and it is not metadata for a log line. `ShimSteps
        # .TranslateExpressions` in AiFirstSsisSemanticsShim.cs rewrites expression text with three
        # SSIS-dialect rules -- `[FUNC](` -> `FUNC(`, `"lit"` -> `'lit'`, and `+` -> `||` -- and
        # applied them to EVERY platform, because the shim was never told which platform produced the
        # IR. Its sibling SynthesizePassThrough was DELETED for exactly that (it fabricated four
        # columns on Informatica). This one was measured harmless only by fixture accident:
        # 0 rewrites on Informatica/DataStage/Pentaho/ADF and 2 and 1 on the two SSIS fixtures,
        # because those four fixtures happen to contain no double-quoted literal and no bracketed
        # function name. An Informatica expression containing a double-quoted literal -- legal, and
        # meaning a STRING in PowerCenter's expression language -- would be rewritten by a rule
        # written for another language.
        #
        # The previous pass declined to gate it because "gating it needs the platform identity to
        # cross the process boundary, which is an IR-schema change". We own this schema, so the
        # change is here: every platform_*.json already declares `platform`, and the value is copied
        # verbatim rather than derived, so a new table needs no code change to be gateable.
        #
        # NOT a node and not an edge: it is a property of the DOCUMENT, so it sits beside them. The
        # C# hydrator reads `nodes` and `edges` by name and ignores unknown root keys, which is why
        # this addition does not change a single hydrated graph.
        return {"platform": self.table["platform"], "nodes": nodes, "edges": edges}

    def emit_node(self, name: str, el) -> dict:
        # FRAMEWORK CHANGE 65: WHERE THE MODEL'S FINGERPRINTS GO INTO THE IR.
        #
        # Slots created between here and the return are this element's; the MODEL-provenance
        # ones among them are exactly the facts a model authored, and they are attached to the
        # node so the C# half can mark the ARTIFACT. Snapshotting the ledger rather than
        # instrumenting each site is deliberate: MODEL slots are appended in four places today
        # (element_fields escalation, sidecar $kind, its promoted fields, sidecar
        # OutputColumns) and a fifth would otherwise ship unmarked -- which is the defect
        # itself, one level up.
        _model_mark = len(self.slots)
        # FRAMEWORK CHANGE 32 (call site): ir_kind may depend on role as well as
        # native kind. See Identification.dispatch_for.
        dispatch = self.idn.dispatch_for(el)
        ir_kind = dispatch["ir_kind"]
        key_attr = self.idn.key_attr_of(el)

        # FRAMEWORK CHANGE 60: PAYLOAD-DEPENDENT KINDS, and the rule that a missing
        # payload DEGRADES rather than upgrades.
        #
        # Widening the hydrator past source-and-expression means some element kinds
        # carry a mandatory scalar: a FilterTransformation is meaningless without its
        # predicate, a TargetTransformation without its table name. `element_fields`
        # declares those, per kind, as {ir_field: {rule, required}} where `rule` is a
        # no_slot_facts id -- so the extraction is table-declared and cited, exactly
        # like external_io_slots, rather than hardcoded per platform in this emitter.
        #
        # WHY REQUIRED MEANS DEGRADE, NOT EMIT-EMPTY. This is a safety property, not
        # tidiness. FilterTranslator's shared base substitutes `WHERE TRUE` for an
        # empty predicate and records that only as a log warning. A filter that
        # silently becomes TRUE does not fail -- it returns EVERY ROW, and the model
        # looks like a clean migration. Degrading to UnsupportedTransformation instead
        # puts a blocking EWI in the artifact where a reviewer actually sees it.
        #
        # So an unextractable predicate must never become a FilterTransformation. The
        # decision belongs HERE and not in the hydrator: the hydrator throwing would
        # lose the whole document over one element, whereas the producer can degrade a
        # single node and keep the rest. The hydrator still throws if a producer
        # ignores this contract, which is the same treatment an unknown $kind gets.
        payload: dict = {}
        payload_missing: list[str] = []
        # FRAMEWORK CHANGE 68 (d): rule ids whose value actually REACHED `payload`, so
        # `record_no_slot_facts` can suppress them.
        #
        # THE DEFECT, and it is the one platform_ssis.json's `_element_fields_comment`
        # already describes -- found again, in the mechanism rather than in a table.
        # `external_io_slots` and `containment_slots` both add their rule ids to
        # `promoted`; `element_fields` NEVER DID. So a rule promoted into an IR field
        # was ALSO reported as a slotless NO_SLOT fact, citing the same location with
        # the same value, on an element whose IR field is SOURCE-populated from it. A
        # FALSE unmet obligation -- the one case where retiring an obligation is
        # correct, because the document states the fact and the IR carries it.
        #
        # WHY IT WAS INVISIBLE, per rule, because "no output changed" is what let it
        # sit: `oledb_open_rowset` and `cspl_friendly_expression` are CHILD_TEXT, a kind
        # the census did not implement until FRAMEWORK CHANGE 68 (c) -- so the duplicate
        # could not be raised. `inf_target_instance_name` is ELEMENT_ATTR @NAME and the
        # census's ELEMENT_ATTR branch reads the TABLEATTRIBUTE bag, which has no NAME
        # key. That left THREE rules where the duplicate was live and simply not on a
        # canonical fixture: `dsx_prop_table` / `dsx_prop_where` (MEASURED on
        # CustomerSummaryDerive.dsx: `!dsx_prop_table[table]` unmet on V0S1 and V0S4 and
        # `!dsx_prop_where[where]` unmet on V0S3, all three with element.TableName /
        # element.FilterConditions populated from the very same subrecord), and
        # `ktr_table_output_table` on the blind .ktr's TableOutput step. MaskDemo.dsx
        # contains no PxOdbc and no PxFilter and neither canonical .ktr contains a
        # TableOutput, which is the whole reason the canonical numbers never showed it.
        promoted_fields: set = set()
        for ir_field, fspec in (dispatch.get("element_fields") or {}).items():
            # `rule` may be a LIST of candidate ids, tried in table order, first
            # non-None hit wins -- Alteryx's FilterConditions needs this because
            # Custom mode states the whole predicate as one child's text
            # (`filter_expression`) while Simple mode states it as three sibling
            # facts assembled by a template (`filter_simple_predicate`); a single
            # id cannot name both readings of the same IR field.
            rule_ids = fspec["rule"] if isinstance(fspec["rule"], list) else [fspec["rule"]]
            hit = None
            fired_rule_id = None
            for rid in rule_ids:
                hit = self.resolve_fact(el, rid)
                if hit is not None:
                    fired_rule_id = rid
                    break
            if hit is None:
                if fspec.get("required"):
                    payload_missing.append(f"{ir_field} (rule {fspec['rule']})")
                continue
            _key, where, value = hit
            # FRAMEWORK CHANGE 60 (e): an optional table-declared normalisation.
            #
            # SSIS states a destination as `[dbo].[CUSTOMER_SUMMARY]` -- a QUALIFIED,
            # bracket-quoted name. Passing that straight through produced
            # `{{ config(alias='[dbo].[CUSTOMER_SUMMARY]') }}`, where real SnowConvert
            # emits `alias='CUSTOMER_SUMMARY'`. Brackets are not legal in an unquoted
            # Snowflake identifier, so the raw value is not merely ugly, it is wrong --
            # the same class as the Pentaho model-name finding, reached by another route.
            #
            # The transform is declared PER RULE in the table rather than inferred here,
            # because "which part of a qualified name is the table" is a platform fact.
            # Deliberately NOT trying to also populate SchemaName: `dbo` is a SQL Server
            # schema, and asserting it as the Snowflake target schema would state a
            # destination the migration has not actually decided. Dropping it leaves
            # TargetTranslatorBase's documented fallback in charge, which is honest.
            xf = fspec.get("transform")
            if isinstance(xf, dict):
                # A transform declared PER CANDIDATE RULE, not per field --
                # `filter_expression` states raw Alteryx expression syntax and
                # needs NORMALIZE_EXPRESSION_SYNTAX; `filter_simple_predicate`
                # already assembles final SQL and must not be re-lexed (its own
                # quoting would be misread as an Alteryx `[ref]`/`"literal"` pair
                # and mangled). A rule id absent from the map gets no transform.
                xf = xf.get(fired_rule_id)
            if xf == "UNQUALIFIED_TAIL":
                raw = value
                value = value.split(".")[-1].strip("[]`\"")
                if value != raw:
                    where += f"  [transform UNQUALIFIED_TAIL from {raw!r}]"
                    self.transformed_reads.append((ir_field, raw, value))
            elif xf == "NORMALIZE_EXPRESSION_SYNTAX":
                # I-19/SNOW-3936576: whole PREDICATE rewrite via _normalize_expression_syntax.
                raw = value
                value = self._normalize_expression_syntax(value)
                if value != raw:
                    where += f"  [transform NORMALIZE_EXPRESSION_SYNTAX from {raw!r}]"
                    self.transformed_reads.append((ir_field, raw, value))
            elif xf is not None:
                raise ValueError(f"element_fields transform '{xf}' is not implemented")
            payload[ir_field] = value
            # PARTIAL PROMOTIONS ARE NOT SUPPRESSED, and this exception is not a
            # special case so much as the definition of the rule kind. A HARVEST rule
            # with a `harvest_key` promotes ONE NAMED PART of a tuple while the census
            # branch reports the WHOLE tuple -- Informatica's
            # `source_table_qualification` promotes {table} into
            # SourceQualifier.TableName and its census detail says `mydb.dbo
            # qualification has no IR field`, which is a TRUE unmet obligation about
            # the database and schema that still have none. MEASURED: suppressing it
            # took MappingForTest.XML from 186/220 to 186/219 and SQ_EMPLOYEE from
            # 93.8% to 96.8% while nothing new had been read -- a fit rise bought by
            # deleting a real cost, which is the exact move this project forbids.
            rule = self.rule_by_id(fired_rule_id) or {}
            if not (rule.get("from") == "HARVEST" and rule.get("harvest_key")):
                promoted_fields.add(fired_rule_id)
            self.slots.append(Slot(name, f"element.{ir_field}", SOURCE, where, value))

        if ir_kind is not None and payload_missing:
            # FRAMEWORK CHANGE 61 (b): ESCALATE TO THE MODEL BEFORE DEGRADING.
            #
            # The previous rule went straight from "required payload missing" to
            # "degrade", which was half right. Emitting a hollow FilterTransformation is
            # genuinely unsafe -- an empty predicate becomes WHERE TRUE and silently
            # returns every row. But degrading is not the only alternative, and treating
            # it as such is what made "nothing" the normal output. A predicate no rule
            # kind can scrape is exactly the kind of thing a model CAN read.
            #
            # So the order is: deterministic rule -> model -> degrade. Degradation is now
            # the third answer rather than the second.
            supplied = self.ai_for(el)
            still_missing = []
            for entry in payload_missing:
                field = entry.split(" ")[0]
                if field in supplied and not field.startswith("_"):
                    payload[field] = supplied[field]
                    self.slots.append(Slot(
                        name, f"element.{field}", MODEL, f"sidecar:{field}",
                        f"{supplied[field]!r} -- no deterministic rule could read this; "
                        f"authored by a model, NOT read from the document"))
                else:
                    still_missing.append(entry)
            payload_missing = still_missing

        if ir_kind is not None and payload_missing:
            # Record the refusal as its own obligation so the fit number reflects that
            # a representable kind was DECLINED, not that the element was never seen.
            self.slots.append(Slot(
                name, "element.$kind", MISSING, "element_fields",
                f"'{el.kind_raw}' maps to {ir_kind}, but required payload did not "
                f"resolve deterministically OR from the model sidecar: "
                f"{', '.join(payload_missing)}. Degrading rather than emitting "
                f"a semantically hollow {ir_kind} -- an empty filter predicate becomes "
                f"WHERE TRUE downstream, which silently returns every row."))
            ir_kind = None
            payload = {}
            # The payload is DISCARDED here, so nothing was promoted after all and the
            # census must report every one of these facts again. Clearing this is the
            # difference between "the IR carries it" and "the IR was going to".
            promoted_fields.clear()

        # FRAMEWORK CHANGE 61 (c): THE MODEL MAY SUPPLY A KIND THE TABLE HAS NONE FOR.
        #
        # This is the case that produced literal zeros: Pentaho's Janino step and
        # DataStage's Transformer hold expressions in Java and DataStage BASIC, which no
        # engine translator lowers, so the table deliberately left them unmapped rather
        # than emit Java into a .sql file. Correct as far as it went -- and it left the
        # derive step of every such pipeline as a placeholder.
        #
        # A model CAN lower those. If it has, it says so here by naming the IR kind, and
        # the element rejoins the graph as a first-class node. The table's refusal stands
        # as the DEFAULT; the sidecar is what overrides it, per element, on the record.
        if ir_kind is None:
            supplied = self.ai_for(el)
            if supplied.get("$kind"):
                # FRAMEWORK CHANGE 66: refuse a kind the hydrator would throw on, and
                # DEGRADE this element instead of losing the document. See
                # HYDRATOR_KIND_CONTRACT for why the blast radius makes this worth a
                # guard rather than an exception at hydration time.
                _claimed = supplied["$kind"]
                if _claimed not in HYDRATOR_KIND_CONTRACT:
                    self.slots.append(Slot(
                        name, "element.$kind", MISSING, "sidecar:$kind",
                        f"a model asserts '{_claimed}', which the hydrator's kind switch "
                        f"has no arm for, so promoting it would throw during hydration and "
                        f"lose the WHOLE document. Refused; this element degrades. Accepted "
                        f"kinds: {', '.join(sorted(HYDRATOR_KIND_CONTRACT))}"))
                else:
                    _absent = [f for f in HYDRATOR_KIND_CONTRACT[_claimed]
                               if not str(supplied.get(f) or "").strip()]
                    if _absent:
                        # The required-payload rule, on the sidecar path. A hollow
                        # FilterTransformation is the worse outcome even than degrading:
                        # `FilterTranslator` substitutes `WHERE TRUE` for an empty
                        # predicate and silently returns every row.
                        self.slots.append(Slot(
                            name, "element.$kind", MISSING, "sidecar:$kind",
                            f"a model asserts '{_claimed}' but supplies no "
                            f"{', '.join(_absent)}, which the hydrator reads with "
                            f"RequiredString; promoting it would throw and lose the WHOLE "
                            f"document. Refused; this element degrades."))
                    else:
                        ir_kind = _claimed
                if ir_kind is not None:
                    for _f, _v in supplied.items():
                        # `_`-prefixed keys are the sidecar's own documentation -- source
                        # expression, reasoning, flagged divergences. They are for a human
                        # reviewer, not IR fields, and promoting them put
                        # `_source_dialect` into an element the hydrator then had to ignore.
                        if _f.startswith("_") or _f in ("$kind", "OutputColumns", "ModelSql"):
                            continue
                        payload[_f] = _v
                        self.slots.append(Slot(name, f"element.{_f}", MODEL,
                                               f"sidecar:{_f}", str(_v)))
                    self.slots.append(Slot(
                        name, "element.$kind", MODEL, "sidecar:$kind",
                        f"'{el.kind_raw}' has no table ir_kind; a model asserts {ir_kind}. "
                        f"MODEL provenance, not TABLE -- the platform table still refuses "
                        f"this kind and that refusal is the default."))

        # FRAMEWORK CHANGE 44: node.id was always a single attribute reading. Under
        # key scoping it is COMPOSED from two readings -- the enclosing job's key
        # and the record's own -- by a named rule, so citing only the record's
        # attribute would understate it.
        ks = self.idn.struct.get("key_scope")
        if ks:
            self.slots.append(Slot(
                name, "node.id", DERIVED,
                el.where + self.idn.attr_ref(self.idn.node_of(el), key_attr),
                f"key_scope: @{ks['key_attr']} of the enclosing {ks['tag']} "
                f"+ '{ks['separator']}' + @{key_attr}"))
        else:
            self.slots.append(Slot(name, "node.id", SOURCE,
                                   el.where + self.idn.attr_ref(
                                       self.idn.node_of(el), key_attr)))
        # FRAMEWORK CHANGE 34 (call site) and FRAMEWORK CHANGE 41: the role is no
        # longer always an attribute. When it is DERIVED, the VALUE of node.type
        # and of element.$kind is decided by an algorithm over identified
        # structure and the table supplies only the mapping -- so recording them
        # as TABLE would credit the table with a reading it did not make. Both
        # DERIVED and TABLE count as satisfied, so the fit number is unchanged;
        # what changes is the provenance breakdown, which is the integrity
        # measure when there is no golden output to check against.
        role_derived = el.role_source.startswith("DERIVED")
        role_prov = DERIVED if role_derived else TABLE
        # FRAMEWORK CHANGE 51: `role_to_node_type[el.role]` was indexed directly, so
        # a role the table does not map did not degrade -- it CRASHED the emitter.
        # EXECUTED: InfPc/Registry/MappletPart/mapplet_part.xml raises
        # `KeyError: 'MAPPLET'` here, and MAPPLET is an ordinary Informatica
        # INSTANCE/@TYPE. The cost is not one bad node, it is the whole document:
        # the other 11 elements never get emitted either, and the run produces no
        # IR and no fit number at all, so the gap is invisible rather than small.
        #
        # An unhandled ROLE now behaves the way an unhandled KIND already does --
        # emit a table-declared placeholder, record the obligation as MISSING so it
        # earns no fit credit, and name the role that could not be mapped. The
        # placeholder is `unmapped_role_node_type` in the table because choosing it
        # is policy; it is deliberately NOT 'transformation', which would assert a
        # role the producer failed to determine.
        node_type, role_prov, role_detail = self.node_type_of(el, role_prov)
        self.slots.append(Slot(name, "node.type", role_prov, "role_to_node_type",
                               role_detail
                               + (f"  [role via {el.role_source}]" if role_derived else "")))
        self.slots.append(Slot(name, "node.modelName", TABLE,
                               self.table["naming_policy"]["policy_id"]))
        # FRAMEWORK CHANGE 43 (a pre-existing provenance defect, found on
        # DataStage and present on SSIS too): this cited el.where + "/@" +
        # key_attr, the KEY attribute, even though element.Name is emitted from
        # the DISPLAY attribute whenever naming_policy says so. On SSIS it cited
        # @refId for a value read from @name; on DataStage it cited @Identifier
        # for a value read from @Name. The count was right and the citation was
        # wrong, which is the failure mode provenance exists to prevent.
        name_attr = (el.display_name_attr
                     if self.table["naming_policy"].get("element_name_from")
                     == "DISPLAY_NAME" else key_attr)
        self.slots.append(Slot(name, "element.Name", SOURCE,
                               el.where + self.idn.attr_ref(
                                   self.idn.node_of(el), name_attr)))

        node = {
            "id": name,
            "type": node_type,
            "modelName": self.model_name(el),
            "element": {},
        }

        # FRAMEWORK CHANGE 49: a null ir_kind used to END the node here -- the node
        # was emitted as `$kind: null` with no columns, and the hydrator then kept
        # it OUT of the data-flow graph and dropped EVERY EDGE touching it. Measured
        # across five platforms that cost DataStage 19 of 19 edges: 43 nodes, 19
        # dependencies, zero surviving lineage.
        #
        # `degrade_to` names an engine Transformation class that keeps the node IN
        # the graph while still declaring the element's own kind unrepresented. Two
        # invariants make that honest rather than a number-raising trick:
        #   1. element.$kind stays MISSING, so fit.score's census gate still returns
        #      NotSupported for the element and the degradation earns no fit credit.
        #   2. `_unsupported` still carries the native kind, so the consumer can name
        #      what it could not translate.
        # No degrade_to: containers stay `$kind: null` (no model). A refused
        # data-flow kind becomes UnsupportedTransformation so a placeholder
        # model exists for tier-3 fill; the $kind obligation stays MISSING.
        degraded_from = None
        if ir_kind is None:
            degrade = dispatch.get("degrade_to")
            if not degrade and not self.is_orchestration_container(el):
                degrade = PLACEHOLDER_KIND
            self.slots.append(Slot(name, "element.$kind", MISSING, "kind_dispatch",
                                   f"'{el.kind_raw}' has no ir_kind; hydrator accepts only "
                                   "SourceQualifier and ExpressionTransformation"
                                   + (f"; degraded to {degrade} so the node and its edges "
                                      f"survive hydration -- census stays NotSupported"
                                      if degrade else "")))
            if degrade is None:
                node["element"] = {"$kind": None, "Name": self.ir_element_name(el),
                                   "_unsupported": el.kind_raw}
                # FRAMEWORK CHANGE 59 (b): containment is promoted even here. An
                # element whose KIND is unrepresentable can still state which
                # container owns it, and that is where ENG-001 was found -- on the
                # 31 non-job DataStage elements, none of which is a supported kind.
                self.record_no_slot_facts(
                    el, frozenset(self.promote_containment(node, name, el)))
                return node

            ir_kind, degraded_from = degrade, el.kind_raw

        if degraded_from is None:
            self.slots.append(Slot(name, "element.$kind",
                                   DERIVED if role_derived and dispatch.get("ir_kind_by_role")
                                   else TABLE, "kind_dispatch",
                                   f"'{el.kind_raw}' -> {ir_kind}"
                                   + (f"  [via role {el.role}, {el.role_source}]"
                                      if role_derived and dispatch.get("ir_kind_by_role")
                                      else "")))

        rename = self.idn.rename_map(name)
        ci = self.syn.get("case_insensitive_resolution", True)
        by_lower = {(p.name.lower() if ci else p.name): p for p in el.ports}
        connected_in = {fe.to_field for fe in self.idn.inbound(name)}

        inputs = self.input_columns(name, el, by_lower)

        outputs = []
        oi = 0
        for p in el.ports:
            if not self.is_output(p):
                continue
            if self.is_local(p) and self.pol["drop_local_variables_from_outputs"]:
                continue
            if self.excluded_group(el, p):
                continue
            # FRAMEWORK CHANGE 25: `if p.ref_field is not None` hardcoded the
            # Informatica Router's REF_FIELD passthrough into the emitter.
            if p.ref_field is not None and \
                    self.pol.get("ref_field_passthrough_rule") == "REF_FIELD_IS_UPSTREAM_NAME":
                text, residue, rules = p.ref_field, [], ["ref_field_passthrough"]
            else:
                text, residue, rules = self.resolve(el, p, rename, by_lower, connected_in)
            passthrough = text == p.name
            expr = None if passthrough else text
            outputs.append(self.column_json(p, p.name, expr))
            if expr is None:
                self.record_column_slots(name, f"element.OutputColumns[{oi}]", p, None)
            else:
                if residue:
                    prov = (RESIDUE, p.where + p.expr_where_suffix,
                            "; ".join(sorted(set(residue))))
                elif rules:
                    prov = (TABLE, p.where + p.expr_where_suffix,
                            "; ".join(sorted(set(rules))))
                else:
                    prov = (DERIVED, p.where + p.expr_where_suffix,
                            "port-reference resolution over the connector graph")
                self.record_column_slots(name, f"element.OutputColumns[{oi}]", p, prov)
            oi += 1

        node["element"] = {
            "$kind": ir_kind,
            "Name": self.ir_element_name(el),
            "InputColumns": inputs,
            "OutputColumns": outputs,
        }

        # FRAMEWORK CHANGE 61 (d): MODEL-AUTHORED COLUMN EXPRESSIONS.
        #
        # The last piece of tier 2, and the one that decides whether a derive step becomes
        # a real model or a placeholder. Port resolution can find that a step HAS output
        # fields; it cannot lower `BirthDate.getYear() + 1900` (Java) or `a : b : c`
        # (DataStage BASIC) into Snowflake, because no engine translator handles those
        # dialects. Without this the node is present and projects nothing.
        #
        # Expressions here are expected ALREADY IN SNOWFLAKE DIALECT. That works because
        # the value migrator on this path is a pass-through -- the same behaviour that let
        # Informatica's GET_DATE_PART reach the artifact verbatim, which was a defect
        # there and is the mechanism here. It does mean the model owns correctness of the
        # SQL it writes, with no second opinion from the engine's expression translators.
        # That is the trade tier 2 makes, and it is why these carry MODEL provenance.
        supplied_cols = self.ai_for(el).get("OutputColumns")
        if ir_kind is not None and supplied_cols:
            by_name = {c["Name"].lower(): c for c in node["element"]["OutputColumns"]}
            for i, sc in enumerate(supplied_cols):
                col = {"Name": sc["Name"]}
                if sc.get("Expression"):
                    col["$kind"] = "ColumnExpression"
                    col["Expression"] = sc["Expression"]
                for k in ("DataType", "Precision", "Scale"):
                    if sc.get(k) is not None:
                        col[k] = sc[k]
                by_name[sc["Name"].lower()] = col
                self.slots.append(Slot(
                    name, f"element.OutputColumns[{i}]", MODEL, "sidecar:OutputColumns",
                    f"{sc['Name']} = {sc.get('Expression', '<passthrough>')!r} -- lowered to "
                    f"Snowflake by a model; the source dialect has no engine translator"))
            node["element"]["OutputColumns"] = list(by_name.values())

        # FRAMEWORK CHANGE 60 (d): A TARGET'S PROJECTION IS WHAT IT RECEIVES.
        #
        # Measured defect this fixes: with TargetTransformation newly reachable, every
        # mart model came out as `SELECT` followed by `FROM source_data AS sd` -- no
        # columns, unrunnable SQL, on all four platforms. Cause is not the translator.
        # TargetTranslator projects OutputColumns, and a target's OutputColumns were
        # empty because a destination has no OUTBOUND edge, so port resolution -- which
        # walks the connector graph forward -- had nothing to resolve.
        #
        # A write stage genuinely has no outputs in the source document. But it does
        # have a projection: the columns it writes are the columns it receives. Mirroring
        # inputs is therefore a derivation, not an invention, and it is recorded as
        # DERIVED rather than SOURCE so provenance does not credit the document with
        # stating something it never stated.
        #
        # Guarded three ways so it cannot quietly paper over a real gap: only for a
        # TARGET role, only when outputs are genuinely empty, and only when inputs are
        # not -- a target with no inputs either keeps its existing MISSING obligation.
        if (ir_kind is not None and el.role == "TARGET"
                and not outputs and inputs):
            node["element"]["OutputColumns"] = [dict(c) for c in inputs]
            self.slots.append(Slot(
                name, "element.OutputColumns", DERIVED, "target_projection_mirrors_input",
                f"a write stage declares no outbound port, so its projection is derived "
                f"from its {len(inputs)} inbound column(s); without this every mart model "
                f"emits a column-less SELECT"))
        # FRAMEWORK CHANGE 60 (b): the table-declared scalar payload. Merged after the
        # base fields and never over them -- a rule that tried to supply $kind or Name
        # would be a table bug, and silently letting it win would hide that.
        for _f, _v in payload.items():
            if _f in node["element"]:
                raise ValueError(
                    f"element_fields rule for '{el.kind_raw}' tries to overwrite "
                    f"reserved IR field '{_f}'")
            node["element"][_f] = _v
        # FRAMEWORK CHANGE 49 (b): a degraded node still names its native kind, so a
        # consumer can report WHAT it failed to translate rather than only that it
        # failed. UnsupportedTransformation.OriginalTransformationText is exactly the
        # field this feeds.
        #
        # FRAMEWORK CHANGE 63 (b): and `_unsupported_body` carries the element's own
        # SOURCE FRAGMENT beside it. `_unsupported` keeps its meaning unchanged -- the
        # native kind NAME -- deliberately: the hydrator reads it for
        # UnsupportedIrNode.NativeKind on the `$kind: null` path too, and the marker
        # line naming WHAT failed is the one thing the current placeholder does get
        # right. The body is an ADDITION beside it, not a redefinition of it.
        if degraded_from is not None:
            node["element"]["_unsupported"] = degraded_from
            body = self.unsupported_body(el)
            if body is not None:
                node["element"]["_unsupported_body"] = body
                attach_source_sql(node["element"], body)

        # FRAMEWORK CHANGE 59 (ENG-014 spike): EXTERNAL I/O AS TWO ORTHOGONAL FACTS.
        #
        # A table entry may declare `external_io` -- "Reads", "Writes", or
        # "Reads|Writes" -- alongside a real `ir_kind`. That is the widened
        # classification: the kind axis still decides the model name, and reads/writes
        # is a separate axis. An ADF Copy activity is the case the old binary could
        # not carry: classified as a source its write is unrepresented, classified as
        # a transformation its read has no external origin.
        #
        # `external_io_slots` names, per side, which no_slot_facts ids the widened
        # classification can now HOLD. Each promoted fact becomes a SOURCE-provenance
        # obligation citing the same document location it cited as NO_SLOT, and is
        # suppressed from the NO_SLOT pass so nothing is counted twice.
        #
        # The promotion is deliberately NARROW. Only facts that are genuinely part of
        # a read spec or a write spec are promoted. The store settings
        # (AzureBlobFSReadSettings / AzureBlobFSWriteSettings) name a CONNECTION and
        # stay NO_SLOT -- that is ENG-002, a different ticket -- and the activity
        # policy timeouts stay NO_SLOT because they are execution policy, ENG-012.
        # Promoting those would credit this ticket with closing gaps it does not close.
        promoted = set()
        promoted |= promoted_fields
        external_io = dispatch.get("external_io")
        if external_io is not None:
            node["element"]["ExternalIo"] = external_io
            self.slots.append(Slot(
                name, "element.ExternalIo", TABLE, "kind_dispatch",
                f"'{el.kind_raw}' reads/writes externally: {external_io}"))

            for side, fields in (dispatch.get("external_io_slots") or {}).items():
                spec = {}
                for ir_field, rule_id in fields.items():
                    hit = self.resolve_fact(el, rule_id)
                    if hit is None:
                        # The rule did not fire. Suppressing it anyway is correct:
                        # there is no fact here to represent, so there is no
                        # obligation either way.
                        promoted.add(rule_id)
                        continue
                    _key, where, value = hit
                    spec[ir_field] = value
                    self.slots.append(Slot(name, f"element.{side}.{ir_field}",
                                           SOURCE, where, value))
                    promoted.add(rule_id)
                if spec:
                    node["element"][side] = spec

        # FRAMEWORK CHANGE 59 (b) (ENG-001 spike): CONTAINMENT AS MODELLED DATA.
        #
        # `containment_slots` names no_slot_facts ids whose fact IS a containment
        # relationship, and which a `node.container` field can now hold. Same
        # promotion rule: SOURCE provenance, same citation, suppressed from NO_SLOT.
        promoted |= self.promote_containment(node, name, el)

        # FRAMEWORK CHANGE 37: a supported element that projects NO columns used to
        # create no column obligations at all, so it scored 100% for having nothing
        # to fail at. That is a defect in the metric, not a property of the source:
        # 28 of the 29 DataStage stages carry no column metadata, and the
        # CContainerView states this outright (LinkHasMetaDatas "False| " at
        # dsx:725). "There is a link in this direction but no columns on it" is an
        # unmet obligation and must be counted as one.
        #
        # The obligation is conditioned on an EDGE existing in that direction, not
        # on the element being supported. A source with no inbound edge is not
        # missing its InputColumns -- there is nothing upstream for them to come
        # from -- and counting that would have penalised every source on every
        # platform for a fact that is not a gap.
        edges = self.idn.element_edges()
        has_in = any(e["to"] == name for e in edges)
        has_out = any(e["from"] == name for e in edges)
        for ir_field, cols, linked in (("OutputColumns", outputs, has_out),
                                       ("InputColumns", inputs, has_in)):
            if linked and not cols:
                self.slots.append(Slot(
                    name, f"element.{ir_field}", MISSING, el.where,
                    (f"element is in the graph as {ir_kind} (degraded from "
                     f"'{degraded_from}') and has a link in this "
                     if degraded_from is not None
                     else f"element is supported ($kind={ir_kind}) and has a link in this ")
                    + f"direction, but the document projects no {ir_field}"))
        self.record_no_slot_facts(el, frozenset(promoted))
        # FRAMEWORK CHANGE 65 (b): TIER-2 CONTENT WAS SHIPPING UNMARKED.
        #
        # MEASURED on poc/blind-run/runU/pentaho:
        # `int_derive_fullname_and_birthyear.sql` holds
        #   FirstName || ' ' || MiddleName || ' ' || LastName AS FullName,
        #   YEAR(BirthDate) AS BirthYear
        # BOTH authored by a model -- the .ktr states them as Java
        # (`FirstName + " " + MiddleName + " " + LastName`, `BirthDate.getYear() + 1900`) and no
        # engine translator lowers Java. The file carried NO marker, so it read exactly like an
        # expression read from the document and lowered by a translator. Tier 3 is stamped
        # (SSC-AI-AUTHORED); tier 2 was invisible, and stage 4's MODEL-AUTHORED count therefore
        # reported 2 for a tree in which 3 of 4 models hold model-authored content.
        #
        # The distinction already existed HERE -- `MODEL` is its own provenance class precisely
        # so a model's assertion is never mistaken for a reading (CONFIDENCE.yml,
        # `model-provenance-is-a-separate-class`). It was kept in the ledger and thrown away in
        # the artifact, which is the only thing a reviewer reads. This carries it across.
        authored = [s for s in self.slots[_model_mark:] if s.provenance == MODEL]
        if authored:
            node["modelAuthored"] = [
                {"path": s.path, "sidecar": s.where, "detail": s.detail} for s in authored]
        return node
