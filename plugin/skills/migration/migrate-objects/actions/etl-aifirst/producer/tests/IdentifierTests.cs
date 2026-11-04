namespace AiFirst.Producer.Tests;

using System;
using System.Collections.Generic;
using AiFirst.Producer;

internal static class IdentifierTests
{
  public static void DbtProjectNameIsAValidIdentifier()
  {
    var cases = new Dictionary<string, string>
    {
      ["0006_insert_update_update"] = "t_0006_insert_update_update",
      ["0020_table_output_test_avoid_truncate"] = "t_0020_table_output_test_avoid_truncate",
      ["0012_Dimension__Lookup"] = "t_0012_dimension_lookup",
      ["Archive_DeprecatedTasks"] = "Archive_DeprecatedTasks",
      ["Data_Flow_Task"] = "Data_Flow_Task",
      ["customer_summary_fullname_birthyear"] = "customer_summary_fullname_birthyear",
    };
    foreach (var (input, expected) in cases)
    {
      var actual = ProducerIdentifiers.DbtProjectName(input);
      if (actual != expected)
      {
        throw new InvalidOperationException($"DbtProjectName('{input}') = '{actual}', expected '{expected}'");
      }
    }
  }
}
