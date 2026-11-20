// <copyright file="ProducerWriteModes.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Linq;
using Artinsoft.Common.AST;
using Artinsoft.Common.Tools;
using Mobilize.AnsiSql.AST;
using Mobilize.Snow;
using Snowflake.SnowConvert.EtlToDbt.Dbt;
using Snowflake.SnowConvert.EtlToDbt.DbtGeneration;

/// <summary>
/// Adjusts a target's mart after the engine translated it, where the engine's class carries the
/// table and the projection but not the whole write mode.
/// </summary>
/// <remarks>
/// <para>
/// UPSERT. The engine's update-strategy target puts every non-key column in
/// <c>merge_update_columns</c> and reads <c>unique_key</c> from the stream-side key names. A Hop
/// Insert/update updates only its <c>update=Y</c> columns and matches on table columns, so both are
/// set from the IR. INSERT-ONLY (no <c>update=Y</c> column, or <c>update_bypassed=Y</c>) uses the
/// engine's <c>insert_only</c> strategy.
/// </para>
/// <para>
/// ONE ROW PER KEY. Snowflake's MERGE rejects a target row matched by two source rows, and inserts
/// both when the key is new, while the source applies its rows one at a time. The model keeps one
/// input row per key: exact when the duplicates are identical, and otherwise the row kept is the
/// first in the order of the written columns, not the source's row order (the representation has
/// none). The same rule the engine's OLE DB Command translator applies to an update.
/// </para>
/// <para>
/// SYNCHRONIZE, SCD2, COMBINATION. The engine has no strategy for these writes; the mart names a
/// producer strategy macro (<see cref="ProducerStatefulSinkMacros"/>) and carries the settings the
/// macro reads in a second <c>config()</c> call.
/// </para>
/// <para>
/// REPLACE IF ROWS. Truncate-when-the-first-row-arrives has no engine slot: a <c>table</c> rebuild
/// empties the table on a run with no rows. The mart becomes incremental with a strategy that
/// deletes the table's rows only when this run's batch is not empty, then appends the batch.
/// </para>
/// </remarks>
internal static class ProducerWriteModes
{
  internal const string ReplaceIfRowsStrategy = "replace_if_rows";

  internal const string OneRowPerKeyComment =
    "One input row per key: the write applies each key once. Rows sharing a key that differ keep "
    + "the first in the order of the written columns.";

  /// <summary>Applies <paramref name="mode"/> to the engine's mart and returns the macros it needs.</summary>
  /// <param name="query">The engine's mart query for the target.</param>
  /// <param name="mode">The target's write mode from the IR.</param>
  /// <param name="macros">Receives each strategy macro the adjusted mart needs.</param>
  /// <returns>The adjusted query.</returns>
  internal static ISqlQueryForDbt Apply(ISqlQueryForDbt query, AiFirstProducerIrHydrator.TargetWriteMode mode, ICollection<DbtMacro> macros)
  {
    if (query is not MartQueryForDbt mart)
    {
      throw new InvalidOperationException(
        $"write mode {mode.Kind} applies to a mart, and the engine returned {query.GetType().Name}");
    }

    switch (mode.Kind)
    {
      case AiFirstProducerIrHydrator.TargetWriteKind.Upsert:
        return OneRowPerKey(mart, mode) with
        {
          Metadata = mart.Metadata with
          {
            IncrementalStrategy = "merge",
            UniqueKey = mode.KeyColumns.ToArray(),
            MergeUpdateColumns = mode.UpdateColumns.ToArray(),
          },
        };

      case AiFirstProducerIrHydrator.TargetWriteKind.InsertOnly:
        macros.Add(IncrementalStrategyMacroFactory.CreateInsertOnly());
        return OneRowPerKey(mart, mode) with
        {
          Metadata = mart.Metadata with
          {
            IncrementalStrategy = "insert_only",
            UniqueKey = mode.KeyColumns.ToArray(),
            MergeUpdateColumns = null,
          },
        };

      case AiFirstProducerIrHydrator.TargetWriteKind.Synchronize:
      case AiFirstProducerIrHydrator.TargetWriteKind.Scd2:
      case AiFirstProducerIrHydrator.TargetWriteKind.Combination:
        var (strategy, macro) = ProducerStatefulSinkMacros.For(mode.Kind);
        macros.Add(macro);
        var preamble = ProducerStatefulSinkMacros.ConfigPreamble(strategy, mode.Spec!);
        return mart with
        {
          Metadata = mart.Metadata with
          {
            Materialization = DbtModelMaterialization.Incremental,
            IncrementalStrategy = strategy,
            UniqueKey = mode.KeyColumns.ToArray(),
            MergeUpdateColumns = null,
          },
          JinjaConfigPreamble = mart.JinjaConfigPreamble is { Length: > 0 } existing
            ? existing + "\n" + preamble
            : preamble,
        };

      case AiFirstProducerIrHydrator.TargetWriteKind.ReplaceIfRows:
        macros.Add(ReplaceIfRowsMacro());
        return mart with
        {
          Metadata = mart.Metadata with
          {
            Materialization = DbtModelMaterialization.Incremental,
            IncrementalStrategy = ReplaceIfRowsStrategy,
          },
        };

      default:
        throw new InvalidOperationException($"unknown write mode {mode.Kind}");
    }
  }

