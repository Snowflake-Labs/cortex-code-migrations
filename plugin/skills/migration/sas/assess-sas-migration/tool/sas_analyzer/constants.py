"""Shared constants and the canonical countable-block iterator.

Single source of truth for block counting so the portfolio total, per-file count,
and per-tier distribution are always computed over the SAME set of blocks and
reconcile. Mirrors `references/block-tiering-spec.md` (Section 1).
"""

import re
from typing import Iterator, List

from .parser import SASScript, SASBlock, BlockType


# DI Studio / DataFlow scaffolding macro names — always excluded from counts and tiering.
BOILERPLATE_MACRO_NAMES = frozenset({
    'rcset', 'rcsetds', 'etls_startperformancestats', 'etls_setdebug',
    'etls_recordcount', 'etls_endperformancestats', 'etls_recordtable',
    'etls_getrecordcount', 'etls_jobstatus', 'etls_logerror',
})
# DI Studio (etls_*) and SAS Studio Flow (_flw_*) generate open-ended macro families. One is
# scaffolding only when it does no work: no named dataset and no transforming PROC.
BOILERPLATE_MACRO_PREFIXES = ('etls_', '_flw_')
TRANSPORT_PROCS = frozenset({'upload', 'download', 'printto', 'options', 'optsave', 'optload'})

# Statistical / modelling PROCs -> Tier 3 (PySpark/SCOS). One canonical list (a floor, not a closed
# set); block-tiering-spec.md mirrors it. Matched as whole words after string literals are stripped.
TIER3_STAT_PROCS = (
    'reg', 'glm', 'logistic', 'cluster', 'fastclus', 'factor', 'phreg', 'lifetest', 'surveyselect',
    'mixed', 'genmod', 'nlmixed', 'glimmix', 'princomp', 'discrim', 'candisc', 'arima', 'forecast',
    'esm', 'ucm', 'timeseries', 'npar1way', 'ttest', 'nlin', 'probit', 'catmod', 'varclus',
    'dmdb', 'dmreg', 'neural', 'arboretum',
)
TIER3_STAT_PROC_PREFIXES = ('hp',)   # HPFOREST, HPLOGISTIC, HPSPLIT, ... (high-performance procs)
TIER3_PREFIX_EXCEPTIONS = frozenset({'hpsort', 'hpsummary', 'hpds2'})   # data utilities, not models

# A HASH object is Tier 3 only when mutated or iterated. A lookup-only hash
# (defineKey/defineData then find()) is a keyed JOIN -> no Tier-3 trigger.
HASH_MUTATION_MARKERS = ('.add(', '.replace(', '.remove(', '.output(', 'hiter', '.next(', '.prev(',
                         '.ref(', '.sum(')


def statement_text(content: str) -> str:
    """Lowercased SAS with comments and string literals removed, so rules match statements,
    not text inside quotes or comments."""
    s = re.sub(r'/\*[\s\S]*?\*/', ' ', content)
    s = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", s)
    s = re.sub(r'(?m)^\s*\*[^;]*;', ' ', s)
    return s.lower()

# File-level boilerplate indicators (used by the complexity scorer's discount).
BOILERPLATE_INDICATORS = (
    'etls_',
    'sas data integration studio',
    '%macro etls_',
    '%macro rcset',
    'perfinit',
    'log4sas',
    'armsubsys',
    '%macro etls_startperformancestats',
)

# Block types that are never counted as code blocks.
SKIP_TYPES = frozenset({
    BlockType.LET_STATEMENT,
    BlockType.COMMENT,
    BlockType.LIBNAME,
    BlockType.MACRO_CALL,
})


def _own_macro_name(block: SASBlock) -> str:
    m = re.search(r'%macro\s+(\w+)', block.content, re.I)
    return m.group(1).lower() if m else ''


def is_boilerplate_macro(block: SASBlock) -> bool:
    """True if a MACRO_DEF block is DI Studio / DataFlow scaffolding. Judged on the macro's own
    declared name (never a nested %macro), and an unlisted etls_* macro only when it does no work."""
    name = _own_macro_name(block)
    if name in BOILERPLATE_MACRO_NAMES:
        return True
    if not name.startswith(BOILERPLATE_MACRO_PREFIXES):
        return False
    text = statement_text(block.content)
    named_data = [d for d in re.findall(r'\bdata\s+([\w.&]+)', text) if d != '_null_']
    procs = set(re.findall(r'\bproc\s+(\w+)', text)) - TRANSPORT_PROCS
    return not named_data and not procs and 'create table' not in text


def _is_generated_housekeeping(block: SASBlock, later_blocks: List[SASBlock]) -> bool:
    """Flow-generated noise: a `data _null_` that only PUTs _FLW_ markers, or a PROC DATASETS that
    only deletes datasets a later step re-creates (CREATE OR REPLACE makes it redundant)."""
    text = statement_text(block.content)
    if block.block_type == BlockType.DATA_STEP:
        return '_flw_' in block.content.lower() and \
            bool(re.fullmatch(r'\s*data\s+_null_\s*;(\s*%?put\b[^;]*;)*\s*run\s*;\s*', text))
    if block.block_type == BlockType.PROC_DATASETS:
        m = re.fullmatch(r'\s*proc\s+datasets\b[^;]*;\s*delete\s+([^;]+);\s*(?:run|quit)\s*;\s*(?:quit\s*;\s*)?', text)
        if not m:
            return False
        later = {d.split('.')[-1].lower() for b in later_blocks for d in b.metadata.get('output_datasets', [])}
        return all(n.split('.')[-1] in later for n in m.group(1).split())
    return False


def iter_countable_blocks(script: SASScript) -> Iterator[SASBlock]:
    """Canonical countable-block set for a parsed SAS file.

    Every block count reported by the assessment (portfolio total, per-file
    count, per-tier distribution) MUST iterate this generator so the numbers
    reconcile and match how the conversion skill enumerates blocks.

    The parser surfaces each DATA/PROC step at the TOP level even when it lives
    inside a macro (its extraction regexes scan the whole file). So macros are
    already "flattened": we count those top-level steps directly and never
    descend into ``sub_blocks`` (that would double-count). We then:

    - skip non-code types (LET/COMMENT/LIBNAME/MACRO_CALL);
    - skip a MACRO_DEF wrapper when it has inner blocks (they are counted at the
      top level); count the wrapper once only for a pure macro-language macro
      with no DATA/PROC step inside;
    - exclude boilerplate macros AND every block whose line falls within a
      boilerplate macro's range (its inner steps also appear at the top level).

    See ``references/block-tiering-spec.md`` Section 1.
    """
    boilerplate_ranges = [
        (b.start_line, b.end_line)
        for b in script.blocks
        if b.block_type == BlockType.MACRO_DEF and is_boilerplate_macro(b)
    ]

    def within_boilerplate(block: SASBlock) -> bool:
        return any(lo <= block.start_line <= hi for lo, hi in boilerplate_ranges)

    for i, block in enumerate(script.blocks):
        if block.block_type in SKIP_TYPES:
            continue
        if _is_generated_housekeeping(block, script.blocks[i + 1:]):
            continue

        if block.block_type == BlockType.MACRO_DEF:
            if is_boilerplate_macro(block):
                continue
            if block.sub_blocks:
                # Inner DATA/PROC steps are already surfaced at the top level;
                # skip the wrapper to avoid double counting.
                continue
            # Pure macro-language logic (no DATA/PROC inside) counts once.
            yield block
            continue

        if within_boilerplate(block):
            # A DATA/PROC step belonging to a boilerplate macro, surfaced at the
            # top level by the parser's global extraction.
            continue

        yield block

