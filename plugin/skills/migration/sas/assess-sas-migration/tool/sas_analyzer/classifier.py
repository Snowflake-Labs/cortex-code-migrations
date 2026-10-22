import re
from typing import Dict
from .parser import SASScript, SASBlock, BlockType
from .constants import (iter_countable_blocks, statement_text, HASH_MUTATION_MARKERS,
                        TIER3_STAT_PROCS, TIER3_STAT_PROC_PREFIXES, TIER3_PREFIX_EXCEPTIONS)


class TierClassifier:

    # Canonical list lives in constants.py (TIER3_STAT_PROCS); kept here as an alias for callers.
    TIER3_STAT_PROCS = [f'proc {p}' for p in TIER3_STAT_PROCS]

    # External DB engines -> LOW confidence. Canonical union list.
    EXTERNAL_ENGINES = [
        'sqlsvr', 'mssql', 'sql server', 'oracle', 'teradata',
        'odbc', 'oledb', 'db2', 'postgres', 'mysql', 'dsn=',
    ]

    # PROCs without a dedicated BlockType that are nonetheless well understood:
    # housekeeping (no data logic) or a direct SQL mapping (RANK -> RANK()).
    KNOWN_OTHER_PROCS = frozenset({
        'DELETE', 'PRINTTO', 'OPTIONS', 'OPTSAVE', 'OPTLOAD', 'CATALOG', 'PWENCODE', 'RANK',
    })

    def classify_block(self, block: SASBlock) -> Dict:
        content_lower = statement_text(block.content)

        if re.search(r'\bdeclare\s+hash\b', content_lower):
            marker = next((m for m in HASH_MUTATION_MARKERS if m in content_lower), None)
            if marker:
                return {'tier': 3, 'label': 'TIER_3_PYSPARK',
                        'reason': f'HASH object mutated/iterated ({marker}) - no SQL equivalent', 'confidence': 'HIGH'}
            # lookup-only hash = keyed JOIN; fall through to the remaining rules

        if re.search(r'\bdo\s+(until|while)\b', content_lower):
            # CALL EXECUTE is not external state (it is Tier 2 below); don't count it.
            other_calls = len(re.findall(r'\bcall\s+(?!execute\b)\w', content_lower))
            if 'symput' in content_lower or other_calls > 2:
                return {'tier': 3, 'label': 'TIER_3_PYSPARK', 'reason': 'DO loop with external state', 'confidence': 'HIGH'}

        for proc in re.findall(r'\bproc\s+(\w+)', content_lower):
            if proc in TIER3_STAT_PROCS or (proc.startswith(TIER3_STAT_PROC_PREFIXES) and proc not in TIER3_PREFIX_EXCEPTIONS):
                return {'tier': 3, 'label': 'TIER_3_PYSPARK', 'reason': f'Statistical modeling: proc {proc}', 'confidence': 'HIGH'}

        # CALL EXECUTE is dynamic dispatch, not something SQL cannot express:
        # both conversions rebuilt it as a procedure. HASH / stat PROCs in the
        # same block still win above. See block-tiering-spec.md.
        if re.search(r'\bcall\s+execute\b', content_lower):
            return {'tier': 2, 'label': 'TIER_2_SP',
                    'reason': 'CALL EXECUTE - dynamic dispatch -> stored procedure with EXECUTE IMMEDIATE / cursor loop',
                    'confidence': 'MEDIUM'}

        outputs = len(re.findall(r'\boutput\s+\w', content_lower))
        if re.search(r'\bretain\b', content_lower) and 'first.' in content_lower:
            if '= 0' in content_lower or '= .' in content_lower:
                return {'tier': 2, 'label': 'TIER_2_SP', 'reason': 'RETAIN with conditional reset', 'confidence': 'HIGH'}

        if ('first.' in content_lower or 'last.' in content_lower):
            if outputs > 1:
                return {'tier': 2, 'label': 'TIER_2_SP', 'reason': 'FIRST./LAST. with multiple OUTPUT', 'confidence': 'HIGH'}

        if outputs > 1 and not re.search(r'\boutput\s*;', content_lower):
            return {'tier': 2, 'label': 'TIER_2_SP', 'reason': 'Multiple OUTPUT datasets', 'confidence': 'MEDIUM'}

        # Procedural IF/THEN/ELSE and SELECT/WHEN branching only exists in DATA
        # steps. A PROC SQL CASE WHEN is pure SQL (Tier 1) no matter how many
        # WHEN clauses, so gate this rule to DATA steps. See block-tiering-spec.md.
        if block.block_type == BlockType.DATA_STEP and (
                len(re.findall(r'(?<![%\w])if\b', content_lower)) > 5 or
                len(re.findall(r'(?<![%\w])when\b', content_lower)) > 5):
            return {'tier': 2, 'label': 'TIER_2_SP', 'reason': 'Complex branching (>5 IF/WHEN) in DATA step', 'confidence': 'MEDIUM'}

        dml_count = sum(1 for kw in ('delete', 'insert', 'update') if re.search(rf'\b{kw}\b', content_lower))
        if dml_count >= 3:
            return {'tier': 2, 'label': 'TIER_2_SP', 'reason': '3+ sequential DML operations', 'confidence': 'MEDIUM'}

        confidence = self._assess_confidence(content_lower)
        if block.block_type == BlockType.PROC_OTHER and self.proc_name(block) not in self.KNOWN_OTHER_PROCS:
            # A PROC we have no rule for: do not claim it is plain SQL with HIGH
            # confidence. Flagged in portfolio_summary.unrecognised_procs.
            return {'tier': 1, 'label': 'TIER_1_SQL',
                    'reason': f'Unrecognised PROC {self.proc_name(block)} - review manually', 'confidence': 'LOW'}
        return {'tier': 1, 'label': 'TIER_1_SQL', 'reason': 'SQL-translatable', 'confidence': confidence}

    @staticmethod
    def proc_name(block: SASBlock) -> str:
        m = re.match(r'(?is)\s*proc\s+(\w+)', block.content)
        return m.group(1).upper() if m else 'UNKNOWN'

    def _assess_confidence(self, content_lower: str) -> str:
        if content_lower.count('%macro') > 2:
            return 'LOW'
        if '%include' in content_lower and '&' in content_lower:
            return 'LOW'
        if any(eng in content_lower for eng in self.EXTERNAL_ENGINES):
            return 'LOW'
        if 'intck' in content_lower or 'intnx' in content_lower or 'datepart' in content_lower:
            return 'MEDIUM'
        if 'notsorted' in content_lower:
            return 'MEDIUM'
        return 'HIGH'

    def classify_file(self, script: SASScript) -> Dict:
        block_classifications = []
        tier_counts = {1: 0, 2: 0, 3: 0}
        confidence_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}

        for block in iter_countable_blocks(script):
            classification = self.classify_block(block)
            block_classifications.append({
                'block_type': block.block_type.value,
                'start_line': block.start_line,
                'end_line': block.end_line,
                **classification
            })
            tier_counts[classification['tier']] += 1
            confidence_counts[classification['confidence']] += 1

        # Strict "any-block" rule: the file's tier is driven by its most demanding
        # block, matching the conversion skill (one Tier-3 block -> notebook).
        # See references/block-tiering-spec.md Section 3.
        if tier_counts[3] > 0:
            primary_tier = 'TIER_3_PYSPARK'
        elif tier_counts[2] > 0:
            primary_tier = 'TIER_2_SP'
        else:
            primary_tier = 'TIER_1_SQL'

        if confidence_counts['LOW'] > 0:
            overall_confidence = 'LOW'
        elif confidence_counts['MEDIUM'] > 0:
            overall_confidence = 'MEDIUM'
        else:
            overall_confidence = 'HIGH'

        return {
            'primary_tier': primary_tier,
            'confidence': overall_confidence,
            'tier_distribution': {
                'TIER_1_SQL': tier_counts[1],
                'TIER_2_SP': tier_counts[2],
                'TIER_3_PYSPARK': tier_counts[3],
            },
            'block_classifications': block_classifications,
        }