  /// <summary>
  /// The <c>replace_if_rows</c> incremental strategy: delete every row of the table when this
  /// run's batch has a row, then append the batch. An empty batch changes nothing.
  /// </summary>
  internal static DbtMacro ReplaceIfRowsMacro()
  {
    const string body = """

        {%- set target_relation = arg_dict["target_relation"] -%}
        {%- set temp_relation = arg_dict["temp_relation"] -%}
        {%- set dest_columns = arg_dict["dest_columns"] -%}

        {%- set cols = [] -%}
        {%- for col in dest_columns -%}
            {%- do cols.append(col.quoted) -%}
        {%- endfor -%}

        DELETE FROM {{ target_relation }}
        WHERE EXISTS (SELECT 1 FROM {{ temp_relation }});
        INSERT INTO {{ target_relation }} ({{ cols | join(", ") }})
        SELECT {{ cols | join(", ") }} FROM {{ temp_relation }}

    """;

    return new DbtMacro("get_incremental_" + ReplaceIfRowsStrategy + "_sql", ["arg_dict"], body)
    {
      Subfolder = IncrementalStrategyMacroFactory.Subfolder,
    };
  }

  private static MartQueryForDbt OneRowPerKey(MartQueryForDbt mart, AiFirstProducerIrHydrator.TargetWriteMode mode)
  {
    if (mart.SqlQueryAst is not SqlSelect select)
    {
      throw new InvalidOperationException(
        $"one-row-per-key needs the engine's SELECT, and the mart is {mart.SqlQueryAst.GetType().Name}");
    }

    var written = mart.Transformation.OutputColumns.Select(c => c.Name).ToList();
    var window = Sql.WindowFunctionExpr(
      Sql.FunctionExpr(Sql.SingleNameExpr("ROW_NUMBER")),
      Sql.WindowNameOrSpecification(Sql.WindowSpecification(
        existingWindowName: null,
        partitionClause: Sql.WindowPartitionClause(
          partitionReference: mode.KeyColumns.Select(Column).ToList()),
        orderByClause: Sql.OrderBy(written.Select(c => (SqlOrderByValue)Sql.OrderDirection(Column(c))).ToList()))));
    var qualify = Sql.Qualify(Sql.Eql(window, Sql.LiteralExpr(Sql.Literal(1))))
      .ApplyToComments(above: b => b.Add(Sql.LineComment(OneRowPerKeyComment)));

    var clauses = select.SelectBody.SelectBodyClauses.ToBuilder();
    clauses.Add(qualify);
    return mart with { SqlQueryAst = select.Copy(selectBody: select.SelectBody.Copy(selectBodyClauses: clauses.Build())) };
  }

  private static SqlEmit Sql => SqlEmit.Instance;

  private static SqlExpr Column(string name) => Sql.SingleNameExpr(Sql.IdentMultipleLines(name));
}
