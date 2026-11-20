# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load and render versioned migration effort-estimate artifacts."""

from __future__ import annotations

import html
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from snowconvert_reports.issue_docs import ISSUE_DOCUMENTATION_URL_JS

_HOURS_PER_WORK_DAY = 8.0

_OVERRIDES_INFO_ICON = (
    '<span class="info-icon" style="margin-left:4px;">i<span class="tooltip">'
    "An override is one rate you have changed. Snowflake's own figure is kept alongside it, "
    "so every total can be compared against the unedited estimate — and a single override "
    "can be cleared by emptying its cell."
    "</span></span>"
)

# What the effort estimate's object count covers. Overview's Total Objects counts
# every object the waves analysis saw, so the two numbers differ; this names the gap.
PRICED_OBJECTS_HINT = (
    "Priced objects are the in-scope objects found in the source that the effort "
    "estimate counts. The total object count on the Overview also includes missing "
    "references, out-of-scope objects, indexes, workflows and scripts with no rate "
    "card, which the estimate leaves out. Units registered but not yet converted get "
    "no hours until they are converted."
)

# Sub-line under Priced Objects. ``pending_count`` is absent on artifacts written
# before it existed, which shows no line.
_PENDING_SUBLINE_HTML = (
    '<div v-if="effortSummary.pending_count > 0" class="effort-sf-note">'
    "{{ effortCount(effortSummary.pending_count) }} not converted yet \u2014 not estimated"
    "</div>"
)

_PRICED_OBJECTS_INFO_ICON = (
    '<span class="info-icon" style="margin-left:4px;">i<span class="tooltip">'
    f"{html.escape(PRICED_OBJECTS_HINT)}"
    "</span></span>"
)

# Shared by the calculator Grouping header and the EWI-breakdown Grouping header.
GROUPING_COLUMN_TIP = (
    "The first object with a given EWI is charged the full rate for its complexity. "
    "Each additional object with that EWI is grouped and charged 0.25× that rate. "
    "Some EWIs are not grouped."
)

EFFORT_DISCLAIMER_HTML = (
    '<p style="color: #0369A1; background: #F0F9FF; border: 1px solid #BAE6FD; '
    'border-radius: 8px; padding: 12px 14px; font-size: 0.88rem; line-height: 1.5; '
    'margin-bottom: 20px;">'
    "<strong>Disclaimer:</strong> These estimates are a best-effort recommendation only. "
    "Actual effort may vary based on project scope, team experience, data quality, "
    "and migration complexity."
    "</p>"
)
_DDL_EXCLUDED_DISPLAY_TYPES = frozenset({"Index", "Flow Control"})

# Rendered wherever an hour figure is absent because the work has no estimation
# approach yet, matching the fixed-budget tooltip's own N/A cells.
_NOT_APPLICABLE = "N/A"

# Complexity bands, worst first — the order the .NET calculator, the FDE workbook
# and this report all list them in. ``Redesign`` carries a rate but no objects
# are classified into it, so only the first four are shown and edited.
_BANDS = ("critical", "high", "medium", "low")
_BAND_LABELS = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}


@dataclass
class CalculatorRow:
    """One calculator line item, mirroring the .NET record it is rehydrated from.

    ``pricing`` says which fields are live. A *banded* row prices counted objects
    and carries ``band_counts`` plus ``band_rates``. A *flat* row is one budget
    for the whole line. A *flat_total* row shows the object count and charges
    ``flat_hours`` once. A *per_object* row charges ``unit_hours`` times the count.
    """

    # Stable config key, unique per row: how an override addresses a row without
    # matching a display label. ``bucket`` is the roll-up class and ``ddl_type``
    # the DDL summary entry the row prices, or None when it prices no single type.
    key: str
    bucket: str
    ddl_type: Optional[str]
    component: str
    object_type: str
    quantity: Any
    # ``None`` on a flat row; a mapping of band name to objects / hours otherwise.
    band_counts: Optional[Dict[str, Any]]
    band_rates: Optional[Dict[str, float]]
    # ``None`` on a banded row, and on a flat row Snowflake publishes no figure
    # for. The latter renders as N/A and contributes nothing to the totals until
    # the user enters their own budget, which they may: declining to price a line
    # is a statement about our estimate, not a restriction on theirs.
    flat_hours: Optional[float]
    estimated_hours: Optional[float]
    manual_rewrite_hours: Optional[float]
    automation_pct: Optional[float]
    comments: str = ""
    # Absent on artifacts written before these shapes existed. Missing means banded
    # when band counts are present and flat otherwise; the shared JS module decides.
    pricing: str = "banded"
    unit_hours: Optional[float] = None
    # Functions and Stored Procedures only: objects with a dynamic SQL finding,
    # priced on their own column and not in ``band_counts``, and the hours each.
    # Absent on every other row, which renders an em dash in that column.
    dynamic_sql_count: Optional[int] = None
    dynamic_sql_unit_hours: Optional[float] = None
    # Present on a Code Conversion row. Absent on v1 artifacts and on every other row.
    repetition: Optional[Dict[str, Any]] = None
    # SSIS Package and Informatica Mapping Code Conversion rows only: the EWI groups
    # at full price, with no discount. Absent on older artifacts and every other row.
    ewi_groups: Optional[List[Dict[str, Any]]] = None


