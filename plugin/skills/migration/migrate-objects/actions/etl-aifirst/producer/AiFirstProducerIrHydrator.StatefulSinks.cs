// <copyright file="AiFirstProducerIrHydrator.StatefulSinks.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using Mobilize.Snow.Issues;
using Snowflake.SnowConvert.EtlToDbt.Models;
using Snowflake.SnowConvert.EtlToDbt.Models.Columns;

/// <summary>
/// Hydration of the Hop writes the engine has no strategy for: Synchronize after merge, Dimension
/// lookup/update (SCD2) and Combination lookup/update, plus Merge rows (diff), the transform that
/// feeds Synchronize after merge its flag.
/// </summary>
/// <remarks>
/// <para>
/// Each write becomes the engine's <see cref="OptimizedUpdateStrategyTargetTransformation"/>, which
/// builds the mart (the projection of the written columns, alias = the table) exactly as it does for
/// Insert/update. The write itself is a producer strategy macro (hop_synchronize, hop_scd2,
/// hop_combination) whose settings the mart carries in its config; see
/// <see cref="ProducerWriteModes"/> and <see cref="ProducerStatefulSinkMacros"/>.
/// </para>
/// <para>
/// A setting the strategy does not implement degrades the transform, with the reason in the
/// placeholder, instead of writing the table some other way.
/// </para>
/// </remarks>
internal static partial class AiFirstProducerIrHydrator
{
  private static readonly string[] Scd2KeyMethods = ["tablemax", "sequence", "uuid", "field"];

  private static readonly string[] CombinationKeyMethods = ["tablemax", "sequence"];

  private static readonly string[] StartDateAlternatives = ["none", "sysdate", "pipeline_start"];

  private static Transformation HydrateStatefulWrite(string kind, JsonElement elementJson)
  {
    var keys = RequiredStringList(elementJson, "KeyColumns");
    var written = HydrateColumns(elementJson, "OutputColumns").Select(c => c.Name).ToList();
    var refusal = kind switch
    {
      "SynchronizeTargetTransformation" => SynchronizeRefusal(elementJson, keys, written),
      "DimensionTargetTransformation" => DimensionRefusal(elementJson),
      _ => CombinationRefusal(elementJson),
    };
    refusal ??= keys.FirstOrDefault(k => !written.Contains(k, StringComparer.OrdinalIgnoreCase)) is { } unwritten
      ? $"key column '{unwritten}' is not a column this transform writes"
      : null;

    if (refusal is not null)
    {
      return new UnsupportedTransformation
      {
        OriginalTransformationText = (OptionalString(elementJson, "_unsupported") ?? kind) + "\n" + refusal,
        IssueCodeForNotConverted = IssueName.ExceptionThrownWhileConverting,
      };
    }

    return new OptimizedUpdateStrategyTargetTransformation
    {
      TableName = AiFirstProducerDataFlowContext.SanitizeRelationIdentifier(RequiredString(elementJson, "TableName")),
      InlinedUpdateStrategyExpression = "IIF(FALSE, DD_INSERT, DD_UPDATE)",
    };
  }

  private static string? SynchronizeRefusal(JsonElement elementJson, IReadOnlyList<string> keys, IReadOnlyList<string> written)
  {
    if (IsYes(elementJson, "TableNameInField"))
    {
      return "a table named per row (tablename_in_field=Y) has no single relation to write";
    }

    if (OptionalStringList(elementJson, "KeyConditions").Any(c => c.Trim() != "="))
    {
      return "a key condition other than '=' has no keyed-write equivalent";
    }

    if (new[] { "OrderInsert", "OrderUpdate", "OrderDelete" }.All(f => string.IsNullOrEmpty(OptionalString(elementJson, f))))
    {
      return "no operation field value is mapped to insert, update or delete";
    }

    return written.Contains(RequiredString(elementJson, "OperationField"), StringComparer.OrdinalIgnoreCase)
      ? "the operation field is also a written column"
      : null;
  }

  private static string? DimensionRefusal(JsonElement elementJson)
  {
    if (!IsYes(elementJson, "Update"))
    {
      return "a dimension lookup with update=N writes nothing; the lookup itself has no translation";
    }

    var method = KeyMethod(elementJson, Scd2KeyMethods);
    if (method is null)
    {
      return $"technical key creation '{OptionalString(elementJson, "KeyCreation")}' is not implemented "
        + $"(implemented: {string.Join(", ", Scd2KeyMethods)})";
    }

    if (method == "sequence" && string.IsNullOrEmpty(OptionalString(elementJson, "SequenceName")))
    {
      return "a sequence technical key with no sequence name";
    }

    if (method == "field" && string.IsNullOrEmpty(OptionalString(elementJson, "TechnicalKeySourceField")))
    {
      return "a field technical key with no source field";
    }

    foreach (var column in new[] { "VersionColumn", "DateFromColumn", "DateToColumn" })
    {
      if (string.IsNullOrEmpty(OptionalString(elementJson, column)))
      {
        return $"a dimension with no {column} has no versioning to write";
      }
    }

    var alternative = StartDateAlternative(elementJson);
    return StartDateAlternatives.Contains(alternative)
      ? null
      : $"start date alternative '{alternative}' is not implemented (implemented: {string.Join(", ", StartDateAlternatives)})";
  }

