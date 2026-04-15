# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Persistent Snowpark worker process.

Communicates with the Rust MCP server via JSON-over-stdio:
  - Read one JSON object per line from stdin
  - Write one JSON object per line to stdout
  - stderr is unused (available for diagnostics)

Commands:
  {"cmd":"init", "connection_name":"...", "database":"..."|null}
  {"cmd":"sql",  "sql":"...", "params":[...]|null}
  {"cmd":"close"}
"""

import json
import sys


def main():
    session = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception as e:
            _respond(error=f"Invalid JSON: {e}")
            continue

        cmd = req.get("cmd")

        if cmd == "init":
            try:
                from snowflake.snowpark import Session

                cfg = {"connection_name": req["connection_name"]}
                session = Session.builder.configs(cfg).create()
                db = req.get("database")
                if db:
                    safe = db.replace('"', "").upper()
                    session.sql(f'USE DATABASE "{safe}"').collect()
                _respond(ok=True)
            except Exception as e:
                _respond(error=str(e))

        elif cmd == "sql":
            if session is None:
                _respond(error="No session. Send init first.")
                continue
            try:
                params = req.get("params") or None
                if params:
                    rows = session.sql(req["sql"], params=params).collect()
                else:
                    rows = session.sql(req["sql"]).collect()
                result = [[row[i] for i in range(len(row))] for row in rows]
                _respond(rows=result)
            except Exception as e:
                _respond(error=str(e))

        elif cmd == "close":
            if session:
                try:
                    session.close()
                except Exception:
                    pass
            _respond(ok=True)
            break

        else:
            _respond(error=f"Unknown command: {cmd}")


def _respond(**kwargs):
    print(json.dumps(kwargs, default=str), flush=True)


if __name__ == "__main__":
    main()
