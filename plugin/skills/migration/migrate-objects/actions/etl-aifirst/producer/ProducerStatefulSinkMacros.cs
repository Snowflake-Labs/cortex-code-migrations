// <copyright file="ProducerStatefulSinkMacros.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Linq;
using Snowflake.SnowConvert.EtlToDbt.Dbt;

/// <summary>
/// The incremental strategies for Hop writes the engine has no strategy for: hop_synchronize
/// (Synchronize after merge), hop_scd2 (Dimension lookup/update) and hop_combination (Combination
/// lookup/update). Each reads its settings from the model's config under its own name.
/// </summary>
/// <remarks>
/// <para>
/// ROW ORDER. Hop applies rows one at a time in stream order, and a relation has none. Where the
/// order changes the result -- rows sharing a key in one batch, and the order technical keys are
/// handed out in -- the strategies use: occurrence within the key, by the stream date when there is
/// one and then by the tracked columns' values; then the key columns. Equal to Hop's when each key's
/// rows arrive in that order and new keys arrive in key order.
/// </para>
/// <para>
/// CLOCK. "Now" is dbt's <c>run_started_at</c> (UTC), one value for the whole run, where Hop takes
/// the pipeline start in the JVM's zone (validity dates) or the wall clock (audit dates). Those
/// columns are listed as <c>clock_columns</c> in the settings and in the unit's clock-column
/// manifest, which the test seed excludes from the comparison.
/// </para>
/// <para>
/// The statements run one after another, not in one transaction.
/// </para>
/// </remarks>
internal static class ProducerStatefulSinkMacros
{
  internal const string SynchronizeStrategy = "hop_synchronize";

  internal const string Scd2Strategy = "hop_scd2";

  internal const string CombinationStrategy = "hop_combination";

  /// <summary>The strategy name and its macro for a stateful write kind.</summary>
  internal static (string Strategy, DbtMacro Macro) For(AiFirstProducerIrHydrator.TargetWriteKind kind)
    => kind switch
    {
      AiFirstProducerIrHydrator.TargetWriteKind.Synchronize => (SynchronizeStrategy, Macro(SynchronizeStrategy, SynchronizeBody)),
      AiFirstProducerIrHydrator.TargetWriteKind.Scd2 => (Scd2Strategy, Macro(Scd2Strategy, Scd2Body)),
      AiFirstProducerIrHydrator.TargetWriteKind.Combination => (CombinationStrategy, Macro(CombinationStrategy, CombinationBody)),
      _ => throw new InvalidOperationException($"{kind} has no producer strategy"),
    };

  /// <summary>The <c>{{ config(&lt;strategy&gt;={...}) }}</c> call that carries the settings.</summary>
  internal static string ConfigPreamble(string strategy, IReadOnlyDictionary<string, object?> spec)
    => "{{ config(" + strategy + "={" + string.Join(", ", spec.Select(kv => $"'{kv.Key}': {Jinja(kv.Value)}")) + "}) }}";

  private static string Jinja(object? value) => value switch
  {
    null => "none",
    bool b => b ? "true" : "false",
    string s => "'" + s.Replace("\\", "\\\\", StringComparison.Ordinal).Replace("'", "\\'", StringComparison.Ordinal) + "'",
    IEnumerable<string> list => "[" + string.Join(", ", list.Select(Jinja)) + "]",
    _ => throw new InvalidOperationException($"no Jinja literal for {value.GetType().Name}"),
  };

  private static DbtMacro Macro(string strategy, string body)
    => new("get_incremental_" + strategy + "_sql", ["arg_dict"], body)
    {
      Subfolder = IncrementalStrategyMacroFactory.Subfolder,
    };

