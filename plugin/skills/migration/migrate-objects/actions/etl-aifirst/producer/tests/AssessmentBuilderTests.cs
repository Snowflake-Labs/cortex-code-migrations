namespace AiFirst.Producer.Tests;

using System;
using AiFirst.Producer;
using Mobilize.Snow.Assessment.AssessmentMode.ETLAndReporting;

internal static class AssessmentBuilderTests
{
  public static void HasStatusReportsRegisteredStatuses()
  {
    var recording = new RecordingEtlAssessmentBuilder();
    Check(!recording.HasStatus("Package\\Task"), "Recording: no status before RegisterStatus");
    recording.RegisterStatus("Package\\Task", EtlReplatformStatus.NotSupported);
    Check(recording.HasStatus("Package\\Task"), "Recording: status after RegisterStatus");
    Check(!recording.HasStatus("package\\task"), "Recording: names are ordinal, case-sensitive");
    recording.RegisterEwi("Package\\Other", default!);
    Check(!recording.HasStatus("Package\\Other"), "Recording: an EWI is not a status");

    var noOp = new NoOpEtlAssessmentBuilder();
    noOp.RegisterStatus("Package\\Task", EtlReplatformStatus.NotSupported);
    Check(!noOp.HasStatus("Package\\Task"), "NoOp: keeps nothing, so never has a status");
  }

  private static void Check(bool condition, string message)
  {
    if (!condition)
    {
      throw new InvalidOperationException(message);
    }
  }
}
