// <copyright file="AiFirstProducerIrHydrator.SinkWrites.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Snowflake.SnowConvert.EtlToDbt.Models;
using Snowflake.SnowConvert.EtlToDbt.Models.Enums;

/// <summary>
/// The write mode of every target, stated for the test seed: how the run changes the table and which
/// table columns identify a row of it.
/// </summary>
internal static partial class AiFirstProducerIrHydrator
{
  /// <summary>Insert every row and keep the table's other rows.</summary>
  internal const string AppendSinkMode = "append";

  /// <summary>Empty the table, then insert every row.</summary>
  internal const string ReplaceSinkMode = "replace";

  /// <summary>One target's write, as <c>sink_writes.json</c> states it.</summary>
  /// <param name="Table">The table the target writes.</param>
  /// <param name="Transform">The source element's name.</param>
  /// <param name="Mode">
  /// <see cref="AppendSinkMode"/>, <see cref="ReplaceSinkMode"/>, <c>update_only</c>, <c>delete</c>, or a
  /// <see cref="TargetWriteKind"/> in snake case (<c>replace_if_rows</c>, <c>upsert</c>,
  /// <c>insert_only</c>, <c>synchronize</c>, <c>scd2</c>, <c>combination</c>).
  /// </param>
  /// <param name="Keys">
  /// The table columns that identify a row: the keys the write matches on, plus the version column of a
  /// versioned dimension. Empty when the write states none.
  /// </param>
  internal sealed record SinkWrite(string Table, string Transform, string Mode, IReadOnlyList<string> Keys);

  private static SinkWrite? SinkWriteOf(Transformation element, JsonElement elementJson, TargetWriteMode? mode)
  {
    if (element is OleDbCommandTransformation command)
    {
      return new SinkWrite(
        command.TableName,
        element.Name,
        command.CommandType == OleDbCommandType.Delete ? "delete" : "update_only",
        command.UniqueKeyColumns.ToList());
    }

    if (element is not TargetTransformation target)
    {
      return null;
    }

    if (mode is null)
    {
      return new SinkWrite(
        target.TableName,
        element.Name,
        IsYes(elementJson, "TruncateTarget") ? ReplaceSinkMode : AppendSinkMode,
        []);
    }

    var keys = mode.KeyColumns.ToList();
    if (mode.Kind == TargetWriteKind.Scd2 && mode.Spec?.GetValueOrDefault("version") is string version
      && !keys.Contains(version, StringComparer.OrdinalIgnoreCase))
    {
      keys.Add(version);
    }

    return new SinkWrite(target.TableName, element.Name, SinkModeName(mode.Kind), keys);
  }

  private static string SinkModeName(TargetWriteKind kind) => kind switch
  {
    TargetWriteKind.Upsert => "upsert",
    TargetWriteKind.InsertOnly => "insert_only",
    TargetWriteKind.ReplaceIfRows => "replace_if_rows",
    TargetWriteKind.Synchronize => "synchronize",
    TargetWriteKind.Scd2 => "scd2",
    TargetWriteKind.Combination => "combination",
    _ => throw new InvalidOperationException($"no sink mode name for {kind}"),
  };
}