  // Per row, the operation field picks the statement: DELETE and UPDATE match on every key, INSERT
  // writes every <value> column. A value mapped to no operation (Merge rows' 'identical') does nothing.
  private const string SynchronizeBody = """

        {%- set spec = config.get('hop_synchronize') -%}
        {%- set target_relation = arg_dict["target_relation"] -%}
        {%- set temp_relation = arg_dict["temp_relation"] -%}
        {%- set keys = spec['keys'] -%}
        {%- set op = spec['operation_field'] -%}
        {%- set key_match = [] -%}
        {%- for k in keys -%}{%- do key_match.append('t.' ~ k ~ ' = s.' ~ k) -%}{%- endfor -%}
        {%- if spec['delete_value'] is not none %}
        DELETE FROM {{ target_relation }} AS t
        USING (
            SELECT DISTINCT {{ keys | join(', ') }}
            FROM {{ temp_relation }}
            WHERE {{ op }} = '{{ spec['delete_value'] | replace("'", "''") }}'
        ) AS s
        WHERE {{ key_match | join(' AND ') }};
        {%- endif %}
        {%- if spec['update_value'] is not none and spec['update_columns'] %}
        UPDATE {{ target_relation }} AS t
        SET {% for c in spec['update_columns'] %}{{ c }} = s.{{ c }}{% if not loop.last %}, {% endif %}{% endfor %}
        FROM (
            SELECT {{ (keys + spec['update_columns']) | join(', ') }}
            FROM {{ temp_relation }}
            WHERE {{ op }} = '{{ spec['update_value'] | replace("'", "''") }}'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY {{ keys | join(', ') }} ORDER BY {{ spec['update_columns'] | join(', ') }}) = 1
        ) AS s
        WHERE {{ key_match | join(' AND ') }};
        {%- endif %}
        {%- if spec['insert_value'] is not none %}
        INSERT INTO {{ target_relation }} ({{ spec['columns'] | join(', ') }})
        SELECT {{ spec['columns'] | join(', ') }}
        FROM {{ temp_relation }}
        WHERE {{ op }} = '{{ spec['insert_value'] | replace("'", "''") }}';
        {%- endif %}
        SELECT 1

    """;

  // Insert each combination of the key columns not in the table (null matches null, as Hop's
  // lookup does), with a technical key: tablemax = MAX + 1 in order, sequence = NEXTVAL in order.
  private const string CombinationBody = """

        {%- set spec = config.get('hop_combination') -%}
        {%- set target_relation = arg_dict["target_relation"] -%}
        {%- set temp_relation = arg_dict["temp_relation"] -%}
        {%- set new_rel = make_temp_relation(target_relation, '__hop_new') -%}
        {%- set keys_rel = make_temp_relation(target_relation, '__hop_keys') -%}
        {%- set keys = spec['keys'] -%}
        {%- set tk = spec['technical_key'] -%}
        {%- set run_ts = "'" ~ run_started_at.strftime('%Y-%m-%d %H:%M:%S.%f') ~ "'::TIMESTAMP_NTZ" -%}
        {%- set missing = [] -%}
        {%- for k in keys -%}{%- do missing.append('EQUAL_NULL(t.' ~ k ~ ', s.' ~ k ~ ')') -%}{%- endfor %}
        CREATE OR REPLACE TEMPORARY TABLE {{ new_rel }} AS
        SELECT s.*, ROW_NUMBER() OVER (ORDER BY {{ keys | join(', ') }}) AS hop_rn__
        FROM (SELECT DISTINCT {{ keys | join(', ') }} FROM {{ temp_relation }}) AS s
        WHERE NOT EXISTS (SELECT 1 FROM {{ target_relation }} AS t WHERE {{ missing | join(' AND ') }});
        {%- if spec['key_creation'] == 'sequence' %}
        CREATE OR REPLACE TEMPORARY TABLE {{ keys_rel }} AS
        SELECT {{ target_relation.database }}.{{ target_relation.schema }}.{{ spec['sequence'] }}.NEXTVAL AS hop_tk__
        FROM {{ new_rel }};
        {%- endif %}
        INSERT INTO {{ target_relation }} ({{ tk }}, {{ keys | join(', ') }}{% if spec['last_update_column'] %}, {{ spec['last_update_column'] }}{% endif %})
        SELECT
            {%- if spec['key_creation'] == 'sequence' %} k.hop_tk__,
            {%- else %} (SELECT COALESCE(MAX({{ tk }}), 0) FROM {{ target_relation }}) + n.hop_rn__,
            {%- endif %}
            {% for k in keys %}n.{{ k }}{% if not loop.last %}, {% endif %}{% endfor %}
            {%- if spec['last_update_column'] %}, {{ run_ts }}{% endif %}
        FROM {{ new_rel }} AS n
        {%- if spec['key_creation'] == 'sequence' %}
        JOIN (SELECT hop_tk__, ROW_NUMBER() OVER (ORDER BY hop_tk__) AS hop_rn__ FROM {{ keys_rel }}) AS k
          ON k.hop_rn__ = n.hop_rn__
        {%- endif %};
        SELECT 1

    """;