def load_effort_assessment(path: Path) -> Optional[Dict[str, Any]]:
    """Load an effort artifact and rehydrate its calculator rows for HTML renderers."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            assessment = json.load(stream)
        assessment["calculator_rows"] = [
            CalculatorRow(**row) for row in assessment.get("calculator_rows") or []
        ]
        return assessment
    except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
        print(f"Warning: Could not load effort estimates data: {exc}", file=sys.stderr)
        return None


# The Effort tab's whole Vue surface, as a mixin the root app pulls in. It lives
# in a plain string rather than inside generate_multi_report.py's f-string
# template so no `{{ }}` needs brace-doubling — the one place a mistake here
# would be invisible until the report renders.
EFFORT_MIXIN_JS = r"""
(function () {
  "use strict";

  const baseline = window.__EFFORT_BASELINE__ || null;
  const shared = globalThis.EffortOverrides || null;
  if (!baseline || !shared) {
    window.__EFFORT_MIXIN__ = null;
    return;
  }

  // Edits stay in memory; download is the only way to persist. The file on disk
  // is the single source of truth shared with the dashboard.
  const stored = shared.parseOverrides(window.__EFFORT_OVERRIDES__ || {});

  /**
   * One 16x16 stroked glyph. Inline because the report is a single file opened over
   * file://, where an icon font or a sprite sheet cannot be fetched. Rendered with
   * v-html from a computed, so the markup is built here rather than in a template
   * attribute where its quotes would have to be escaped.
   */
  function _groupingSingular(objectType) {
    var known = {
      "Functions": "function",
      "Stored Procedures": "stored procedure",
      "SSIS Packages": "package",
      "Informatica PowerCenter Mappings": "mapping",
      "BTEQ Scripts": "BTEQ script",
    };
    if (known[objectType]) return known[objectType];
    var raw = String(objectType || "object").trim();
    if (raw.length > 1 && raw.slice(-1).toLowerCase() === "s") raw = raw.slice(0, -1);
    return raw.toLowerCase() || "object";
  }

  function _groupingPlural(singular) {
    return singular === "stored procedure" ? "stored procedures" : singular + "s";
  }

  function _svg(path) {
    return (
      '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" ' +
      'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" ' +
      'stroke-linejoin="round"><path d="' + path + '"/></svg>'
    );
  }

  /*__ISSUE_DOCUMENTATION_URL_JS__*/

  window.__EFFORT_MIXIN__ = {
    data() {
      const loaded = shared.countEntries(stored);
      return {
        // Rate overrides are keyed (row key -> band -> hours); a flat row's whole
        // budget is one number, so the two live in separate maps exactly as the
        // overrides file stores them.
        effortRateOverrides: Object.assign({}, stored.band_rates),
        effortFlatOverrides: Object.assign({}, stored.flat_hours),
        effortDrafts: {},
        effortErrors: {},
        effortNotice: stored.discarded
          ? "The saved overrides were written by an older effort model" +
            (stored.discarded_version === null ? "" : " (schema " + stored.discarded_version + ")") +
            ", so their rates cannot be applied and need re-entering."
          : loaded > 0 ? loaded + " override(s) loaded from file." : "",
        // Collapse state is view state, not arithmetic, so unlike the override maths
        // it is not shared with the dashboard. A key present and true means closed,
        // so sections start open without having to enumerate them. Not persisted.
        effortCollapsed: {},
        effortMenuOpen: false,
        // One open EWI breakdown at a time. Null when closed; a calculator row
        // when open. Opening it only reads the groups already on the row.
        effortEwiBreakdownRow: null,
      };
    },
    mounted() {
      this._effortEwiOnKeyDown = (event) => {
        if (!event || event.key !== "Escape") return;
        if (this.effortEwiBreakdownRow) this.effortCloseEwiBreakdown();
      };
      window.addEventListener("keydown", this._effortEwiOnKeyDown);
    },
    beforeUnmount() {
      if (this._effortEwiOnKeyDown) {
        window.removeEventListener("keydown", this._effortEwiOnKeyDown);
      }
    },
    computed: {
      effortChevronDown() {
        return _svg('M4 6.5 8 10.5l4-4');
      },
      effortChevronRight() {
        return _svg('M6.5 4 10.5 8l-4 4');
      },
      effortIconDownload() {
        return _svg('M8 2.5v6.5M5.2 6.7 8 9.5l2.8-2.8M3 12.5h10');
      },
      effortIconUpload() {
        return _svg('M8 9.5V3M5.2 5.8 8 3l2.8 2.8M3 12.5h10');
      },
      effortIconReset() {
        return _svg('M3.5 7.5h5.5a2.75 2.75 0 1 1 0 5.5H6M3.5 7.5 6 5M3.5 7.5 6 10');
      },
      effortApplied() {
        return shared.applyOverrides(
          baseline.calculator_rows,
          this.effortRateOverrides,
          this.effortFlatOverrides,
        );
      },
      effortRollup() {
        return shared.rollUp(
          this.effortApplied,
          baseline.summary,
          this.effortRateOverrides,
          this.effortFlatOverrides,
        );
      },
      // Grouping and its subtotals come from the shared module, not from this
      // template, so the report and the dashboard cannot disagree about one.
      effortSections() {
        return shared.groupSections(this.effortApplied, baseline.summary, this.effortRollup)
          .filter(function (section) {
            return section.key === "fixed_budget"
              || section.rows.length
              || section.zeroTypes.length
              || section.extraRows.length;
          });
      },
      // Object type, Category, # objects, Hours/object, Base hours, Grouping,
      // Total hours, Comments: the one grid every section shares. A computed value,
      // so the template's `effortColumnCount - 2` reads a number, not a function.
      effortColumnCount() {
        return 8;
      },
      effortHasOverrides() {
        return this.effortRollup.overridden_count > 0;
      },
      effortTotalChanged() {
        return this.effortRollup.custom.total !== this.effortRollup.sf.total;
      },
      effortCodeChanged() {
        return this.effortRollup.custom.code !== this.effortRollup.sf.code;
      },
      effortFixedBudgetChanged() {
        return this.effortRollup.custom.fixed_budget !== this.effortRollup.sf.fixed_budget;
      },
      effortStaleKeys() {
        return this.effortRollup.stale_keys;
      },
      effortSummary() {
        return baseline.summary || {};
      },
      // An artifact written before fully_converted counted converted objects in its
      // shares, which is not "fully converted": those shares render as unknown.
      effortSharesKnown() {
        const ddl = this.effortSummary.ddl_summary || {};
        return Object.values(ddl).every((stats) => stats && "fully_converted" in stats);
      },
    },
    methods: {
      effortHours(value) {
        if (typeof value !== "number" || !isFinite(value)) return "\u2014";
        return value.toLocaleString(undefined, {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        });
      },
      /** The spreadsheet lines a row renders as, from the shared module so the
       *  dashboard lays out the same cells and totals. */
      effortLines(row) {
        return shared.displayLines(row);
      },
      /** Grouping applies when C# published repetition groups on this object type. */
      effortGroupingApplies(row) {
        return !!(row && row.repetition);
      },
      effortGroupingLabel(row) {
        return this.effortGroupingApplies(row) ? "Yes" : "No";
      },
      effortComments(row) {
        if (row && row.pricing === "critical_split") {
          return "Critical: hours × objects, with EWI grouping. Non-critical: one budget for the type.";
        }
        var text = (row && row.comments) || "";
        return String(text).replace(/^(critical split|flat total|per object);\s*/i, "");
      },
      effortGroupingNote(row) {
        var repetition = row && row.repetition;
        if (!repetition) return "";
        var count = Number(repetition.first_full_price_count);
        if (!isFinite(count) || count < 1) count = 1;
        var singular = _groupingSingular(row.object_type);
        var factor = repetition.discount_factor;
        var rest = " Each additional " + singular + " with that EWI is charged " + factor + "× that rate.";
        var note = count === 1
          ? "The first " + singular + " with a given EWI is charged the full rate for its complexity." + rest
          : "The first " + count + " " + _groupingPlural(singular) + " with a given EWI are charged the full rate for their complexity." + rest;
        var exceptions = (baseline.repetition && baseline.repetition.non_repetitive_codes) || [];
        if (exceptions.length) {
          note += " Some EWIs are not grouped.";
        }
        return note;
      },
      effortHoursOrNa(value) {
        return value === null || value === undefined ? "\u2014" : this.effortHours(value);
      },
      effortCompact(value) {
        return value === null || value === undefined ? "\u2014" : String(value);
      },
      effortDaysLabel(hours) {
        const days = shared.hoursToDays(hours);
        return days.toLocaleString() + (days === 1 ? " day" : " days");
      },
      effortPercent(fraction) {
        const value = typeof fraction === "number" && isFinite(fraction) ? fraction : 0;
        return (value * 100).toFixed(1) + "%";
      },
      effortShare(fraction) {
        return this.effortSharesKnown ? this.effortPercent(fraction) : "\u2014";
      },
      effortCount(value) {
        return typeof value === "number" ? value.toLocaleString() : "0";
      },
      effortQuantity(quantity) {
        return typeof quantity === "number" ? quantity.toLocaleString() : quantity;
      },
      effortBandLabel(band) {
        return band.charAt(0).toUpperCase() + band.slice(1);
      },
      effortMenuPick(action) {
        this.effortMenuOpen = false;
        if (action === 'download') {
          this.effortDownload();
        } else if (action === 'reset') {
          this.effortResetAll();
        }
      },
      effortResetSubLabel() {
        return this.effortHasOverrides
          ? 'Clears every override and returns to the published estimate'
          : 'Nothing to reset — every rate is already Snowflake\u2019s';
      },
      effortIsFlat(section) {
        return section && section.shape === "flat";
      },
      effortSectionOpen(section) {
        // Read, do not probe -- see applyOverrides in effort_overrides.js.
        return this.effortCollapsed[section.key] !== true;
      },
      effortToggleSection(section) {
        // Replace the map rather than mutating it: a new object is what a computed
        // reading it re-runs on.
        const next = Object.assign({}, this.effortCollapsed);
        next[section.key] = this.effortCollapsed[section.key] !== true;
        this.effortCollapsed = next;
      },
      /** Identifies one editable cell: a band of a banded row, or a flat row's budget. */
      effortCellKey(row, band) {
        return band ? row.key + "|" + band : row.key;
      },
      effortInputValue(row, band) {
        // Read, do not probe: a hasOwnProperty check is not tracked by Vue's
        // reactive proxy. See applyOverrides in effort_overrides.js. A blank
        // draft is "", which stays distinct from an absent one.
        const draft = this.effortDrafts[this.effortCellKey(row, band)];
        if (draft !== undefined) {
          return draft;
        }
        // A band-less cell is the Dynamic SQL rate on a row with that column, else
        // the row's budget or per-object rate.
        let value;
        if (band) {
          value = row.custom_band_rates ? row.custom_band_rates[band] : null;
        } else if (shared.hasDynamicSqlColumn(row)) {
          value = row.custom_dynamic_sql_unit_hours;
        } else {
          value = row.custom_flat_hours;
        }
        return value === null || value === undefined ? "" : String(value);
      },
      effortOnInput(row, band, raw) {
        // The draft is exactly what the user typed, so re-rendering never moves
        // the caret; only a valid value reaches the override map.
        const cell = this.effortCellKey(row, band);
        this.effortDrafts[cell] = raw;
        const checked = shared.validateRateInput(raw);
        if (!checked.ok) {
          this.effortErrors[cell] = checked.error;
          return;
        }
        delete this.effortErrors[cell];
        // Typing Snowflake's own number back clears the cell instead of storing an
        // override that prices identically, which would still count toward the
        // badge and still ride along in a downloaded file.
        const stored = shared.overrideToStore(row, band, checked.value);
        if (band) {
          this.effortSetRate(row.key, band, stored);
        } else if (stored === null) {
          delete this.effortFlatOverrides[row.key];
        } else {
          this.effortFlatOverrides[row.key] = stored;
        }
      },
      effortSetRate(key, band, value) {
        // Replace the card rather than mutating it in place: a new object is what
        // makes the computed re-run, and dropping an emptied card keeps the
        // downloaded file free of rows the user has cleared.
        const card = Object.assign({}, this.effortRateOverrides[key]);
        if (value === null) {
          delete card[band];
        } else {
          card[band] = value;
        }
        if (Object.keys(card).length === 0) {
          delete this.effortRateOverrides[key];
        } else {
          this.effortRateOverrides[key] = card;
        }
      },
      effortOnBlur(row, band) {
        const cell = this.effortCellKey(row, band);
        if (this.effortErrors[cell]) return;
        delete this.effortDrafts[cell];
      },
      effortCellError(row, band) {
        return this.effortErrors[this.effortCellKey(row, band)];
      },
      effortSubtotalChanged(section) {
        return section.subtotal.custom !== section.subtotal.sf;
      },
      /** "Views", "Views or Tables", "Views, Tables or Indexes". */
      effortZeroNote(types) {
        const list = Array.isArray(types) ? types : [];
        if (list.length <= 1) return list[0] || "";
        return list.slice(0, -1).join(", ") + " or " + list[list.length - 1];
      },
      effortResetAll() {
        this.effortRateOverrides = {};
        this.effortFlatOverrides = {};
        this.effortDrafts = {};
        this.effortErrors = {};
        this.effortNotice = "";
      },

      effortDownload() {
        const payload = shared.serializeOverrides(
          this.effortRateOverrides,
          this.effortFlatOverrides,
          { artifact: baseline.artifact, source_dialect: baseline.source_dialect },
          new Date().toISOString(),
        );
        const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "effort-overrides.json";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      },
      effortLoadFile(event) {
        this.effortMenuOpen = false;
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          const parsed = shared.parseOverrides(String(reader.result));
          if (parsed.discarded) {
            const version = parsed.discarded_version;
            this.effortNotice =
              file.name +
              " was written by an older effort model" +
              (version === null ? "" : " (schema " + version + ")") +
              ", so its rates cannot be applied and need re-entering.";
            return;
          }
          const count = shared.countEntries(parsed);
          this.effortRateOverrides = Object.assign({}, parsed.band_rates);
          this.effortFlatOverrides = Object.assign({}, parsed.flat_hours);
          this.effortDrafts = {};
          this.effortErrors = {};
          this.effortNotice =
            count === 0
              ? file.name + " carried no overrides, so every figure is Snowflake's again."
              : "Loaded " +
                count +
                " override(s) from " +
                file.name +
                ", replacing what was here.";
        };
        reader.readAsText(file);
        event.target.value = "";
      },
      /** The groups the View EWI Breakdown modal lists: a discounted row's
       *  repetition groups, else the full-price groups SSIS and Informatica
       *  rows publish. Empty when the row has neither, which hides the button. */
      effortEwiGroups(row) {
        if (!row) return [];
        var groups = row.repetition ? row.repetition.groups : row.ewi_groups;
        return Array.isArray(groups) ? groups : [];
      },
      /** The breakdown's Dynamic SQL line, from the shared module so the
       *  dashboard lists the same objects and hours; null hides it. */
      effortEwiDynamicSql(row) {
        return row ? shared.dynamicSqlBreakdown(row) : null;
      },
      /** Whether a row opens View EWI Breakdown: it has groups, or objects
       *  priced on its Dynamic SQL column. */
      effortHasEwiBreakdown(row) {
        return this.effortEwiGroups(row).length > 0 || this.effortEwiDynamicSql(row) !== null;
      },
      effortOpenEwiBreakdown(row) {
        this.effortEwiBreakdownRow = row;
      },
      effortCloseEwiBreakdown() {
        this.effortEwiBreakdownRow = null;
      },
      /** Whether this EWI group is charged with grouping. Full-price groups
       *  (the exceptions) stay at the band rate for every object. */
      effortEwiGroupingLabel(group) {
        if (!group) return "\u2014";
        return group.full_price ? "No" : "Yes";
      },
      /** Why Hours is not Objects × Rate on a grouped EWI. Empty when they match. */
      effortEwiHoursTip(row, group) {
        if (!group || group.full_price) return "";
        var repetition = (row && row.repetition) || {};
        var first = Number(repetition.first_full_price_count);
        if (!isFinite(first) || first < 1) first = 1;
        var count = Number(group.count) || 0;
        var head = Math.min(count, first);
        var tail = count - head;
        if (tail === 0) return "";
        var rate = this.effortEwiGroupRate(row, group);
        var rateText = String(Math.round(rate * 10000) / 10000);
        var first = head === 1
          ? "The first object is charged " + rateText + " h."
          : "The first " + head + " objects are charged " + rateText + " h each.";
        var rest = "The other " + tail + (tail === 1 ? " object is" : " objects are") +
          " charged " + repetition.discount_factor + "\u00d7 that rate.";
        return first + " " + rest + " So Hours is not " + count + " \u00d7 " + rateText + " h.";
      },
      effortEwiGroupRate(row, group) {
        var rates = row && (row.custom_band_rates || row.band_rates);
        if (!rates || !group) return null;
        var rate = rates[group.band];
        return typeof rate === "number" && isFinite(rate) ? rate : null;
      },
      effortEwiDynamicSqlRate(row) {
        var rate = row && row.custom_dynamic_sql_unit_hours;
        return typeof rate === "number" && isFinite(rate) ? rate : null;
      },
      /** Docs page for an EWI group's code, the same link object details use;
       *  empty for the "No EWI" group, which stays plain text. */
      effortEwiDocUrl(code) {
        return code ? issueDocumentationUrl(code) : "";
      },
      // The report's own Discovery tab, Optimization Opportunities panel: the
      // effort table and Discovery are one page, so this switches tabs, no popup.
      effortOpenOptimizationOpportunities() {
        this.activeTab = "discovery";
        this.discoveryTab = "optimization";
      },
    },
  };
})();
""".replace("/*__ISSUE_DOCUMENTATION_URL_JS__*/", ISSUE_DOCUMENTATION_URL_JS)

# Every block below is a plain (non-f) string, interpolated whole into the
# renderers' f-strings. f-string interpolation runs once, so Vue's `{{ }}` inside
# these constants is never parsed as a replacement field and needs no doubling —
# which is where a silent brace mistake would otherwise land.

_EFFORT_KPI_CARDS_HTML = """
        <div class="effort-cards">
            <div class="effort-card">
                <div class="effort-card-num">{{ effortCount(effortSummary.ddl_objects) }}</div>
                <div class="effort-card-lbl">Priced Objects/*__PRICED_OBJECTS_INFO_ICON__*/</div>
                /*__PENDING_SUBLINE__*/
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{{ effortShare(effortSummary.ddl_auto_pct) }}</div>
                <div class="effort-card-lbl">DDL Fully Converted</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{{ effortHours(effortRollup.custom.total) }} h</div>
                <div class="effort-card-lbl">Total Effort</div>
                <div v-if="effortTotalChanged" class="effort-sf-note">Snowflake: {{ effortHours(effortRollup.sf.total) }} h</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{{ effortHours(effortRollup.custom.code) }} h</div>
                <div class="effort-card-lbl">Code Conversion Effort</div>
                <div v-if="effortCodeChanged" class="effort-sf-note">Snowflake: {{ effortHours(effortRollup.sf.code) }} h</div>
            </div>
        </div>
