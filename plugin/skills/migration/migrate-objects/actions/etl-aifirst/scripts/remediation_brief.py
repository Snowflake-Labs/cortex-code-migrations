#!/usr/bin/env python3
"""REMEDIATION BRIEF — index existing Gate B / integrity / AIM artifacts for Stabilization.

WHY THIS EXISTS. findings/61 SS10-11 names the planning gap: AI-First detects and contextualises
(Gate A, emission, integrity, Gate B, the AIM issue framework); who turns that discrete list into a
competent result is a separate, larger question this module does not answer. What it DOES do is stop
that list from being three files nobody correlates: this writes ONE json beside the tree that POINTS AT
the existing artifacts and classifies each outstanding item into a `lane` -- who acts on it next.

THIS IS AN INDEX, NOT A SECOND TRUTH STORE. Every number in `summary` and every citation in an item's
`from` is read back off a file this driver already wrote (integrity.json, gateB-sidecar.json,
Reports/AiFirstIssues/issues.json). Nothing here re-derives a verdict a gate already reached, and
nothing here is a new judgement call -- the `lane` rules below are the crude, structural (no model
call) classification findings/61 SS10 describes, explicitly named "a first implementation" pending
refinement.

THE MERGE RULE (why an item can carry BOTH an integrity and a Gate B citation). findings/61 SS11's
worked example shows a Filter defect where integrity (EDGES/PAYLOAD) and Gate B (a DIVERGENT MD:
obligation) are the SAME underlying bug, seen from two gates. Reporting them as two items would ask
Stabilization to fix the same line twice under two different names. Both gates name the affected
element by a NODE ID -- integrity's `subject` embeds it ("3 -> 5", "5 . FilterConditions"); Gate B's
`model` field embeds it too, because this project's emitter names models after the node ("int_m_5").
So: extract digit tokens from each subject/model, and treat any integrity item and any Gate B row that
share a digit token as ONE finding. This is a heuristic tied to this emitter's naming convention, not a
general contract -- exactly why it stays crude and auditable in one function (`_digit_tokens`) rather
than baked into several.

LANE RULES (crude, per findings/61 SS10, refine later):
  - every integrity OUTSTANDING item is `conversion_emitter`. integrity_gate.py compares the IR
    directly to the dbt tree, so by construction an outstanding item means the IR already held the
    fact and the emitter did not carry it through -- there is no separate "was it in the IR" question
    left open once integrity itself raised the obligation.
  - a Gate B outstanding/divergent row that shares a digit token with an integrity item is folded into
    that item (still `conversion_emitter`) rather than raised twice.
  - a Gate B outstanding/divergent row with NO integrity overlap: `stabilization_repair` when the
    verdict is DIVERGENT/BROKEN (a good-faith convert whose intent still needs fixing); `residual` when
    UNVERIFIABLE/UNANSWERED (nothing was established either way -- Stabilization must not invent an
    intent repair from a verdict that never resolved).
  - an AIM issue instance whose signature `reason` names an unsupported-construct class
    (no-vocabulary-member / degraded-to-catch-all-class / no-lowering-for-source-language) is
    `residual` for the August MVP bar (findings/61 SS11, SS15 item 5); every other AIM instance is
    `stabilization_repair`.

`conversion_ir` and `stabilization_harden` are valid lane values this module never emits: the first is
Gate A's judgement half (a model call, out of this script's scope -- Track C does not touch gate_a.py),
the second is profile-driven hardening with no structural signal here to detect it from. Leaving them
unused is honest; inventing a rule to fill them would not be.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

SCHEMA = "aim.remediation-brief.v1"

LANES = (
    "conversion_emitter",
    "conversion_ir",
    "stabilization_repair",
    "stabilization_harden",
    "residual",
)

# findings/61 SS11: AIM signature `reason` values that name an unsupported construct rather than a
# converted-but-wrong one. Read from issues/signature.py's own REASON_ALIASES canonical targets, not
# re-typed by guess -- if that vocabulary grows, this set drifts out of date loudly (a reason string
# this module has never seen falls through to stabilization_repair, not silently into residual).
UNSUPPORTED_AIM_REASONS = frozenset(
    {
        "no-vocabulary-member",
        "degraded-to-catch-all-class",
        "no-lowering-for-source-language",
    }
)

ALLOWED_ACTIONS = {
    "conversion_emitter": [
        "fix_emitter_ref_resolution",
        "emit_value_from_ir",
        "re_run_migrator",
    ],
    "conversion_ir": ["extend_identification", "add_ir_sidecar", "re_run_identify"],
    "stabilization_repair": ["repair_emitted_sql_under_profile", "re_verify_gate_b"],
    "stabilization_harden": ["apply_platform_hardening_procedure"],
    "residual": ["file_aim_or_eng_ticket"],
}
FORBIDDEN_ACTIONS = [
    "hand_edit_output_tree_outside_mechanisms",
    "invent_source_intent_without_pointer",
]

# Gate B verdicts that leave the obligation OUTSTANDING (mirrors gate_b.py's DISCHARGING complement).
_DIVERGENT_LIKE = {"DIVERGENT", "BROKEN"}
_UNRESOLVED_LIKE = {"UNVERIFIABLE", "UNANSWERED"}


def _load_json_status(path):
    """Best-effort read that also names WHY a source came back empty: 'missing' (no file --
    e.g. Gate B never ran) and 'corrupt' (a file that exists but does not parse) are different
    claims from 'loaded', and collapsing them to a bare None is what let a degraded run's absent
    Gate B sidecar produce the same items_total:0 shape as a clean run with nothing to report."""
    if not path or not os.path.isfile(path):
        return None, "missing"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), "loaded"
    except (OSError, json.JSONDecodeError):
        return None, "corrupt"


def _load_json(path):
    data, _ = _load_json_status(path)
    return data


def _slug(text, n=48):
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return (out or "x")[:n]


def _digit_tokens(text):
    return {t for t in re.split(r"[^A-Za-z0-9]+", str(text)) if t.isdigit()}


def _short_hash(*parts, n=10):
    """A slug alone collides when two long identifiers share the same first N characters (measured:
    two AIM-EMIT instances on sibling files under the same deep Output/ETL/... path truncated to the
    identical `id`). Appending a hash of the untruncated parts keeps ids short AND content-addressed,
    the same property AIM's own `AIM-<category>-<digest>` codes rely on."""
    h = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()[:n]