  // Dimension lookup/update, update=Y: each row in order compares with the state before it, so a
  // changed Insert column opens a version, a changed Update column overwrites the current one and a
  // changed Punch through column overwrites every version, as Hop's row-at-a-time walk does.
  private const string Scd2Body = """

        {%- set spec = config.get('hop_scd2') -%}
        {%- set target_relation = arg_dict["target_relation"] -%}
        {%- set temp_relation = arg_dict["temp_relation"] -%}
        {%- set rows_rel = make_temp_relation(target_relation, '__hop_rows') -%}
        {%- set act_rel = make_temp_relation(target_relation, '__hop_act') -%}
        {%- set seg_rel = make_temp_relation(target_relation, '__hop_seg') -%}
        {%- set keys_rel = make_temp_relation(target_relation, '__hop_keys') -%}
        {%- set keys = spec['keys'] -%}
        {%- set tracked = spec['insert_columns'] + spec['update_columns'] + spec['punch_columns'] -%}
        {%- set tk = spec['technical_key'] -%}
        {%- set version = spec['version'] -%}
        {%- set date_from = spec['date_from'] -%}
        {%- set date_to = spec['date_to'] -%}
        {%- set alt = spec['start_date_alternative'] -%}
        {%- set run_ts = "'" ~ run_started_at.strftime('%Y-%m-%d %H:%M:%S.%f') ~ "'::TIMESTAMP_NTZ" -%}
        {%- set min_date = "'" ~ spec['min_date'] ~ "'::TIMESTAMP_NTZ" -%}
        {%- set max_date = "'" ~ spec['max_date'] ~ "'::TIMESTAMP_NTZ" -%}
        {%- set vdate = ('CAST(b.' ~ spec['stream_date'] ~ ' AS TIMESTAMP_NTZ)') if spec['stream_date'] else run_ts -%}
        {%- set touched = spec['date_inserted_updated_columns'] + spec['date_updated_columns'] -%}
        {%- set inserted = spec['date_inserted_updated_columns'] + spec['date_inserted_columns'] -%}
        {%- set rk = [] -%}{%- set ck = [] -%}{%- set fk = [] -%}{%- set nk = [] -%}{%- set on_cur = [] -%}{%- set on_t = [] -%}
        {%- for k in keys -%}
          {%- do rk.append('r.' ~ k) -%}{%- do fk.append('f.' ~ k) -%}{%- do nk.append('n.' ~ k) -%}
          {%- do on_cur.append('c.' ~ k ~ ' = r.' ~ k) -%}{%- do on_t.append('t.' ~ k ~ ' = s.' ~ k) -%}
        {%- endfor -%}
        {%- set ins_changed = [] -%}{%- set any_changed = [] -%}{%- set punch_changed = [] -%}
        {%- for c in spec['insert_columns'] -%}{%- do ins_changed.append('NOT EQUAL_NULL(p.' ~ c ~ ', p.hop_prev_' ~ c ~ ')') -%}{%- endfor -%}
        {%- for c in tracked -%}{%- do any_changed.append('NOT EQUAL_NULL(p.' ~ c ~ ', p.hop_prev_' ~ c ~ ')') -%}{%- endfor -%}
        {%- for c in spec['punch_columns'] -%}{%- do punch_changed.append('NOT EQUAL_NULL(p.' ~ c ~ ', p.hop_prev_' ~ c ~ ')') -%}{%- endfor -%}
        {%- set order_in_key = ((['b.' ~ spec['stream_date']] if spec['stream_date'] else []) + (tracked if tracked else keys)) | join(', ') -%}
        {%- set new_key_from = min_date if alt == 'none' else (run_ts if alt == 'pipeline_start' else 'n.hop_start_vdate__') -%}
        {%- set new_version_from = run_ts if alt == 'pipeline_start' else 'n.hop_start_vdate__' -%}
        {%- set close_next = 'n.hop_next_vdate__' if alt == 'none' else run_ts -%}
        {%- set close_current = 's.hop_close_vdate__' if alt == 'none' else run_ts -%}
        {%- if spec['unknown_row'] %}
        INSERT INTO {{ target_relation }} ({{ tk }}, {{ version }})
        SELECT {{ spec['not_found_key'] }}, 1
        WHERE EXISTS (SELECT 1 FROM {{ temp_relation }})
          AND NOT EXISTS (SELECT 1 FROM {{ target_relation }} WHERE {{ tk }} = {{ spec['not_found_key'] }});
        {%- endif %}
        CREATE OR REPLACE TEMPORARY TABLE {{ rows_rel }} AS
        SELECT b.*, {{ vdate }} AS hop_vdate__,
            ROW_NUMBER() OVER (PARTITION BY {{ keys | join(', ') }} ORDER BY {{ order_in_key }}) AS hop_seq__
        FROM {{ temp_relation }} AS b;
        CREATE OR REPLACE TEMPORARY TABLE {{ act_rel }} AS
        WITH cur AS (
            SELECT {{ fk | join(', ') }}, d.{{ tk }} AS hop_cur_tk__, d.{{ version }} AS hop_cur_version__
                {%- for c in tracked %}, d.{{ c }} AS hop_cur_{{ c }}{% endfor %}
            FROM {{ rows_rel }} AS f
            JOIN {{ target_relation }} AS d
              ON {% for k in keys %}d.{{ k }} = f.{{ k }} AND {% endfor %}f.hop_vdate__ >= d.{{ date_from }} AND f.hop_vdate__ < d.{{ date_to }}
            WHERE f.hop_seq__ = 1
            QUALIFY ROW_NUMBER() OVER (PARTITION BY {{ fk | join(', ') }} ORDER BY d.{{ version }} DESC) = 1
        ),
        prev AS (
            SELECT r.*, c.hop_cur_tk__, c.hop_cur_version__
                {%- for c in tracked %},
                IFF(r.hop_seq__ = 1, c.hop_cur_{{ c }}, LAG(r.{{ c }}) OVER (PARTITION BY {{ rk | join(', ') }} ORDER BY r.hop_seq__)) AS hop_prev_{{ c }}
                {%- endfor %}
            FROM {{ rows_rel }} AS r
            LEFT JOIN cur AS c ON {{ on_cur | join(' AND ') }}
        ),
        classified AS (
            SELECT p.*,
                CASE
                    WHEN p.hop_seq__ = 1 AND p.hop_cur_tk__ IS NULL THEN 'new_key'
                    {%- if ins_changed %}
                    WHEN {{ ins_changed | join(' OR ') }} THEN 'new_version'
                    {%- endif %}
                    {%- if any_changed %}
                    WHEN {{ any_changed | join(' OR ') }} THEN 'update'
                    {%- endif %}
                    ELSE 'none'
                END AS hop_action__,
                {%- if punch_changed %}
                (p.hop_cur_tk__ IS NOT NULL OR p.hop_seq__ > 1) AND ({{ punch_changed | join(' OR ') }}) AS hop_punch__
                {%- else %}
                FALSE AS hop_punch__
                {%- endif %}
            FROM prev AS p
        )
        SELECT x.*,
            SUM(IFF(x.hop_action__ IN ('new_key', 'new_version'), 1, 0))
                OVER (PARTITION BY {% for k in keys %}x.{{ k }}{% if not loop.last %}, {% endif %}{% endfor %} ORDER BY x.hop_seq__ ROWS UNBOUNDED PRECEDING) AS hop_seg__
        FROM classified AS x;
        CREATE OR REPLACE TEMPORARY TABLE {{ seg_rel }} AS
        WITH segs AS (
            SELECT {{ keys | join(', ') }}, hop_seg__,
                MIN(hop_seq__) AS hop_start_seq__,
                MIN_BY(hop_action__, hop_seq__) AS hop_start_action__,
                MIN_BY(hop_vdate__, hop_seq__) AS hop_start_vdate__,
                BOOLOR_AGG(hop_action__ = 'update') AS hop_updated__,
                MAX(IFF(hop_action__ = 'update', hop_vdate__, NULL)) AS hop_update_vdate__,
                {%- if spec['technical_key_field'] %}
                MIN_BY({{ spec['technical_key_field'] }}, hop_seq__) AS hop_tk_field__,
                {%- endif %}
                {%- for c in tracked %}
                MAX_BY({{ c }}, hop_seq__) AS {{ c }},
                {%- endfor %}
                ANY_VALUE(hop_cur_tk__) AS hop_cur_tk__,
                ANY_VALUE(hop_cur_version__) AS hop_cur_version__
            FROM {{ act_rel }}
            GROUP BY {{ keys | join(', ') }}, hop_seg__
        )
        SELECT s.*,
            LEAD(s.hop_start_vdate__) OVER (PARTITION BY {% for k in keys %}s.{{ k }}{% if not loop.last %}, {% endif %}{% endfor %} ORDER BY s.hop_seg__) AS hop_next_vdate__,
            MAX(s.hop_seg__) OVER (PARTITION BY {% for k in keys %}s.{{ k }}{% if not loop.last %}, {% endif %}{% endfor %}) AS hop_last_seg__
        FROM segs AS s;
        UPDATE {{ target_relation }} AS t
        SET {{ date_to }} = IFF(s.hop_has_new__, {{ close_current }}, t.{{ date_to }})
            {%- for c in tracked %},
            {{ c }} = IFF(s.hop_updated__, s.{{ c }}, t.{{ c }})
            {%- endfor %}
            {%- for c in touched %},
            {{ c }} = IFF(s.hop_has_new__, {{ run_ts }}, IFF(s.hop_updated__, s.hop_update_vdate__, t.{{ c }}))
            {%- endfor %}
            {%- for c in spec['last_version_columns'] %},
            {{ c }} = IFF(s.hop_has_new__, FALSE, t.{{ c }})
            {%- endfor %}
        FROM (
            SELECT hop_cur_tk__,
                MAX(hop_seg__) >= 1 AS hop_has_new__,
                MAX(IFF(hop_seg__ = 1, hop_start_vdate__, NULL)) AS hop_close_vdate__,
                COALESCE(BOOLOR_AGG(IFF(hop_seg__ = 0, hop_updated__, NULL)), FALSE) AS hop_updated__,
                MAX(IFF(hop_seg__ = 0, hop_update_vdate__, NULL)) AS hop_update_vdate__
                {%- for c in tracked %},
                MAX(IFF(hop_seg__ = 0, {{ c }}, NULL)) AS {{ c }}
                {%- endfor %}
            FROM {{ seg_rel }}
            WHERE hop_cur_tk__ IS NOT NULL
            GROUP BY hop_cur_tk__
        ) AS s
        WHERE t.{{ tk }} = s.hop_cur_tk__ AND (s.hop_has_new__ OR s.hop_updated__);
        {%- if spec['key_creation'] == 'sequence' %}
        CREATE OR REPLACE TEMPORARY TABLE {{ keys_rel }} AS
        SELECT {{ target_relation.database }}.{{ target_relation.schema }}.{{ spec['sequence'] }}.NEXTVAL AS hop_tk__
        FROM {{ seg_rel }}
        WHERE hop_seg__ >= 1;
        {%- endif %}
        INSERT INTO {{ target_relation }} ({{ tk }}, {{ version }}, {{ date_from }}, {{ date_to }}, {{ keys | join(', ') }}
            {%- for c in tracked + inserted + spec['date_updated_columns'] + spec['last_version_columns'] %}, {{ c }}{% endfor %})
        SELECT
            {%- if spec['key_creation'] == 'sequence' %} k.hop_tk__,
            {%- elif spec['key_creation'] == 'uuid' %} UUID_STRING(),
            {%- elif spec['key_creation'] == 'field' %} n.hop_tk_field__,
            {%- else %} (SELECT COALESCE(MAX({{ tk }}), 0) FROM {{ target_relation }}) + n.hop_tk_rn__,
            {%- endif %}
            COALESCE(n.hop_cur_version__, 0) + n.hop_seg__,
            IFF(n.hop_start_action__ = 'new_key', {{ new_key_from }}, {{ new_version_from }}),
            IFF(n.hop_seg__ < n.hop_last_seg__, {{ close_next }}, {{ max_date }}),
            {{ nk | join(', ') }}
            {%- for c in tracked %}, n.{{ c }}{% endfor %}
            {%- for c in inserted %}, {{ run_ts }}{% endfor %}
            {%- for c in spec['date_updated_columns'] %}, IFF(n.hop_seg__ < n.hop_last_seg__, {{ run_ts }}, NULL){% endfor %}
            {%- for c in spec['last_version_columns'] %}, n.hop_seg__ = n.hop_last_seg__{% endfor %}
        FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY hop_start_seq__, {{ keys | join(', ') }}) AS hop_tk_rn__
            FROM {{ seg_rel }}
            WHERE hop_seg__ >= 1
        ) AS n
        {%- if spec['key_creation'] == 'sequence' %}
        JOIN (SELECT hop_tk__, ROW_NUMBER() OVER (ORDER BY hop_tk__) AS hop_tk_rn__ FROM {{ keys_rel }}) AS k
          ON k.hop_tk_rn__ = n.hop_tk_rn__
        {%- endif %};
        {%- if spec['punch_columns'] %}
        UPDATE {{ target_relation }} AS t
        SET {% for c in spec['punch_columns'] %}{{ c }} = s.{{ c }}{% if not loop.last %}, {% endif %}{% endfor %}
            {%- for c in touched %}, {{ c }} = {{ run_ts }}{% endfor %}
        FROM (
            SELECT {{ keys | join(', ') }}
                {%- for c in spec['punch_columns'] %}, MAX_BY({{ c }}, hop_seq__) AS {{ c }}{% endfor %}
            FROM {{ act_rel }}
            GROUP BY {{ keys | join(', ') }}
            HAVING BOOLOR_AGG(hop_punch__)
        ) AS s
        WHERE {{ on_t | join(' AND ') }};
        {%- endif %}
        SELECT 1

    """;
}
