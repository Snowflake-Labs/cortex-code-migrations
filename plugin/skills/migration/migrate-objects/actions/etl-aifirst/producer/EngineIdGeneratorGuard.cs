// <copyright file="EngineIdGeneratorGuard.cs" company="Snowflake Inc">
//        Copyright (c) 2019-2026 Snowflake Inc. All rights reserved.
// </copyright>

namespace AiFirst.Producer;

using System;
using System.Reflection;
using System.Threading;
using Artinsoft.Common.AST;

/// <summary>
/// Ends the emitter with <see cref="ExitCode"/> when the engine fails to fetch an AST id seed.
/// </summary>
/// <remarks>
/// <para>
/// The engine's <c>RefreshableIdGenerator</c> marks itself initialised before its first seed fetch
/// (<c>InterprocessIdGeneratorFactory.GetNextSeed</c>, a named mutex over a per-user control file).
/// On macOS that mutex can fail to open (<c>IOException ... lstat("") == -1; errno == ENOENT</c>).
/// The generator then never gets ids for the rest of the process: the next parse spins forever in
/// <c>GetId()</c> (a Pentaho Formula re-emit hung for 90 minutes), or the exception is caught inside
/// a translator and the node comes out wrong (a Hop Synchronize after merge lost its mart).
/// </para>
/// <para>
/// The process cannot recover, so the guard does not try: it reports the failure and exits, before a
/// partial tree is taken for a result. The driver runs the emitter again in a fresh process, which
/// fetches its seed anew.
/// </para>
/// <para>
/// An engine with the fix recovers from a failed fetch itself (it retries the mutex, then guards the
/// seed with the control file's lock), so the guard stands down there: a first-chance exception the
/// engine is about to handle must not end a process that would have succeeded. The fixed engine is
/// recognised by the member it added for that fallback.
/// </para>
/// </remarks>
internal static class EngineIdGeneratorGuard
{
  /// <summary>The emitter's exit code for a failed id seed fetch (EX_TEMPFAIL: run it again).</summary>
  internal const int ExitCode = 75;

  private const string SeedFetchFrame = "InterprocessIdGeneratorFactory.GetNextSeed";

  private const string FixedEngineContextType = "Artinsoft.Common.AST.InterprocessIdGeneratorFactory+Context";

  private const string FixedEngineMember = "MutexUnavailable";

  private static int tripped;

  // Reading the stack can itself raise first-chance exceptions; without this the handler recurses.
  [ThreadStatic]
  private static bool inHandler;

  /// <summary>Watches for a failed seed fetch for the rest of the process.</summary>
  internal static void Install()
  {
    if (EngineRecoversFromSeedFailure())
    {
      return;
    }

    AppDomain.CurrentDomain.FirstChanceException += (_, e) =>
    {
      if (inHandler || Volatile.Read(ref tripped) != 0)
      {
        return;
      }

      inHandler = true;
      try
      {
        // The first-chance exception carries no trace yet; the current stack still holds the fetch.
        if (!Environment.StackTrace.Contains(SeedFetchFrame, StringComparison.Ordinal))
        {
          return;
        }

        if (Interlocked.Exchange(ref tripped, 1) == 0)
        {
          // Exiting from inside the handler would run while the engine holds its control-file lock;
          // a background thread exits once the throw has unwound.
          var message = e.Exception.Message;
          new Thread(() => Trip(message)) { IsBackground = true, Name = "engine-id-guard" }.Start();
        }
      }
      finally
      {
        inHandler = false;
      }
    };
  }

  /// <summary>Gets whether the engine recovers from a failed seed fetch itself.</summary>
  internal static bool EngineRecoversFromSeedFailure() =>
    typeof(IdGeneratorFactory).Assembly.GetType(FixedEngineContextType)
      ?.GetProperty(FixedEngineMember, BindingFlags.Instance | BindingFlags.NonPublic) is not null;

  private static void Trip(string message)
  {
    Thread.Sleep(200);
    Console.Out.Flush();
    Console.Error.WriteLine(
      $"ENGINE_ID_SEED_FAILED: the engine could not fetch an AST id seed ({message}). This process cannot "
      + $"produce a trustworthy tree; exiting {ExitCode} so the caller runs the emitter again.");
    Console.Error.Flush();
    Environment.Exit(ExitCode);
  }
}
