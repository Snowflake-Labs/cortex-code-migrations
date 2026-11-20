// Unit parameters and variables through the engine's shared SSIS/Informatica variables runtime,
// with no engine change. No default "param_file": a Hop pipeline names no environment file
// (hop-run -e picks one per run), so a run passes it with EXECUTE TASK ... USING CONFIG.
namespace AiFirst.Producer;

using System;
using System.Collections.Generic;
using System.Linq;
using Mobilize.AnsiSql.AST;
using Newtonsoft.Json;
using Snowflake.SnowConvert.EtlToDbt;
using Snowflake.SnowConvert.EtlToDbt.Constants;
using Snowflake.SnowConvert.EtlToDbt.Context;
using Snowflake.SnowConvert.EtlToDbt.Dbt;
using Snowflake.SnowConvert.EtlToDbt.OutputSerialization.Models;
using Snowflake.SnowConvert.EtlToDbt.Variables;

/// <summary>
/// A unit's run-time values as engine definitions, plus the two facts the root task needs beside
/// them: which keys sit in the CONFIG "project" section, and the environment file a run swaps.
/// </summary>
/// <param name="Definitions">One definition per parameter and variable, scoped to the unit.</param>
/// <param name="ProjectKeys">Keys rendered in the "project" section rather than "package".</param>
/// <param name="ParameterFile">The environment file whose values are the CONFIG defaults and that a run
/// swaps through CONFIG "param_file"; null when there is none.</param>
internal sealed record ProducerUnitVariables(
  IReadOnlyList<EtlVariableDefinition> Definitions,
  IReadOnlySet<string> ProjectKeys,
  string? ParameterFile)
{
  internal static readonly ProducerUnitVariables None = new([], new HashSet<string>(), null);
}

internal static class ProducerParameters
{
  /// <summary>
  /// One definition per parameter or variable. Namespace and ScopeHierarchy stay empty, so
  /// <see cref="EtlVariableDefinition.ConstantReference"/> is the name with spaces as underscores:
  /// the CONFIG key, the control_variables row, the --vars key and the model's var() key are then
  /// the same string. The scope is the unit name through the SSIS sanitizer, as SSIS scopes a
  /// package's variables.
  /// </summary>
  internal static IReadOnlyList<EtlVariableDefinition> Build(
    string unitName,
    IEnumerable<(string Name, string Default, string DataType, bool IsParameter)> values)
  {
    var scope = SsisNameUtilities.SanitizeName(unitName);
    return values
      .Select(p => new EtlVariableDefinition
      {
        Id = p.Name,
        Name = p.Name,
        DataType = p.DataType,
        Scope = scope,
        OrchestratorScope = unitName,
        Value = p.Default,
        IsParameter = p.IsParameter,
        IsProjectVariable = true,
        // Unquoted, YAML reads an ISO date as a date and 10 as an int; a VARCHAR stays a string.
        RenderValueDoubleQuoted = string.Equals(p.DataType, "VARCHAR", StringComparison.OrdinalIgnoreCase),
      })
      .ToList();
  }

  internal static ProducerUnitVariables Build(
    string unitName, IReadOnlyList<AiFirstProducerIrHydrator.IrParameter> values, string? parameterFile)
  {
    var definitions = Build(unitName, values.Select(p => (p.Name, p.Default, p.DataType, p.IsParameter)));
    var projectKeys = definitions
      .Zip(values, (d, v) => (d.ConstantReference, v.Section))
      .Where(p => string.Equals(p.Section, ControlVariablesConstants.ProjectConfigKey, StringComparison.Ordinal))
      .Select(p => p.ConstantReference)
      .ToHashSet(StringComparer.Ordinal);
    return new ProducerUnitVariables(definitions, projectKeys, definitions.Count == 0 ? null : parameterFile);
  }

  internal static IReadOnlyList<ISqlStatement> RootSetup(string scope, bool hasProject, bool hasParameterFile)
  {
    var result = new List<ISqlStatement>
    {
      VariableCodeGenerationHelper.CreateConfigLetStatement(ControlVariablesConstants.PackageConfigKey),
      VariableCodeGenerationHelper.CreateScopeLetStatement(scope),
      VariableCodeGenerationHelper.CreateClearVariablesCall(),
      VariableCodeGenerationHelper.CreateInitVariablesFromConfigCall(),
    };
    if (hasProject)
    {
      result.Insert(1, VariableCodeGenerationHelper.CreateConfigLetStatement(
        ControlVariablesConstants.ProjectConfigKey, ControlVariablesConstants.ProjectConfigVariableName));
      result.Add(VariableCodeGenerationHelper.CreateInitVariablesFromConfigCall(
        ControlVariablesConstants.ProjectConfigVariableName));
    }

    if (hasParameterFile)
    {
      result.Add(VariableCodeGenerationHelper.CreateLoadParameterFileCallFromConfig(Array.Empty<string>()));
    }

    return result;
  }

  /// <summary>
  /// The comment put above the root task when the unit reads an environment file: the root runs with
  /// that file's values as its CONFIG defaults, and a run swaps in another one the way an Informatica
  /// parameter file is loaded (LoadParameterFile, CONFIG "param_file"). Same AIM type as
  /// issues/detect.py detect_parameter_file_stage reports for the IR fact.
  /// </summary>
  internal static string ParameterFileNotice(string parameterFile) =>
    "--** AIM-VAR-" + EnvironmentSwapAimId + " - THE ROOT TASK RUNS WITH THE VALUES OF HOP ENVIRONMENT FILE '"
    + parameterFile + "' AS ITS DEFAULT CONFIG. TO RUN WITH ANOTHER ENVIRONMENT FILE, CONVERT IT TO THE EXPECTED "
    + "JSON FORMAT ({\"*global*\": {\"NAME\": \"value\"}}), PUT IT ON A SNOWFLAKE STAGE AND RUN EXECUTE TASK ... "
    + "USING CONFIG = '{\"param_file\": \"@<STAGE>/<FILE>\"}'. **"
    + Environment.NewLine;

  internal const string EnvironmentSwapAimId = "553da6562f7d";

  /// <summary>The project contents argument of the variables overload; the producer writes no folder hooks.</summary>
  internal static EtlDbtProjectContents EmptyContents() => new(Enumerable.Empty<IDbtArtifact>());
}

/// <summary>
/// The root CONFIG for a unit: the SSIS generator's "package" and "project" sections, with the
/// engine's entry converter.
/// </summary>
internal sealed class ProducerTaskConfigJsonGenerator(ProducerUnitVariables unit) : ITaskConfigJsonGenerator
{
  public string? BuildConfigJson(IOrchestrationConversionContext context)
  {
    var all = context.AllDefinitions.ToList();
    if (all.Count == 0)
    {
      return null;
    }

    var config = new Dictionary<string, object>();
    config[ControlVariablesConstants.PackageConfigKey] = new SortedDictionary<string, VariableConfigEntry>(
      Section(all.Where(v => !unit.ProjectKeys.Contains(v.ConstantReference))));
    var project = all.Where(v => unit.ProjectKeys.Contains(v.ConstantReference)).ToList();
    if (project.Count > 0)
    {
      config[ControlVariablesConstants.ProjectConfigKey] = Section(project);
    }

    return JsonConvert.SerializeObject(config, Formatting.Indented);
  }

  private static Dictionary<string, VariableConfigEntry> Section(IEnumerable<EtlVariableDefinition> variables) =>
    variables.ToDictionary(
      v => v.ConstantReference,
      v => new VariableConfigEntry { Value = v.Value, Type = v.DataType, IsParameter = v.IsParameter });
}