def integrity_outstanding_entries(integrity):
    """Flatten every class's outstanding_items into one list, each tagged with the digit tokens in
    its `subject` -- the merge key against Gate B rows. `integrity` is integrity_gate.py's own
    `--json` output (see integrity_gate.py Ledger.as_dict); this reads it back, it does not
    reimplement it."""
    entries = []
    for cls in (integrity or {}).get("classes", []) or []:
        cls_name = cls.get("class")
        for it in cls.get("outstanding_items", []) or []:
            subject = it.get("subject", "")
            entries.append(
                {
                    "class": cls_name,
                    "subject": subject,
                    "why": it.get("why", ""),
                    "evidence": it.get("evidence", ""),
                    "tokens": _digit_tokens(subject),
                }
            )
    return entries


def gate_b_outstanding_entries(sidecar):
    """`sidecar` is gateB-sidecar.json (see gate_b.py score()'s `sidecar` dict) -- the SCORED ledger,
    not the raw verifier answer in verdict.json. `unresolved` already carries outstanding obligations
    plus unanswered ones; `divergences` is the subset of those that are DIVERGENT/BROKEN. Only
    `unresolved` is read: every divergence is already inside it, and reading both would double-count."""
    if not sidecar:
        return []
    seen = set()
    entries = []
    for row in sidecar.get("unresolved", []) or []:
        oid = row.get("obligation_id")
        if oid in seen:
            continue
        seen.add(oid)
        model = row.get("model") or ""
        entries.append(
            {
                "obligation_id": oid,
                "family": row.get("family"),
                "verdict": row.get("verdict"),
                "model": model,
                "sql_file": row.get("sql_file"),
                "output_column": row.get("output_column"),
                "source_says": row.get("source_says") or "",
                "sql_says": row.get("sql_says") or "",
                "failing_input": row.get("failing_input") or "",
                "differs_as": row.get("differs_as") or "",
                "reason": row.get("reason") or "",
                "tokens": _digit_tokens(model),
            }
        )
    return entries


def aim_issue_instances(issues):
    """`issues` is Reports/AiFirstIssues/issues.json (issues/stage.py). Returns its `instances` list
    verbatim -- each already carries `code`, `reason`, `element_id`, `element`, `text`, `evidence`."""
    if not issues:
        return []
    return issues.get("instances", []) or []


