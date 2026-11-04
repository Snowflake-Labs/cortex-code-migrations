// <copyright file="WriteOutputRows.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Mobilize.AnsiSql.AST;
using Mobilize.Snow;
using Snowflake.SnowConvert.EtlToDbt.Dag;
using Snowflake.SnowConvert.EtlToDbt.DbtGeneration;
using Snowflake.SnowConvert.EtlToDbt.DbtGeneration.Translations;
using Snowflake.SnowConvert.EtlToDbt.Models;
using Snowflake.SnowConvert.EtlToDbt.Models.Columns;

/// <summary>
/// The rows a write rejected, routed by an error edge (Hop transform error handling, an SSIS error
/// output). Snowflake rejects a statement, not a row: a converted write either loads every row or
/// fails, so its error stream is empty.
/// </summary>
internal sealed class WriteErrorRowsTransformation : Transformation
{
  /// <summary>Gets the name of the write whose error rows these are.</summary>
  public string WriteName { get; init; } = string.Empty;
}

/// <summary>Writes an error stream as the write's input columns, the error fields as NULL, and no row.</summary>
internal sealed class WriteErrorRowsTranslator : IEtlIrElementToDbtArtifactTranslator
{
  /// <inheritdoc/>
  public string TypeNameToApplyTo => typeof(WriteErrorRowsTransformation).FullName!;

  /// <inheritdoc/>
  public ITranslationResult[] Translate(Transformation transformation, IEtlIrToDbtContext ctx)
  {
    var errors = (WriteErrorRowsTransformation)transformation;
    var input = ctx.GetIncomingEntities(errors).Single();
    var available = input.OutputColumns.Select(c => c.Name).ToHashSet(StringComparer.OrdinalIgnoreCase);

    var sql = new StringBuilder();
    sql.AppendLine($"-- Error rows of '{errors.WriteName}'. Snowflake rejects a statement, not a row: the");
    sql.AppendLine("-- converted write loads every row or fails, so no row reaches this stream.");
    sql.AppendLine("SELECT");
    sql.AppendLine(string.Join(
      ",\n",
      errors.OutputColumns.Select(c => available.Contains(c.Name)
        ? $"    {c.Name}"
        : $"    CAST(NULL AS VARCHAR) AS {c.Name}")));
    sql.AppendLine($"FROM {{{{ ref('{ctx.GetFormattedSourceModelName(input, errors)}') }}}}");
    sql.Append("WHERE FALSE");

    // The body is RawContentsOverride; the AST only satisfies the query's constructor.
    var sqlEmit = SqlEmit.Instance;
    var select = sqlEmit.Select(sqlEmit.SelectBody(columns: new SqlExpr[] { sqlEmit.LiteralExpr(sqlEmit.Literal(1)) }));
    return
    [
      new IntermediateQueryForDbt(select, ctx.GetModelName(errors), errors, new DbtArtifactMetadata())
      {
        RawContentsOverride = sql.ToString(),
      },
    ];
  }
}

/// <summary>
/// Routes what a write passes on. A write hands the transforms after it the rows it wrote in this run,
/// and an error edge the rows it rejected. A dbt <c>ref()</c> of the write's model reads the whole
/// table instead, earlier runs included, and a reject stream has no column the error fields name. So
/// an edge out of a write starts at the write's own input, and an error edge passes through a
/// <see cref="WriteErrorRowsTransformation"/>. A lookup that writes (a dimension or a combination)
/// adds its technical key to the rows it passes on, which only its table holds, so its other edges
/// keep reading its model.
/// </summary>
internal static class WriteOutputRows
{
  internal const string ErrorEdgeLabel = "error";

  /// <summary>Rewires the edges out of a write with exactly one input; other edges are kept.</summary>
  /// <param name="nodes">The graph's nodes; an error-rows node is appended per error edge.</param>
  /// <param name="edges">The graph's edges.</param>
  /// <param name="modelNames">Model name per node id; the error-rows node's is added.</param>
  /// <param name="writeModes">The write mode per node id, which tells a lookup that writes.</param>
  /// <returns>The rewired edges.</returns>
  internal static List<DagEdge<Transformation>> Route(
    List<DagNode<Transformation>> nodes,
    List<DagEdge<Transformation>> edges,
    Dictionary<string, string> modelNames,
    IReadOnlyDictionary<string, AiFirstProducerIrHydrator.TargetWriteMode> writeModes)
  {
    var routed = new List<DagEdge<Transformation>>(edges);
    foreach (var write in nodes.Where(n => IsWrite(n.Element)).ToList())
    {
      var inputs = edges.Where(e => e.To == write).ToList();
      var outputs = edges.Where(e => e.From == write).ToList();
      if (inputs.Count != 1 || outputs.Count == 0)
      {
        continue;
      }

      var upstream = inputs[0].From;
      var addsTechnicalKey = writeModes.TryGetValue(write.Id, out var mode)
        && mode.Kind is AiFirstProducerIrHydrator.TargetWriteKind.Scd2 or AiFirstProducerIrHydrator.TargetWriteKind.Combination;
      foreach (var output in outputs)
      {
        if (!string.Equals(output.Label, ErrorEdgeLabel, StringComparison.OrdinalIgnoreCase))
        {
          if (!addsTechnicalKey)
          {
            routed.Remove(output);
            routed.Add(new DagEdge<Transformation>(upstream, output.To, null));
          }

          continue;
        }

        routed.Remove(output);
        var errorRows = new DagNode<Transformation>(
          $"{write.Id} (error rows)",
          "transformation",
          new WriteErrorRowsTransformation
          {
            Name = $"{write.Element.Name} (error rows)",
            WriteName = write.Element.Name,
            InputColumns = upstream.Element.OutputColumns.Select(c => new Column { Name = c.Name }).ToList(),
            OutputColumns = output.To.Element.InputColumns.Select(c => new Column { Name = c.Name }).ToList(),
          });
        nodes.Add(errorRows);
        modelNames[errorRows.Id] = modelNames[write.Id] + "__error_rows";
        routed.Add(new DagEdge<Transformation>(upstream, errorRows, null));
        routed.Add(new DagEdge<Transformation>(errorRows, output.To, null));
      }
    }

    return routed;
  }

  private static bool IsWrite(Transformation element) => element is TargetTransformation or OleDbCommandTransformation;
}