  private static string? CombinationRefusal(JsonElement elementJson)
  {
    if (IsYes(elementJson, "UseHash"))
    {
      return "a combination looked up by a hash column (crc=Y) is not implemented";
    }

    var method = CombinationKeyMethod(elementJson);
    if (!CombinationKeyMethods.Contains(method))
    {
      return $"technical key creation '{method}' is not implemented (implemented: {string.Join(", ", CombinationKeyMethods)})";
    }

    return method == "sequence" && string.IsNullOrEmpty(OptionalString(elementJson, "SequenceName"))
      ? "a sequence technical key with no sequence name"
      : null;
  }

  private static string? KeyMethod(JsonElement elementJson, IReadOnlyCollection<string> implemented)
  {
    var method = (OptionalString(elementJson, "KeyCreation") ?? "tablemax").Trim().ToLowerInvariant();
    return implemented.Contains(method) ? method : null;
  }

  // CombinationLookup falls back on <use_autoinc> and <sequence> when <creation_method> is absent.
  private static string CombinationKeyMethod(JsonElement elementJson)
    => OptionalString(elementJson, "KeyCreation") is { Length: > 0 } method
      ? method.Trim().ToLowerInvariant()
      : IsYes(elementJson, "UseAutoIncrement")
        ? "autoinc"
        : string.IsNullOrEmpty(OptionalString(elementJson, "SequenceName")) ? "tablemax" : "sequence";

  private static string StartDateAlternative(JsonElement elementJson)
    => IsYes(elementJson, "UseStartDateAlternative")
      ? (OptionalString(elementJson, "StartDateAlternative") ?? "none").Trim().ToLowerInvariant()
      : "none";

  /// <summary>
  /// Stream fields the strategy reads from the batch and never writes: the Synchronize operation
  /// field, the dimension's stream date and a 'field' technical key's source.
  /// </summary>
  private static void AddStreamOnlyColumns(Transformation element, JsonElement elementJson)
  {
    var kind = OptionalString(elementJson, "$kind");
    var fields = kind switch
    {
      "SynchronizeTargetTransformation" => new string?[] { RequiredString(elementJson, "OperationField") },
      "DimensionTargetTransformation" => new string?[]
      {
        OptionalString(elementJson, "StreamDateField"),
        KeyMethod(elementJson, Scd2KeyMethods) == "field" ? OptionalString(elementJson, "TechnicalKeySourceField") : null,
      },
      _ => Array.Empty<string?>(),
    };

    foreach (var field in fields.OfType<string>().Where(f => f.Length > 0))
    {
      if (element.OutputColumns.Any(c => string.Equals(c.Name, field, StringComparison.OrdinalIgnoreCase)))
      {
        continue;
      }

      element.InputColumns.Add(new Column { Name = field });
      element.OutputColumns.Add(new Column { Name = field });
    }
  }