def _gate_b_item(entry):
    lane = "stabilization_repair" if entry["verdict"] in _DIVERGENT_LIKE else "residual"
    return {
        "id": "RB:gateb-%s-%s" % (_slug(entry["obligation_id"]), _short_hash(entry["obligation_id"])),
        "lane": lane,
        "priority": 2 if lane == "stabilization_repair" else 4,
        "models": [entry["model"]] if entry["model"] else [],
        "element_ids": sorted(entry["tokens"]),
        "from": [
            {
                "kind": "gate_b",
                "obligation_id": entry["obligation_id"],
                "family": entry["family"],
                "verdict": entry["verdict"],
            }
        ],
        "intent_excerpt": {
            "source_says": entry["source_says"],
            "sql_says": entry["sql_says"],
        },
        "allowed_actions": ALLOWED_ACTIONS[lane],
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "reverify": ["gate_b:%s" % entry["obligation_id"]],
    }


def _merged_emitter_item(integrity_entries, gate_b_entries):
    """One conversion_emitter item for a cluster of integrity outstanding entries that share
    digit tokens (findings/61 SS11: EDGES + PAYLOAD on the same node are one bug, not two)."""
    if not isinstance(integrity_entries, list):
        integrity_entries = [integrity_entries]
    models = sorted({e["model"] for e in gate_b_entries if e["model"]})
    tokens = set()
    for ie in integrity_entries:
        tokens |= ie["tokens"]
    for e in gate_b_entries:
        tokens |= e["tokens"]
    element_ids = sorted(tokens)
    frm = []
    reverify = []
    id_parts = []
    for integrity_entry in integrity_entries:
        frm.append(
            {
                "kind": "integrity",
                "class": integrity_entry["class"],
                "subject": integrity_entry["subject"],
                "why": integrity_entry["why"],
            }
        )
        reverify.append("integrity:%s:%s" % (integrity_entry["class"], integrity_entry["subject"]))
        id_parts.extend([integrity_entry["class"], integrity_entry["subject"]])
    intent_excerpt = {}
    for e in gate_b_entries:
        frm.append(
            {
                "kind": "gate_b",
                "obligation_id": e["obligation_id"],
                "family": e["family"],
                "verdict": e["verdict"],
            }
        )
        intent_excerpt = {"source_says": e["source_says"], "sql_says": e["sql_says"]}
        reverify.append("gate_b:%s" % e["obligation_id"])
    label = "-".join(_slug(p) if p else "x" for p in id_parts[:4]) or "x"
    item_id = "RB:integrity-%s-%s" % (label, _short_hash(*id_parts))
    return {
        "id": item_id,
        "lane": "conversion_emitter",
        "priority": 1,
        "models": models,
        "element_ids": element_ids,
        "from": frm,
        "intent_excerpt": intent_excerpt,
        "allowed_actions": ALLOWED_ACTIONS["conversion_emitter"],
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "reverify": reverify,
    }


def _cluster_integrity_entries(entries):
    """Union-find over digit-token overlap so same-node EDGES+PAYLOAD collapse to one cluster."""
    n = len(entries)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if entries[i]["tokens"] and entries[j]["tokens"] and entries[i]["tokens"] & entries[j]["tokens"]:
                union(i, j)
    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(entries[i])
    return list(clusters.values())


def _looks_like_model_path(text):
    """AIM states an element identity in `element_id` for most categories, but an EMIT finding is
    about a generated FILE and carries that file's path there instead. Measured on the Order
    Enrichment workload: 9 of 20 instances carried a path. A path left in an identity field becomes
    a fake element to any consumer that joins `element_ids` against the element inventory, which is
    how a brief full of real findings correlates to nothing."""
    text = str(text)
    return "/" in text or text.endswith(".sql")


def _aim_identity(instance):
    """Splits an AIM instance's two facts apart: which element it is about, and which generated file
    it was found in. Returns `(element_ids, models)`.

    Element ids are bare source ids -- the vocabulary `_digit_tokens` already produces for the
    integrity and Gate B lanes, and the one `ETL.Elements` states as `FullName`. Stating one
    vocabulary across every lane is what lets a consumer join the whole brief with a single key;
    `element` ('m_6') and `FullName` ('6') are the same fact spelled two ways."""
    raw = instance.get("element_id") or ""
    element = instance.get("element") or ""
    if _looks_like_model_path(raw):
        # The path is the finding's location, not its subject: never scrape digit tokens out of
        # it (a folder segment like `job_123` is not the element). `element` names the subject;
        # with no `element` at all, the file stem verbatim is the closest stable identity left.
        ids = _digit_tokens(element)
        if ids:
            return sorted(ids), [str(raw)]
        identity = str(element) or os.path.splitext(os.path.basename(str(raw)))[0]
        return ([identity] if identity else []), [str(raw)]
    ids = _digit_tokens(raw) or _digit_tokens(element)
    if not ids and raw:
        # A platform whose ids are not numeric: keep the identity verbatim rather than drop it.
        ids = {str(raw)}
    return sorted(ids), []


