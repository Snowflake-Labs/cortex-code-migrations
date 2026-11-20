// <copyright file="HopMergeRowsDiff.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Mobilize.AnsiSql.AST;
using Mobilize.Snow;
using Snowflake.SnowConvert.EtlToDbt.DbtGeneration;
using Snowflake.SnowConvert.EtlToDbt.DbtGeneration.Translations;
using Snowflake.SnowConvert.EtlToDbt.Models;

/// <summary>
/// Hop Merge rows (diff): one row per key of a reference and a compare stream, flagged identical /
/// changed / new / deleted. The engine has no element for it.
/// </summary>
internal sealed class HopMergeRowsDiffTransformation : Transformation
{
  /// <summary>Gets the fields both streams are matched on.</summary>
  public IReadOnlyList<string> KeyFields { get; init; } = [];

  /// <summary>Gets the fields whose difference makes a matched row 'changed'.</summary>
  public IReadOnlyList<string> ValueFields { get; init; } = [];

  /// <summary>Gets the output field that carries the flag.</summary>
  public string FlagField { get; init; } = string.Empty;

  /// <summary>Gets the name of the transform whose rows are the reference (old) stream.</summary>
  public string ReferenceTransform { get; init; } = string.Empty;

  /// <summary>Gets the name of the transform whose rows are the compare (new) stream.</summary>
  public string CompareTransform { get; init; } = string.Empty;
}

/// <summary>
/// Writes Merge rows (diff) as a FULL OUTER JOIN of the two streams on the key fields.
/// </summary>
/// <remarks>
/// Hop walks both inputs sorted on the keys and emits, per key: the compare row flagged 'new' when
/// only the compare stream has it, the reference row flagged 'deleted' when only the reference
/// stream has it, and the compare row flagged 'identical' or 'changed' when both do, by the value
/// fields. Hop's comparison treats two nulls as equal, so the join and the value test use
/// EQUAL_NULL. The join does not depend on input order; a key repeated inside one stream (which Hop
/// pairs positionally) yields every pairing instead.
/// </remarks>
internal sealed class HopMergeRowsDiffTranslator : IEtlIrElementToDbtArtifactTranslator
{
  internal const string ReferencePresent = "hop_in_reference__";

  internal const string ComparePresent = "hop_in_compare__";

  /// <inheritdoc/>
  public string TypeNameToApplyTo => typeof(HopMergeRowsDiffTransformation).FullName!;

  /// <inheritdoc/>
  public ITranslationResult[] Translate(Transformation transformation, IEtlIrToDbtContext ctx)
  {
    var merge = (HopMergeRowsDiffTransformation)transformation;
    var incoming = ctx.GetIncomingEntities(merge);
    var reference = Input(incoming, merge.ReferenceTransform, "reference");
    var compare = Input(incoming, merge.CompareTransform, "compare");

    var columns = merge.OutputColumns
      .Select(c => c.Name)
      .Where(n => !string.Equals(n, merge.FlagField, StringComparison.OrdinalIgnoreCase))
      .ToList();

    var sql = new StringBuilder();
    sql.AppendLine("WITH reference_rows AS (");
    sql.AppendLine($"    SELECT *, TRUE AS {ReferencePresent} FROM {{{{ ref('{ctx.GetFormattedSourceModelName(reference, merge)}') }}}}");
    sql.AppendLine("),");
    sql.AppendLine("compare_rows AS (");
    sql.AppendLine($"    SELECT *, TRUE AS {ComparePresent} FROM {{{{ ref('{ctx.GetFormattedSourceModelName(compare, merge)}') }}}}");
    sql.AppendLine(")");
    sql.AppendLine("SELECT");
    foreach (var column in columns)
    {
      sql.AppendLine($"    IFF(c.{ComparePresent}, c.{column}, r.{column}) AS {column},");
    }

    sql.AppendLine("    CASE");
    sql.AppendLine($"        WHEN r.{ReferencePresent} IS NULL THEN 'new'");
    sql.AppendLine($"        WHEN c.{ComparePresent} IS NULL THEN 'deleted'");
    if (merge.ValueFields.Count > 0)
    {
      sql.AppendLine($"        WHEN {string.Join(" AND ", merge.ValueFields.Select(v => $"EQUAL_NULL(r.{v}, c.{v})"))} THEN 'identical'");
      sql.AppendLine("        ELSE 'changed'");
    }
    else
    {
      sql.AppendLine("        ELSE 'identical'");
    }

    sql.AppendLine($"    END AS {merge.FlagField}");
    sql.AppendLine("FROM reference_rows AS r");
    sql.AppendLine("FULL OUTER JOIN compare_rows AS c");
    sql.Append($"    ON {string.Join(" AND ", merge.KeyFields.Select(k => $"EQUAL_NULL(r.{k}, c.{k})"))}");

    // The body is RawContentsOverride; the AST only satisfies the query's constructor.
    var sqlEmit = SqlEmit.Instance;
    var select = sqlEmit.Select(sqlEmit.SelectBody(columns: new SqlExpr[] { sqlEmit.LiteralExpr(sqlEmit.Literal(1)) }));
    return
    [
      new IntermediateQueryForDbt(select, ctx.GetModelName(merge), merge, new DbtArtifactMetadata())
      {
        RawContentsOverride = sql.ToString(),
      },
    ];
  }

  private static Transformation Input(Transformation[] incoming, string name, string role)
    => incoming.FirstOrDefault(t => string.Equals(t.Name, name, StringComparison.Ordinal))
      ?? throw new InvalidOperationException(
        $"Merge rows (diff) names '{name}' as its {role} stream, and no hop into it comes from a transform of that name");
}