  private static TargetWriteMode? StatefulWriteModeOf(JsonElement elementJson)
  {
    var kind = OptionalString(elementJson, "$kind");
    if (kind is not ("SynchronizeTargetTransformation" or "DimensionTargetTransformation" or "CombinationTargetTransformation"))
    {
      return null;
    }

    var keys = RequiredStringList(elementJson, "KeyColumns");
    var written = HydrateColumns(elementJson, "OutputColumns")
      .Select(c => c.Name)
      .Distinct(StringComparer.OrdinalIgnoreCase)
      .ToList();
    string? Text(string field) => OptionalString(elementJson, field) is { Length: > 0 } v ? v : null;
    IReadOnlyList<string> List(string field) => OptionalStringList(elementJson, field);

    switch (kind)
    {
      case "SynchronizeTargetTransformation":
        var updates = List("UpdateColumns").Where(c => !keys.Contains(c, StringComparer.OrdinalIgnoreCase)).ToList();
        return new TargetWriteMode(TargetWriteKind.Synchronize, keys, updates, new Dictionary<string, object?>
        {
          ["keys"] = keys,
          ["columns"] = written,
          ["update_columns"] = updates,
          ["operation_field"] = RequiredString(elementJson, "OperationField"),
          ["insert_value"] = Text("OrderInsert"),
          ["update_value"] = Text("OrderUpdate"),
          ["delete_value"] = Text("OrderDelete"),
        });

      case "DimensionTargetTransformation":
        var method = KeyMethod(elementJson, Scd2KeyMethods)!;
        var streamDate = Text("StreamDateField");
        var alternative = StartDateAlternative(elementJson);
        var minYear = int.Parse(Text("MinYear") ?? "1900", CultureInfo.InvariantCulture);
        var maxYear = int.Parse(Text("MaxYear") ?? "2199", CultureInfo.InvariantCulture);
        return new TargetWriteMode(TargetWriteKind.Scd2, keys, [], new Dictionary<string, object?>
        {
          ["keys"] = keys,
          ["technical_key"] = RequiredString(elementJson, "TechnicalKeyColumn"),
          ["key_creation"] = method,
          ["sequence"] = method == "sequence" ? Text("SequenceName") : null,
          ["technical_key_field"] = method == "field" ? Text("TechnicalKeySourceField") : null,
          ["version"] = RequiredString(elementJson, "VersionColumn"),
          ["date_from"] = RequiredString(elementJson, "DateFromColumn"),
          ["date_to"] = RequiredString(elementJson, "DateToColumn"),
          ["stream_date"] = streamDate,
          ["insert_columns"] = List("InsertColumns"),
          ["update_columns"] = List("UpdateColumns"),
          ["punch_columns"] = List("PunchThroughColumns"),
          ["date_inserted_updated_columns"] = List("DateInsertedOrUpdatedColumns"),
          ["date_inserted_columns"] = List("DateInsertedColumns"),
          ["date_updated_columns"] = List("DateUpdatedColumns"),
          ["last_version_columns"] = List("LastVersionColumns"),
          ["min_date"] = string.Format(CultureInfo.InvariantCulture, "{0:D4}-01-01 00:00:00.000", minYear),
          ["max_date"] = string.Format(CultureInfo.InvariantCulture, "{0:D4}-12-31 23:59:59.999", maxYear),
          ["start_date_alternative"] = alternative,
          ["unknown_row"] = !IsYes(elementJson, "UnknownRowCheckDisabled"),
          ["not_found_key"] = method == "uuid" ? "'00000000-0000-0000-0000-000000000000'" : "0",
          ["clock_columns"] = Scd2ClockColumns(elementJson, streamDate, alternative),
        });

      default:
        var combinationMethod = CombinationKeyMethod(elementJson);
        var lastUpdate = Text("LastUpdateColumn");
        return new TargetWriteMode(TargetWriteKind.Combination, keys, [], new Dictionary<string, object?>
        {
          ["keys"] = keys,
          ["technical_key"] = RequiredString(elementJson, "TechnicalKeyColumn"),
          ["key_creation"] = combinationMethod,
          ["sequence"] = combinationMethod == "sequence" ? Text("SequenceName") : null,
          ["last_update_column"] = lastUpdate,
          ["clock_columns"] = lastUpdate is null ? Array.Empty<string>() : new[] { lastUpdate },
        });
    }
  }

  // Columns whose value is the run's clock time, not a function of the input: the validity range
  // when no stream field dates the rows (or a start-date alternative takes the clock), and the
  // audit date columns always.
  private static IReadOnlyList<string> Scd2ClockColumns(JsonElement elementJson, string? streamDate, string alternative)
  {
    var clock = new List<string>();
    if (streamDate is null || alternative != "none")
    {
      clock.Add(RequiredString(elementJson, "DateFromColumn"));
      clock.Add(RequiredString(elementJson, "DateToColumn"));
    }

    clock.AddRange(OptionalStringList(elementJson, "DateInsertedOrUpdatedColumns"));
    clock.AddRange(OptionalStringList(elementJson, "DateInsertedColumns"));
    clock.AddRange(OptionalStringList(elementJson, "DateUpdatedColumns"));
    return clock.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
  }

  private static Transformation HydrateMergeRowsDiff(JsonElement elementJson)
  {
    if (OptionalString(elementJson, "DiffField") is { Length: > 0 })
    {
      return new UnsupportedTransformation
      {
        OriginalTransformationText = (OptionalString(elementJson, "_unsupported") ?? "MergeRows")
          + "\na diff field (the JSON of each change) is not implemented",
        IssueCodeForNotConverted = IssueName.ExceptionThrownWhileConverting,
      };
    }

    return new HopMergeRowsDiffTransformation
    {
      KeyFields = RequiredStringList(elementJson, "KeyFields").ToList(),
      ValueFields = OptionalStringList(elementJson, "ValueFields").ToList(),
      FlagField = RequiredString(elementJson, "FlagField"),
      ReferenceTransform = RequiredString(elementJson, "ReferenceTransform"),
      CompareTransform = RequiredString(elementJson, "CompareTransform"),
    };
  }
}
