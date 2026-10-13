"""Guard: no identifier from a private test corpus may appear in the SAS skill track.

Examples in skills must be neutral (`orders`, `price_band`, `<SOURCE_DB>`). Identifiers seen while
testing against real codebases are listed only as SHA-256 prefixes, so this file does not leak
them either. To add one: sha256(lowercase identifier).hexdigest()[:16].
"""

import hashlib
import re
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[3]          # .../skills/migration/sas
BLOCKED = frozenset({
    'ec7053274de4c2f5', '5f9504600be67856', '7a6eb98987c34c47', '68a3b03b737000e7',
    'af87c0a091455a74', '84ac7f4fb28a497d', 'ed0607dc6b9c1f62', '6f5d799dc2051d67',
    '6dbce0f0f78807b1', '9866b1ca25bc2af5', 'f096eb5e9db3212a', 'f57ffd9bd756b56c',
    '2218dd73e2f689e1', '83928f94c22b793c', '71a00a351a26c8a9', '3ca4ef2360ad87af',
    '105b02681f3c11d7', '483c8296305edc2e', '7b5fe2362816f017', 'd1a3e632076863ce',
    '73f35bdc42c90e41', '1f6429a36a44199d',
})
SUFFIXES = {'.md', '.py', '.json', '.txt', '.yml', '.yaml'}


def _hash(word):
    return hashlib.sha256(word.encode()).hexdigest()[:16]


class CorpusIdentifierGuard(unittest.TestCase):
    def test_no_private_corpus_identifiers(self):
        hits = []
        for p in TRACK.rglob('*'):
            if p.suffix not in SUFFIXES or '__pycache__' in p.parts or p.name == Path(__file__).name:
                continue
            text = p.read_text(encoding='utf-8', errors='replace').lower()
            for word in set(re.findall(r'[a-z_][a-z0-9_]{3,}', text)):
                if _hash(word) in BLOCKED:
                    hits.append(f'{p.relative_to(TRACK)}: {word}')
        self.assertEqual(hits, [], 'replace with neutral examples:\n' + '\n'.join(sorted(hits)))


if __name__ == '__main__':
    unittest.main()