""".replace("/*__PRICED_OBJECTS_INFO_ICON__*/", _PRICED_OBJECTS_INFO_ICON).replace(
    "/*__PENDING_SUBLINE__*/", _PENDING_SUBLINE_HTML
)

_EFFORT_BAND_LEGEND_HTML = """
        <div class="effort-band-legend">
            <span class="effort-band-legend-lead">Every object is counted in exactly one complexity band:</span>
            <span><strong>Critical</strong> — a critical finding</span>
            <span><strong>High</strong> — a high-severity finding</span>
            <span><strong>Medium</strong> — a medium-severity finding</span>
            <span><strong>Low</strong> — converted clean, or minor findings only</span>
        </div>
"""

_EFFORT_TOOLBAR_HTML = """
        <div class="effort-toolbar print-omit">
            <div class="effort-menu-wrap">
                <button type="button" class="effort-btn effort-menu-btn"
                        :aria-expanded="effortMenuOpen ? 'true' : 'false'"
                        @click="effortMenuOpen = !effortMenuOpen">
                    Overrides
                    <span class="effort-chevron" aria-hidden="true" v-html="effortChevronDown"></span>
                </button>
                <!-- A backdrop closes the menu on any outside click, so the mixin needs
                     no document-level listener and no lifecycle hook of its own. -->
                <div v-if="effortMenuOpen" class="effort-menu-backdrop" @click="effortMenuOpen = false"></div>
                <div v-if="effortMenuOpen" class="effort-menu" role="menu">
                    <button type="button" class="effort-menu-item" role="menuitem"
                            @click="effortMenuPick('download')">
                        <span class="effort-menu-icon" aria-hidden="true" v-html="effortIconDownload"></span>
                        <span class="effort-menu-text">
                            <span class="effort-menu-label">Download a copy</span>
                            <span class="effort-menu-sub">Keeps your rates in a file you can hand to someone else</span>
                        </span>
                    </button>
                    <label class="effort-menu-item" role="menuitem">
                        <span class="effort-menu-icon" aria-hidden="true" v-html="effortIconUpload"></span>
                        <span class="effort-menu-text">
                            <span class="effort-menu-label">Load from a file</span>
                            <span class="effort-menu-sub">Replaces the rates on this page with the ones in the file</span>
                        </span>
                        <input type="file" accept="application/json,.json" @change="effortLoadFile" hidden>
                    </label>
                    <button type="button" class="effort-menu-item effort-menu-danger" role="menuitem"
                            :disabled="!effortHasOverrides" @click="effortMenuPick('reset')">
                        <span class="effort-menu-icon" aria-hidden="true" v-html="effortIconReset"></span>
                        <span class="effort-menu-text">
                            <span class="effort-menu-label">Reset all to Snowflake's</span>
                            <span class="effort-menu-sub">{{ effortResetSubLabel() }}</span>
                        </span>
                    </button>
                </div>
            </div>
            <span v-if="effortHasOverrides" class="effort-badge">
                {{ effortRollup.overridden_count }} applied
            </span>
        </div>
        <p v-if="effortNotice" class="effort-notice">{{ effortNotice }}</p>
        <p v-if="effortStaleKeys.length" class="effort-warning">
            {{ effortStaleKeys.length }} override(s) no longer match this assessment and are
            being ignored: {{ effortStaleKeys.join(', ') }}
        </p>
