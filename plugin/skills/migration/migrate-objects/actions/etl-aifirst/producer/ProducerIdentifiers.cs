// The dbt project name a unit deploys under, made a valid unquoted Snowflake identifier: the
// engine keeps a leading digit (an SSIS refId never has one), and a Hop document stem such as
// `0006-insert-update-update` would make `EXECUTE DBT PROJECT` a syntax error.
namespace AiFirst.Producer;

using System.Collections.Generic;
using Mobilize.AnsiSql.AST;
using Snowflake.SnowConvert.EtlToDbt;
using Snowflake.SnowConvert.EtlToDbt.Context;
using Snowflake.SnowConvert.EtlToDbt.Services;

internal static class ProducerIdentifiers
{
  /// <summary>
  /// The engine's name unchanged when it is already a valid identifier, otherwise the engine's own
  /// SSIS identifier rule (<see cref="SsisNameUtilities.GetFormattedSsisIdentifier"/>: lowercase,
  /// invalid characters to <c>_</c>, no repeated <c>_</c>, <c>t_</c> before a leading digit).
  /// Names that deploy today keep their case and spelling, so their output does not change.
  /// </summary>
  internal static string DbtProjectName(string engineName) =>
    engineName.Length > 0 && char.IsDigit(engineName[0])
      ? SsisNameUtilities.GetFormattedSsisIdentifier(engineName)
      : engineName;
}

/// <summary>
/// Hands the engine's <c>EXECUTE DBT PROJECT</c> generator the name the producer writes the dbt
/// project directory under, so the directory and the statement agree.
/// </summary>
internal sealed class ProducerExecuteDbtProjectStatementGenerator : IExecuteDbtProjectStatementGenerator
{
  private readonly IExecuteDbtProjectStatementGenerator inner;

  internal ProducerExecuteDbtProjectStatementGenerator(IExecuteDbtProjectStatementGenerator inner)
  {
    this.inner = inner;
  }

  public ISqlStatement GenerateExecuteDbtProjectStatement(
    string projectName,
    IOrchestratorTaskTranslationContext context,
    bool hasVariables,
    string variableScope,
    string target = "dev",
    bool useScopeHostParam = false,
    string? scopeHostParameterName = null,
    IReadOnlyList<string>? selectClauses = null) =>
    this.inner.GenerateExecuteDbtProjectStatement(
      ProducerIdentifiers.DbtProjectName(projectName),
      context,
      hasVariables,
      variableScope,
      target,
      useScopeHostParam,
      scopeHostParameterName,
      selectClauses);
}