def _aim_item(instance):
    reason = instance.get("reason", "")
    lane = "residual" if reason in UNSUPPORTED_AIM_REASONS else "stabilization_repair"
    element_ids, models = _aim_identity(instance)
    code = instance.get("code", "")
    # The slug reads as the element; the hash still covers the RAW field, so two EMIT findings on
    # sibling files under one element stay distinct ids.
    raw = instance.get("element_id") or instance.get("element") or ""
    identity = element_ids[0] if element_ids else str(raw)
    return {
        "id": "RB:aim-%s-%s-%s" % (_slug(code), _slug(identity), _short_hash(code, raw)),
        "lane": lane,
        "priority": 4 if lane == "residual" else 2,
        "models": models,
        "element_ids": element_ids,
        "from": [
            {
                "kind": "aim",
                "code": instance.get("code"),
                "category": instance.get("category"),
                "reason": reason,
            }
        ],
        "intent_excerpt": {"sql_says": instance.get("text", "")},
        "allowed_actions": ALLOWED_ACTIONS[lane],
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "reverify": ["aim:%s:%s" % (instance.get("code"), identity)],
    }


def build_items(integrity, gate_b_sidecar, aim_issues):
    """Pure function of three already-loaded artifact dicts (or None) -- takes no paths, so tests can
    hand it canned fixture ledgers directly without touching disk."""
    integrity_entries = integrity_outstanding_entries(integrity)
    gate_b_entries = gate_b_outstanding_entries(gate_b_sidecar)

    used_gb_idx = set()
    items = []
    for cluster in _cluster_integrity_entries(integrity_entries):
        cluster_tokens = set()
        for ie in cluster:
            cluster_tokens |= ie["tokens"]
        matches = [
            (idx, e)
            for idx, e in enumerate(gate_b_entries)
            if idx not in used_gb_idx and cluster_tokens and e["tokens"] and cluster_tokens & e["tokens"]
        ]
        for idx, _ in matches:
            used_gb_idx.add(idx)
        items.append(_merged_emitter_item(cluster, [e for _, e in matches]))

    for idx, entry in enumerate(gate_b_entries):
        if idx in used_gb_idx:
            continue
        items.append(_gate_b_item(entry))

    for instance in aim_issue_instances(aim_issues):
        items.append(_aim_item(instance))

    return items


def build_summary(integrity, gate_b_sidecar, aim_issues):
    summary = {}
    if gate_b_sidecar and gate_b_sidecar.get("ledger"):
        summary["gate_b"] = gate_b_sidecar["ledger"]
    if integrity is not None:
        summary["integrity_outstanding"] = integrity.get("outstanding", 0)
    if aim_issues is not None:
        summary["aim_instances"] = len(aim_issues.get("instances", []) or [])
    return summary


def build_brief(
    platform,
    document,
    pointers,
    integrity=None,
    gate_b_sidecar=None,
    aim_issues=None,
    conversion_exit=None,
    source_status=None,
):
    """The one function that assembles the whole document. `pointers` is a dict of path strings the
    caller already resolved -- this function never guesses a path itself, so a test can feed it
    arbitrary strings without a real tree on disk.

    `source_status` (optional) is the {"integrity"|"gate_b_sidecar"|"aim_issues": "loaded"|"missing"|
    "corrupt"} map `_load_json_status` produced for each artifact. A degraded run (`conversion_exit`
    truthy) where one of those three is not `loaded` is `incomplete`: build_items() cannot tell "this
    source had nothing to report" from "this source could not be read", so both would otherwise reach
    the exact same items_total:0 shape as a genuinely clean run."""
    items = build_items(integrity, gate_b_sidecar, aim_issues)
    lane_counts = {}
    for it in items:
        lane_counts[it["lane"]] = lane_counts.get(it["lane"], 0) + 1
    status = dict(source_status or {})
    status.setdefault("integrity", "loaded" if integrity is not None else "missing")
    status.setdefault("gate_b_sidecar", "loaded" if gate_b_sidecar is not None else "missing")
    status.setdefault("aim_issues", "loaded" if aim_issues is not None else "missing")
    incomplete = bool(conversion_exit) and any(v != "loaded" for v in status.values())
    return {
        "schema": SCHEMA,
        "platform": platform,
        "document": document,
        "conversion_exit": conversion_exit,
        "pointers": pointers,
        "sources": status,
        "incomplete": incomplete,
        "summary": {
            **build_summary(integrity, gate_b_sidecar, aim_issues),
            "items_by_lane": lane_counts,
            "items_total": len(items),
        },
        "items": items,
    }