"""

# One spreadsheet on one grid: every section shares the same eight columns, so a
# fixed budget's Base hours and Total hours sit under the same columns as the
# conversion lines' figures. Each open section has its own header row above its
# banner; a collapsed one shows only its banner. A fixed-budget section spans its
# header and lines across the columns it does not use: Object type covers the first
# four, Base hours covers two.
# Conversion: one line per priced category. Each object type expands into the lines
# it is priced by -- Dynamic SQL then the four bands for banded rows, Critical then
# Non-critical for tables and views, one line otherwise. Cells a line does not use
# read a dash. Object type, Grouping and Comments span the lines of their object
# type. Sections keep their collapsible banner with the subtotal, so collapsing one
# never hides the figure it reports. The fixed-budget section's subtotal is the grand
# total less conversion and testing, so the sections always add up even when the
# summary counts a flat budget that no calculator row carries.
_EFFORT_CALCULATOR_TABLE_HTML = """
        <div class="effort-table-wrap">
            <table class="effort-table effort-sheet">
                <colgroup>
                    <col class="effort-col-type">
                    <col class="effort-col-category">
                    <col class="effort-col-count">
                    <col class="effort-col-rate">
                    <col class="effort-col-fixed">
                    <col class="effort-col-grouping">
                    <col class="effort-col-total">
                    <col class="effort-col-comments">
                </colgroup>
                <tbody v-for="section in effortSections" :key="section.key">
                    <tr v-if="!effortIsFlat(section) &amp;&amp; effortSectionOpen(section)">
                        <th class="effort-ewi-tip" title="The kind of object being priced, such as Stored Procedures, Views or Tables. An object type can have several lines below it.">Object type</th>
                        <th class="effort-ewi-tip" title="Which pricing line this is within the object type: Dynamic SQL, a complexity band (Critical, High, Medium or Low), Critical or Non-critical, or All objects.">Category</th>
                        <th class="num effort-ewi-tip" title="How many objects this line prices. A dash means the line is a fixed budget, so no object count applies."># objects</th>
                        <th class="num effort-ewi-tip" title="Hours to migrate one object on this line. Total hours is # objects times this, except where Grouping is Yes and repeated EWIs are discounted.">Hours/object</th>
                        <th class="num effort-ewi-tip" title="A budget for the whole line, not per object. The # objects count does not multiply it.">Base hours</th>
                        <th class="ctr effort-ewi-tip" title="/*__GROUPING_COLUMN_TIP__*/">Grouping</th>
                        <th class="num effort-ewi-tip" title="Hours this line adds to its section total: # objects times Hours/object after any grouping discount, or the Base hours budget.">Total hours</th>
                        <th class="effort-ewi-tip" title="How the object type is priced, with links to the EWI Breakdown or Optimization Opportunities where they apply.">Comments</th>
                    </tr>
                    <tr v-if="effortIsFlat(section) &amp;&amp; effortSectionOpen(section)">
                        <th class="effort-ewi-tip" colspan="4" title="The budget line being priced, such as UAT, Integration Testing or Data Migration.">Object type</th>
                        <th class="num effort-ewi-tip" colspan="2" title="A budget for the whole line, not per object. The # objects count does not multiply it.">Base hours</th>
                        <th class="num effort-ewi-tip" title="Hours this line adds to its section total. For a fixed budget, this is the Base hours.">Total hours</th>
                        <th class="effort-ewi-tip" title="How the line is priced, with a link to Optimization Opportunities where it applies.">Comments</th>
                    </tr>
                    <tr>
                        <th class="effort-section" :colspan="effortColumnCount - 2" scope="colgroup">
                            <button type="button" class="effort-section-toggle"
                                    :aria-expanded="effortSectionOpen(section) ? 'true' : 'false'"
                                    @click="effortToggleSection(section)">
                                <span class="effort-chevron" aria-hidden="true"
                                      v-html="effortSectionOpen(section) ? effortChevronDown : effortChevronRight"></span>
                                <span>{{ section.title }}</span>
                            </button>
                        </th>
                        <th class="effort-section effort-section-total" scope="colgroup">
                            {{ effortHours(section.subtotal.custom) }}
                            <span v-if="effortSubtotalChanged(section)" class="effort-sf-note">Snowflake: {{ effortHours(section.subtotal.sf) }}</span>
                        </th>
                        <th class="effort-section" scope="colgroup"></th>
                    </tr>
                    <template v-if="effortSectionOpen(section)">
                    <template v-for="row in section.rows" :key="row.key">
                        <tr v-for="(line, index) in effortLines(row)" :key="line.id"
                            :class="{'effort-row-overridden': row.is_overridden, 'effort-line-first': index === 0}">
                            <template v-if="index === 0">
                                <td :rowspan="effortLines(row).length" :colspan="effortIsFlat(section) ? 4 : 1" class="effort-type-cell">
                                    {{ row.object_type }}
                                    <span v-if="row.is_overridden &amp;&amp; !row.is_unestimated" class="effort-sf-note">Snowflake: {{ effortHoursOrNa(row.estimated_hours) }} h</span>
                                </td>
                            </template>
                            <td v-if="!effortIsFlat(section)" class="effort-category">{{ line.category || '\u2014' }}</td>
                            <td v-if="!effortIsFlat(section)" class="num">{{ line.count === null ? '\u2014' : effortCount(line.count) }}</td>
                            <td v-if="!effortIsFlat(section)" class="num">
                                <input v-if="row.is_editable &amp;&amp; (line.cell === 'unit' || line.cell === 'dynamic')"
                                       type="text" inputmode="decimal" class="effort-input"
                                       :class="{'effort-input-error': effortCellError(row, line.band)}"
                                       :value="effortInputValue(row, line.band)"
                                       :aria-label="'Hours per object for ' + row.object_type + ' ' + (line.category || '')"
                                       :title="'Hours to migrate one ' + (line.category || '') + ' object'"
                                       @input="effortOnInput(row, line.band, $event.target.value)"
                                       @blur="effortOnBlur(row, line.band)">
                                <span v-else>{{ (line.cell === 'unit' || line.cell === 'dynamic') ? effortInputValue(row, line.band) : '\u2014' }}</span>
                                <span v-if="effortCellError(row, line.band)" class="effort-error">{{ effortCellError(row, line.band) }}</span>
                                <span v-else-if="line.unit_changed" class="effort-sf-note">Snowflake: {{ effortCompact(line.sf_unit_hours) }}</span>
                            </td>
                            <td :colspan="effortIsFlat(section) ? 2 : 1" class="num">
                                <input v-if="row.is_editable &amp;&amp; line.cell === 'fixed'"
                                       type="text" inputmode="decimal" class="effort-input"
                                       :class="{'effort-input-error': effortCellError(row, null)}"
                                       :value="effortInputValue(row, null)"
                                       :aria-label="'Base hours for ' + row.component + ' ' + row.object_type"
                                       :title="row.is_unestimated ? 'Snowflake publishes no figure for this line — enter your own budget' : 'One budget for this line. The object count does not multiply it.'"
                                       @input="effortOnInput(row, null, $event.target.value)"
                                       @blur="effortOnBlur(row, null)">
                                <span v-else>{{ line.cell === 'fixed' ? effortInputValue(row, null) : '\u2014' }}</span>
                                <span v-if="effortCellError(row, null)" class="effort-error">{{ effortCellError(row, null) }}</span>
                                <span v-else-if="line.cell === 'fixed' &amp;&amp; row.is_unestimated" class="effort-sf-note">Please provide user input.</span>
                                <span v-else-if="line.fixed_changed" class="effort-sf-note">Snowflake: {{ effortCompact(line.sf_fixed_hours) }}</span>
                            </td>
                            <td v-if="index === 0 &amp;&amp; !effortIsFlat(section)" class="ctr" :rowspan="effortLines(row).length">{{ effortGroupingLabel(row) }}</td>
                            <td class="num effort-line-total">{{ effortHoursOrNa(line.total) }}</td>
                            <td v-if="index === 0" class="effort-comments" :rowspan="effortLines(row).length">
                                <div class="effort-comments-body">
                                    {{ effortComments(row) }}
                                    <span v-if="row.repetition" class="effort-comment-note">{{ effortGroupingNote(row) }}</span>
                                    <span v-if="row.automation_pct !== null" class="effort-sf-note">{{ effortShare(row.automation_pct) }} fully converted</span>
                                    <button
                                        v-if="effortHasEwiBreakdown(row)"
                                        type="button"
                                        class="effort-ewi-link"
                                        @click="effortOpenEwiBreakdown(row)"
                                    >View EWI Breakdown</button>
                                    <button
                                        v-if="row.key === 'optimization'"
                                        type="button"
                                        class="effort-ewi-link"
                                        @click="effortOpenOptimizationOpportunities"
                                    >View Optimization Opportunities</button>
                                </div>
                            </td>
                        </tr>
                    </template>
                    <tr v-for="extra in section.extraRows" :key="extra.label" class="effort-line-first">
                        <td :colspan="effortIsFlat(section) ? 4 : 1">{{ extra.label }}</td>
                        <td v-if="!effortIsFlat(section)">\u2014</td>
                        <td v-if="!effortIsFlat(section)">\u2014</td>
                        <td v-if="!effortIsFlat(section)" class="num">\u2014</td>
                        <td :colspan="effortIsFlat(section) ? 2 : 1" class="num">{{ effortHours(extra.hours) }}</td>
                        <td v-if="!effortIsFlat(section)" class="ctr">No</td>
                        <td class="num effort-line-total">{{ effortHours(extra.hours) }}</td>
                        <td>Priced as a flat budget; not editable</td>
                    </tr>
                    <tr v-if="section.zeroTypes.length">
                        <td class="effort-muted" :colspan="effortColumnCount">
                            No {{ effortZeroNote(section.zeroTypes) }} in this workload.
                        </td>
                    </tr>
                    </template>
                </tbody>
                <tbody>
                    <tr class="effort-total">
                        <td :colspan="effortColumnCount - 2">TOTAL MIGRATION EFFORT</td>
                        <td class="num">
                            {{ effortHours(effortRollup.custom.total) }}
                            <span v-if="effortTotalChanged" class="effort-sf-note">Snowflake: {{ effortHours(effortRollup.sf.total) }}</span>
                        </td>
                        <td></td>
                    </tr>
                </tbody>
            </table>
        </div>
        <div
            v-if="effortEwiBreakdownRow"
            class="effort-ewi-modal-overlay"
            role="dialog"
            aria-modal="true"
            :aria-label="'EWI breakdown for ' + effortEwiBreakdownRow.object_type"
            @click="effortCloseEwiBreakdown"
        >
            <div class="effort-ewi-modal" @click.stop>
                <div class="effort-ewi-modal-bar">
                    <div class="effort-ewi-modal-title">{{ effortEwiBreakdownRow.object_type }}</div>
                    <button type="button" class="effort-ewi-modal-close" @click="effortCloseEwiBreakdown">Close</button>
                </div>
                <div class="effort-ewi-modal-body">
                    <table class="effort-table">
                        <thead>
                            <tr>
                                <th class="effort-ewi-tip" title="Error Warning Issues generated during code conversion">EWI code</th>
                                <th>Complexity</th>
                                <th class="num">Objects</th>
                                <th class="num">Hours/object</th>
                                <th class="ctr effort-ewi-tip" title="/*__GROUPING_COLUMN_TIP__*/">Grouping</th>
                                <th class="num">Hours</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="group in effortEwiGroups(effortEwiBreakdownRow)"
                                :key="(group.code || 'none') + '-' + group.band">
                                <td>
                                    <a v-if="effortEwiDocUrl(group.code)" :href="effortEwiDocUrl(group.code)"
                                       target="_blank" rel="noopener noreferrer"
                                       class="effort-ewi-doc-link">{{ group.code }}</a>
                                    <template v-else>{{ group.code || 'No EWI' }}</template>
                                </td>
                                <td>{{ effortBandLabel(group.band) }}</td>
                                <td class="num">{{ effortCount(group.count) }}</td>
                                <td class="num">{{ effortCompact(effortEwiGroupRate(effortEwiBreakdownRow, group)) }}</td>
                                <td class="ctr">{{ effortEwiGroupingLabel(group) }}</td>
                                <td class="num">
                                    <span v-if="effortEwiHoursTip(effortEwiBreakdownRow, group)"
                                          class="effort-ewi-tip"
                                          :title="effortEwiHoursTip(effortEwiBreakdownRow, group)">{{ effortHours(group.hours) }}</span>
                                    <template v-else>{{ effortHours(group.hours) }}</template>
                                </td>
                            </tr>
                            <tr v-if="effortEwiDynamicSql(effortEwiBreakdownRow)">
                                <td class="effort-ewi-tip" title="Objects with SSC-EWI-0030, SSC-EWI-0125, SSC-EWI-0126 or SSC-EWI-0129, priced at the Dynamic SQL rate instead of a complexity band">Dynamic SQL</td>
                                <td class="effort-muted">\u2014</td>
                                <td class="num">{{ effortCount(effortEwiDynamicSql(effortEwiBreakdownRow).count) }}</td>
                                <td class="num">{{ effortCompact(effortEwiDynamicSqlRate(effortEwiBreakdownRow)) }}</td>
                                <td class="ctr">\u2014</td>
                                <td class="num">{{ effortHoursOrNa(effortEwiDynamicSql(effortEwiBreakdownRow).hours) }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
""".replace("/*__GROUPING_COLUMN_TIP__*/", html.escape(GROUPING_COLUMN_TIP))

_OVERVIEW_EFFORT_CARD_TOTAL_HTML = """
                <div class="effort-card">
                    <div class="effort-card-num">{{ effortDaysLabel(effortRollup.custom.total) }}</div>
                    <div class="effort-card-lbl">Total Effort</div>
                    <div v-if="effortTotalChanged" class="effort-sf-note">Snowflake: {{ effortDaysLabel(effortRollup.sf.total) }}</div>
                </div>
                <div class="effort-card">
                    <div class="effort-card-num">{{ effortHours(effortRollup.custom.code) }} h</div>
                    <div class="effort-card-lbl">Code Conversion Effort · {{ effortCount(effortSummary.ddl_objects) }} priced objects/*__PRICED_OBJECTS_INFO_ICON__*/ · {{ effortShare(effortSummary.ddl_auto_pct) }} fully converted · includes unit testing</div>
                    <div v-if="effortCodeChanged" class="effort-sf-note">Snowflake: {{ effortHours(effortRollup.sf.code) }} h</div>
                </div>
""".replace("/*__PRICED_OBJECTS_INFO_ICON__*/", _PRICED_OBJECTS_INFO_ICON)

_OVERVIEW_FIXED_BUDGET_VALUE_HTML = """
                    <div style="font-size: 1.6rem; font-weight: 800; color: #102E46; margin-top: 4px;">{{ effortHours(effortRollup.custom.fixed_budget) }} h</div>
                    <div v-if="effortFixedBudgetChanged" class="effort-sf-note">Snowflake: {{ effortHours(effortRollup.sf.fixed_budget) }} h</div>
"""


def load_effort_overrides(path: Path) -> Dict[str, Any]:
    """Load the user's baseline-hour overrides, or an empty set if unusable.

    The overrides are a convenience layered on an estimate that stands without
    them, so an absent or corrupt file must not stop the report generating.
    """
    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Warning: Could not load effort overrides: {exc}", file=sys.stderr)
        return {}
    if not isinstance(payload, dict):
        print("Warning: Could not load effort overrides: not a JSON object", file=sys.stderr)
        return {}
    return payload


def effort_overrides_module_js() -> str:
    """The shared override module's source, for inlining into the report.

    Inlined rather than linked because the report is opened over file://, where a
    linked script would be blocked.
    """
    module = Path(__file__).parent / "effort_overrides.js"
    try:
        return module.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Warning: Could not read {module.name}: {exc}", file=sys.stderr)
        return ""


def _json_for_script(value: Any) -> str:
    """`json.dumps`, safe to embed inside an HTML `<script>` block.

    A `</script>` sequence inside a string value (a project name or dialect
    label, ultimately from the source database) would otherwise close the
    tag early and let whatever follows run as markup. `<` and `>` cannot
    appear in valid JSON syntax outside a string, so escaping them is lossless.
    """
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def effort_payloads_js(
    assessment: Dict[str, Any],
    overrides: Optional[Dict[str, Any]] = None,
    artifact_name: str = "",
) -> str:
    """Baseline artifact and stored overrides, as globals the mixin reads."""
    baseline = {
        "project_name": assessment.get("project_name", ""),
        "source_dialect": assessment.get("source_dialect", ""),
        "artifact": artifact_name,
        "summary": assessment.get("summary", {}),
        "repetition": assessment.get("repetition"),
        "calculator_rows": [asdict(row) for row in assessment.get("calculator_rows", [])],
    }
    return (
        "window.__EFFORT_BASELINE__ = "
        + _json_for_script(baseline)
        + ";\nwindow.__EFFORT_OVERRIDES__ = "
        + _json_for_script(overrides or {})
        + ";"
    )


def effort_overrides_js(
    assessment: Dict[str, Any],
    overrides: Optional[Dict[str, Any]] = None,
    artifact_name: str = "",
) -> str:
    """Everything the Effort tab's interactivity needs, as one classic script."""
    return "\n".join(
        [
            effort_overrides_module_js(),
            effort_payloads_js(assessment, overrides, artifact_name),
            EFFORT_MIXIN_JS,
        ]
    )


def workload_size_label(tier: str, small_max: int, medium_max: int) -> str:
    """Human-readable workload tier label using thresholds from the artifact."""
    labels = {
        "small": f"Small (up to {small_max:,} objects)",
        "medium": f"Medium ({small_max + 1:,}–{medium_max:,} objects)",
        "large": f"Large (more than {medium_max:,} objects)",
    }
    return labels.get(tier, tier.title())


def _esc(text: Any) -> str:
    import html

    return html.escape(str(text)) if text is not None else ""


def _js_str(value: str) -> str:
    """A JS string literal safe to embed in a double-quoted HTML attribute.

    Vue expressions live in attributes (``v-if="..."``), so a double-quoted JS
    string would close the attribute at its first quote and leave the browser
    parsing the rest of the expression as further attribute names -- Vue then
    never sees the expression at all. Single quotes survive the HTML parser.
    """
    js = value.replace("\\", "\\\\").replace("'", "\\'")
    # `"` becomes an entity rather than a JS escape: the HTML parser decodes it
    # back to a plain quote inside the single-quoted literal, so the attribute
    # stays intact and the expression Vue compiles is unchanged.
    html_safe = (
        js.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    )
    return "'" + html_safe + "'"


def _js_str_array(values: List[str]) -> str:
    """A JS array-of-strings literal, attribute-safe -- see :func:`_js_str`."""
    return "[" + ", ".join(_js_str(v) for v in values) + "]"


def _hours_to_rounded_days(hours: float) -> int:
    """Convert effort hours to whole days, rounded up (8h work day)."""
    if hours <= 0:
        return 0
    return int(math.ceil(hours / _HOURS_PER_WORK_DAY))


def _days_label(days: int) -> str:
    return f"{days:,} day" if days == 1 else f"{days:,} days"


def _render_fixed_budget_info_icon(
    fixed_items: Dict[str, Optional[float]],
    workload_tier: str,
    total_objects: int,
    small_max: int,
    medium_max: int,
) -> str:
    """Info icon with hover tooltip listing fixed budget line items."""
    if not fixed_items:
        return ""
    header = (
        f"<div style='margin-bottom:8px;font-weight:600;'>"
        f"{_esc(workload_size_label(workload_tier, small_max, medium_max))} · "
        f"{total_objects:,} priced objects"
        f"</div>"
    )
    tooltip_lines = header + "".join(
        f"<div style='margin-bottom:4px;'>{_esc(label)}: "
        f"{f'{hours:g} h' if hours is not None else _NOT_APPLICABLE}</div>"
        for label, hours in fixed_items.items()
    )
    return (
        f'<span class="info-icon" style="margin-left:4px;">i'
        f'<span class="tooltip">{tooltip_lines}</span></span>'
    )


def render_overview_section_b_html(assessment: Dict[str, Any]) -> str:
    """Section B on Overview: effort summary for SQL Server DDL + fixed budgets."""
    s = assessment["summary"]
    ddl = s.get("ddl_summary", {})
    shares_known = _publishes_fully_converted(ddl)
    ddl_rows = ""
    for obj_type in sorted(ddl.keys()):
        if obj_type in _DDL_EXCLUDED_DISPLAY_TYPES:
            continue
        st = ddl[obj_type]
        pct = _ddl_share_cell(st, shares_known)
        bands = st.get("bands") or {}
        ddl_rows += f"""
        <tr>
            <td>{_esc(obj_type)}</td>
            <td class="ctr">{st['total']:,}</td>
            <td class="ctr">{bands.get('critical', 0):,}</td>
            <td class="ctr">{bands.get('high', 0):,}</td>
            <td class="ctr">{bands.get('medium', 0):,}</td>
            <td class="ctr">{bands.get('low', 0):,}</td>
            <td class="ctr">{pct}</td>
        </tr>"""

    fixed_items = s.get("fixed_budget_items", {})
    workload_tier = s.get("workload_size_tier", "small")
    workload_objects = s.get("workload_object_count", s.get("ddl_objects", 0))
    small_max = s.get("workload_small_max", 500)
    medium_max = s.get("workload_medium_max", 1500)
    fixed_info_icon = _render_fixed_budget_info_icon(
        fixed_items,
        workload_tier,
        workload_objects,
        small_max,
        medium_max,
    )
    workload_subtitle = (
        f"<div style='font-size:0.72rem;color:#64748B;margin-top:4px;'>"
        f"{_esc(workload_size_label(workload_tier, small_max, medium_max))}</div>"
    )

    return f"""
            <h2 id="effort-estimates" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <span style="background: #E0F2FE; color: #0284C7; padding: 4px 10px; border-radius: 6px; font-size: 0.9rem;">Section B</span>
                Estimated effort to migrate
            </h2>
            {EFFORT_DISCLAIMER_HTML}
            <p style="color: #64748B; font-size: 0.95rem; margin-bottom: 20px; line-height: 1.6;">
                Every object is placed in one complexity band and priced at that band's hours per object,
                plus flat budgets for the project phases. Counts reflect unique converted objects
                (session and batch rows excluded).
            </p>

            <div class="effort-cards">
{_OVERVIEW_EFFORT_CARD_TOTAL_HTML}
                <div style="background: white; padding: 18px; border-radius: 12px; border-top: 4px solid #FF9F36; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <div style="font-size: 0.78rem; color: #64748B; font-weight: 600; text-transform: uppercase; display: flex; align-items: center;">
                        Fixed Budget{fixed_info_icon}
                    </div>
{_OVERVIEW_FIXED_BUDGET_VALUE_HTML}
                    {workload_subtitle}
                </div>
            </div>

            <h3 style="font-size: 1.1rem; font-weight: 700; color: #102E46; margin-bottom: 12px;">Objects by complexity band</h3>
            <div class="effort-table-wrap">
                <table class="effort-table">
                    <thead>
                        <tr>
                            <th>Object Type</th>
                            <th class="ctr">Total</th>
                            <th class="ctr">Critical</th>
                            <th class="ctr">High</th>
                            <th class="ctr">Medium</th>
                            <th class="ctr">Low</th>
                            <th class="ctr">% Fully Converted</th>
                        </tr>
                    </thead>
                    <tbody>{ddl_rows}</tbody>
                </table>
            </div>

            <div style="background: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 10px; padding: 16px 20px; margin-bottom: 40px;">
                <p style="margin: 0 0 8px 0; color: #102E46; font-weight: 600;">Need line-item detail?</p>
                <p style="margin: 0 0 12px 0; color: #475569; font-size: 0.9rem; line-height: 1.5;">
                    The Effort Estimates tab shows the full migration calculator — every component, its objects per complexity band, the editable hours per object, and the resulting total.
                </p>
                <a @click="activeTab = 'effort-estimates'"
                   style="display: inline-block; background: #005C8F; color: white; padding: 10px 18px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; cursor: pointer; text-decoration: none;">
                    Open detailed effort calculator →
                </a>
            </div>
    """


def _publishes_fully_converted(ddl_summary: Dict[str, Dict[str, Any]]) -> bool:
    """Whether the artifact's shares count fully converted objects.

    An artifact written before ``fully_converted`` derived ``pct_auto`` from
    converted objects, so its shares are shown as unknown rather than relabelled.
    """
    return all("fully_converted" in stats for stats in ddl_summary.values())


def _ddl_share_cell(st: Dict[str, Any], shares_known: bool) -> str:
    """One type's % Fully Converted cell. A type with nothing priced has no share."""
    return f"{st['pct_auto'] * 100:.1f}%" if shares_known and st["total"] else "\u2014"


def _repeated_ewi_legend(repetition: Dict[str, Any]) -> str:
    """Legend sentence for rows that price repeated EWIs. The count and factor are the artifact's."""
    factor = _esc(repetition.get("discount_factor"))
    try:
        count = int(repetition.get("first_full_price_count"))
    except (TypeError, ValueError):
        count = 1
    if count == 1:
        lead = "the first object with a given EWI is charged the full rate for its complexity."
    else:
        lead = (
            f"the first {_esc(count)} objects with a given EWI are charged "
            "the full rate for their complexity."
        )
    return (
        "<p><strong>Repeated EWIs:</strong> on a Code Conversion row, "
        f"{lead} Each additional object with that EWI is charged {factor}× that rate.</p>"
    )


def _render_effort_formulas_legend(
    summary: Dict[str, Any],
    repetition: Optional[Dict[str, Any]] = None,
) -> str:
    """Collapsible legend explaining how each effort figure is derived."""
    automation_note = ""
    if summary.get("hours_saved_by_automation", 0) > 0:
        automation_note = (
            "<p><strong>Saved by automation:</strong> what the same objects would cost rebuilt "
            "by hand, minus what is charged above. Automation is never applied as a discount to "
            "the hours themselves — it is already expressed by where the objects landed, since a "
            "cleanly converted object is a Low one. "
            f"Here a manual rebuild would cost ≈ {summary.get('manual_rewrite_hours', 0):,.0f} h "
            f"against the {summary.get('code_estimated_hours', 0):,.0f} h charged, so automation "
            f"saved ≈ {summary.get('hours_saved_by_automation', 0):,.0f} h.</p>"
        )
    repetition_note = ""
    if isinstance(repetition, dict):
        repetition_note = _repeated_ewi_legend(repetition)
    return f"""
        <details style="margin-bottom:32px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:16px;">
            <summary style="font-weight:700;color:#102E46;cursor:pointer;">How these hours are calculated</summary>
            <div style="margin-top:12px;font-size:0.88rem;color:#475569;line-height:1.6;">
                <p><strong>Rows with no repeated EWI</strong> price each band as objects times its rate:</p>
                <p style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:6px;padding:10px 12px;">
                    hours = (critical objects × h/critical) + (high × h/high) + (medium × h/medium) + (low × h/low)
                </p>
                <p>Every object is counted in exactly one band, so the band counts always add up to the
                object total — which means you can reproduce any figure in the calculator with a
                calculator. A Code Conversion row adds up the group hours listed in View EWI Breakdown.</p>
                {repetition_note}
                <p><strong>Bands:</strong> Critical = a critical finding.
                High = a high-severity finding. Medium = a medium-severity finding.
                Low = minor findings only, or none. Conversion status does not set the band.</p>
                {automation_note}
                <p><strong>Fixed Budget:</strong> data migration setup and project-phase lines are left for you to fill in —
                Snowflake publishes no figure for those yet.</p>
                <p><strong>Sources:</strong> conversion statistics — per-object conversion status and issue severities.</p>
            </div>
        </details>"""


def render_effort_tab_html(assessment: Dict[str, Any]) -> str:
    """Full effort page aligned with the migration assessment workbook sections."""
    summary = assessment["summary"]
    formulas_legend = _render_effort_formulas_legend(summary, assessment.get("repetition"))

    return f"""
    <div class="tab-content" :class="{{active: activeTab === 'effort-estimates'}}">
        <div style="margin-bottom: 24px;">
            <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                Migration effort estimates
            </h1>
            <p class="effort-lead">
                This estimate reflects the total human-hours required for the migration using AIM.
                Using the output of our deterministic conversion engine, we categorized each object
                into Critical, High, Medium, or Low complexity based on flagged issues. Standard
                Snowflake baseline effort estimates are automatically applied per object type, but
                these rates are fully customizable to fit your team's specific baseline.
            </p>
        </div>

{_EFFORT_KPI_CARDS_HTML}

        <h2 id="effort-calculator" style="font-size:1.35rem;font-weight:700;color:#102E46;margin-bottom:12px;">Migration effort calculator</h2>
        <p class="effort-lead print-omit">
            Every hours-per-object cell is editable. Change one and its row, its section subtotal,
            the total and the cards above all follow — Snowflake's own figure stays beside yours, so
            nothing is overwritten.
        </p>
        <p class="effort-lead print-omit">
            Your changes are called <strong>overrides</strong>{_OVERRIDES_INFO_ICON}. They live in
            this page while it is open — download them to keep them, or to hand them to someone else.
        </p>
{_EFFORT_BAND_LEGEND_HTML}
{_EFFORT_TOOLBAR_HTML}
{_EFFORT_CALCULATOR_TABLE_HTML}

        {formulas_legend}
    </div>
    """
