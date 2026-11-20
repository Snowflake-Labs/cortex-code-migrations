# SSC-EWI-SSIS0019 — Character Map Operation Not Supported

A Character Map component becomes an `int_<component>` dbt model that applies `UPPER()` / `LOWER()` to each mapped column. SnowConvert translates only a `MapFlags` of exactly `512` (Uppercase) or `256` (Lowercase). Any other value, including a combination such as Uppercase + Full width, leaves the column unchanged and puts one marker per such column at the top of the model. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per column with an untranslated `MapFlags`) |
| Common action | Apply the operation in the model: `UPPER`/`LOWER` with `COLLATE` for casing, the UDF below for the rest |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0019 - SSIS CHARACTER MAP OPERATION 'ByteReversal' (MAPFLAGS=2048) IS NOT SUPPORTED IN SNOWFLAKE. ONLY UPPERCASE (512) AND LOWERCASE (256) OPERATIONS ARE TRANSLATED. THIS COLUMN PASSES THROUGH UNCHANGED. ***/!!!
WITH source_data AS
(
   SELECT FullName, City, Score FROM {{ ref('stg_raw__ole_db_source') }}
)
SELECT
   UPPER(FullName) AS FullName,
   City,
   Score
FROM
   source_data
```

The marker does not name the column. In the `.dtsx`, find the `componentClassID="Microsoft.CharacterMap"` component and the column whose `MapFlags` property has the marker's value: an `<inputColumn usageType="readWrite">` (changed in place), or an `<outputColumn>` with `MapFlags` and `InputColumnLineageId` (new-column mode, e.g. `Copy of City`, computed from the input column named in the lineage). `MapFlags` is a bitmask: a combined value shows as `'Unknown(<n>)'` in the marker, so split it into the flags below.

| Flag | Value | Snowflake |
|---|---|---|
| Lowercase / Uppercase | 256 / 512 | `LOWER` / `UPPER` (built-in) |
| Linguistic casing | 16777216 (always with 256 or 512) | `UPPER`/`LOWER(col COLLATE '<locale>')` (built-in) |
| Byte reversal | 2048 | **no built-in**: UDF |
| Hiragana / Katakana | 1048576 / 2097152 | **no built-in**: UDF |
| Half width / Full width | 4194304 / 8388608 | **no built-in**: UDF |
| Simplified / Traditional Chinese | 33554432 / 67108864 | **no built-in**, and no table in Snowflake: needs a mapping file |

## Fix Patterns

### Pattern 1: Linguistic casing (`16777728` = Uppercase + Linguistic, `16777472` = Lowercase + Linguistic)

Linguistic casing applies the locale's rules (Turkish `i` → `İ`). Take the locale from the component's or the Data Flow task's `LocaleID` (1055 = Turkish → `'tr'`). It matters mainly for Turkish and Azeri; for most other locales plain `UPPER`/`LOWER` gives the same result.

```sql
UPPER(City COLLATE 'tr') AS City,
```

### Pattern 2: Width, kana and byte reversal (alone or combined)

Create this UDF once (the project's setup DDL, or a dbt `on-run-start` hook) and call it with the column's `MapFlags` value. It applies the casing, width and kana flags of the mask and raises on the Chinese flags.

```sql
CREATE OR REPLACE FUNCTION util.ssis_character_map(s VARCHAR, map_flags INT)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
HANDLER = 'char_map'
AS $$
import unicodedata

_H2F = {chr(c): unicodedata.normalize('NFKC', chr(c)) for c in range(0xFF61, 0xFFA0)}  # half-width kana -> full
_F2H = {f: h for h, f in _H2F.items()}
_F2H.update({'\u309b': '\uff9e', '\u309c': '\uff9f'})  # standalone ゛ ゜

def _full(c):
    o = ord(c)
    if 0x21 <= o <= 0x7E: return chr(o + 0xFEE0)
    if c == ' ': return '\u3000'
    return _H2F.get(c, c)

def _half(c):
    o = ord(c)
    if 0xFF01 <= o <= 0xFF5E: return chr(o - 0xFEE0)
    if c == '\u3000': return ' '
    if c in _F2H: return _F2H[c]
    d = unicodedata.normalize('NFD', c)  # voiced kana: ガ -> ｶﾞ
    if len(d) == 2 and d[0] in _F2H and d[1] in _F2H: return _F2H[d[0]] + _F2H[d[1]]
    return c

def _hiragana(c):
    o = ord(c)
    return chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 or o in (0x30FD, 0x30FE) else c

def _katakana(c):
    o = ord(c)
    return chr(o + 0x60) if 0x3041 <= o <= 0x3096 or o in (0x309D, 0x309E) else c

def char_map(s, map_flags):
    if s is None:
        return None
    if map_flags & 0x6000000:
        raise ValueError('Chinese conversion needs a mapping table')
    if map_flags & 0x100: s = s.lower()
    if map_flags & 0x200: s = s.upper()
    if map_flags & 0x800000: s = unicodedata.normalize('NFC', ''.join(map(_full, s)))
    if map_flags & 0x100000: s = ''.join(map(_hiragana, s))
    if map_flags & 0x200000: s = ''.join(map(_katakana, s))
    if map_flags & 0x400000: s = ''.join(map(_half, s))
    if map_flags & 0x800: s = s.encode('utf-16-le').decode('utf-16-be', 'surrogatepass')
    return s
$$;
```

```sql
-- Before: City passes through (Katakana + Half width = 6291456)
   City,
-- After
   util.ssis_character_map(City, 6291456) AS City,
-- New-column mode: the passthrough names the new column, which source_data does not have
   util.ssis_character_map(City, 6291456) AS "Copy of City",
```

Width covers ASCII `!`–`~`, the space (↔ U+3000) and the half-width katakana block. Other full-width symbols (`￥`, `￠`) are left as they are. Byte reversal swaps the two bytes of each UTF-16 code unit (`A` U+0041 → U+4100). A character whose low byte is `D8`–`DF` turns into a lone surrogate that Snowflake cannot store, so the call fails. If the result only fed a binary or hashing step, ask what it is for.

### Pattern 3: Simplified / Traditional Chinese

Windows uses its own character table. Snowflake has no such table and no built-in for this. Stage a character mapping file (for example OpenCC's `TSCharacters.txt` for Traditional → Simplified or `STCharacters.txt` for the reverse), give it to a Python UDF with `IMPORTS = ('@<stage>/TSCharacters.txt')`, and read it from `sys._xoptions['snowflake_import_directory']` into a `dict` of first variants. Which file is acceptable is the user's call. Write `-- NEEDS-USER: provide a Traditional/Simplified character mapping file` and mark as needs-user. One-to-many characters (`发` → `發`/`髮`) can differ from SSIS.

## Key Points

- **Must** remove each `!!!RESOLVE EWI!!!` marker once its column is fixed.
- Keep the column's alias and position. Downstream models and the destination use the SSIS column name.
- Snowflake `UPPER('ß')` is `'SS'` (Windows keeps `ß`). Width and kana conversions can change the length too. Check the destination column's length.
- A Character Map in new-column mode with Uppercase or Lowercase is translated (`UPPER(FullName) AS "Copy of FullName"`). See [SSC-EWI-SSIS0045](SSC-EWI-SSIS0045.md).