# ==================================================================================================
# CLI -- resolves the on-disk conventions this driver already uses and writes the brief beside the
# tree. Everything above this line is pure and independently testable.
# ==================================================================================================

def _resolve_paths(table_path, output_root, bundle_dir):
    platform = re.sub(r"^platform_", "", os.path.splitext(os.path.basename(table_path))[0])
    gate_b_dir = os.path.join(bundle_dir, "gateB")
    integrity_dir = os.path.join(bundle_dir, "integrity")
    aim_dir = os.path.join(output_root, "Reports", "AiFirstIssues")
    return {
        "platform": platform,
        "gate_b_verdict": os.path.join(gate_b_dir, "verdict.json"),
        "gate_b_obligations": os.path.join(gate_b_dir, "obligations.json"),
        "gate_b_sidecar": os.path.join(gate_b_dir, "gateB-sidecar.json"),
        "integrity": os.path.join(integrity_dir, "integrity.json"),
        "ir": os.path.join(integrity_dir, "ir.json"),
        "aim_issues": os.path.join(aim_dir, "issues.json"),
        "output_root": output_root,
    }


def main(argv):
    ap = argparse.ArgumentParser(
        prog="remediation_brief.py",
        description="Index Gate B / integrity / AIM artifacts into a stabilization handoff brief.",
    )
    ap.add_argument("table", help="platform table json (e.g. platform_alteryx.json)")
    ap.add_argument("document", help="source document that was migrated")
    ap.add_argument("output_root", help="the migration's $OUT directory")
    ap.add_argument("--bundle-dir", required=True, help="the driver's $GATE_BUNDLES directory")
    ap.add_argument("--conversion-exit", type=int, default=None)
    ap.add_argument("--out", default=None, help="override the brief's own output path")
    args = ap.parse_args(argv)

    resolved = _resolve_paths(args.table, args.output_root, args.bundle_dir)
    pointers = dict(resolved)
    platform = pointers.pop("platform")
    pointers["source_document"] = os.path.abspath(args.document)

    integrity, integrity_status = _load_json_status(resolved["integrity"])
    gate_b_sidecar, gate_b_status = _load_json_status(resolved["gate_b_sidecar"])
    aim_issues, aim_status = _load_json_status(resolved["aim_issues"])
    source_status = {
        "integrity": integrity_status,
        "gate_b_sidecar": gate_b_status,
        "aim_issues": aim_status,
    }

    brief = build_brief(
        platform=platform,
        document=os.path.basename(args.document),
        pointers=pointers,
        integrity=integrity,
        gate_b_sidecar=gate_b_sidecar,
        aim_issues=aim_issues,
        conversion_exit=args.conversion_exit,
        source_status=source_status,
    )
    brief["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out_path = args.out or os.path.join(
        args.output_root, "Reports", "AiFirstRemediation", "remediation-brief.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(brief, fh, indent=1, sort_keys=False)

    if brief["incomplete"]:
        # Distinct stdout shape from the success line below: a degraded run whose own inputs are
        # missing/corrupt must not read like a clean run that simply found nothing (items_total:0
        # either way) -- the driver greps for this line to tell the two apart.
        unresolved = sorted(k for k, v in source_status.items() if v != "loaded")
        print(" BRIEF INCOMPLETE  : degraded run, source(s) not loaded: %s" % ", ".join(unresolved))
    print(
        " remediation brief : %d item(s) across %d lane(s) written to %s"
        % (brief["summary"]["items_total"], len(brief["summary"]["items_by_lane"]), out_path)
    )
    for lane, n in sorted(brief["summary"]["items_by_lane"].items()):
        print("   %-22s: %d" % (lane, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
