---
name: dcp-setup
description: "Reach an on-premise or private source through a Data Connectivity Proxy tunnel. scai data worker setup --dcp provisions the Snowflake side; this skill covers the agent the customer runs, and the lifecycle around it. Triggers: data connectivity proxy, DCP, on-premise source, private source, source unreachable from Snowflake, dcp agent, rotate bootstrap token."
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Data Connectivity Proxy (DCP) Setup

Data Connectivity Proxy (DCP) lets Snowflake securely reach data sources on your private network
(on-premises, in a VPC, or in a hybrid environment) without requiring you to open inbound firewall
ports or expose your network to the public internet. DCP works by running a lightweight agent process
on your network. The agent makes a single outbound connection on port 443 to Snowflake and
establishes an encrypted tunnel. Snowflake routes requests through that tunnel to reach the private
data source. Your firewall sees only outbound traffic: there is no inbound listener, no public IP,
and no VPN required. Use it whenever running the Data Exchange Worker as a Snowpark Container
Services (SPCS) service and the source sits in a private network.

For object properties, status values, and sizing guidance, follow the Snowflake
[Data Connectivity Proxy](https://docs.snowflake.com/en/user-guide/data-connectivity-proxy)
documentation and its `-setup`, `-monitor`, `-security`, `-troubleshoot`, and `-reference` pages.

---

## Step 1 — Provision the Snowflake side

Pass `--dcp` to worker setup and it creates the DCP-mode network rule for the source endpoint, creates
the integration that rule lives in, creates or reuses the proxy object, and attaches the integration to
the worker service:

```bash
scai data worker setup --compute-pool <pool> --dcp <PROXY_NAME>
```

- **The proxy name is required.** Pass the *same* name from several workers when they read sources in the
  **same network**, so they share one tunnel — a proxy corresponds to one network scope. Naming it
  explicitly also keeps the name agreed with whoever provisioned the proxy, when that was someone else.
- **Setup writes only the tunnel objects that are missing or wrong.** The DCP rule, its integration and
  the proxy are each read first and left alone when they already match, so a re-run against a provisioned
  tunnel issues no tunnel DDL. That is what lets a role without ACCOUNTADMIN use a proxy someone else
  created. The source secret and the worker's direct-egress rule and integration are rewritten on every
  run, with or without `--dcp`.
- The proxy name must be an **unquoted identifier** (letters, digits, `_`, `$`; not starting with a
  digit). Setup upper-cases it.
- The source endpoint needs a **DNS hostname**; setup rejects an address literal, because the value is
  resolved in the agent's network. For a name that resolves only privately, give the agent container the
  mapping with `--add-host <name>:<ip>`.
- **Certificates are issued only when this run creates the proxy**, and setup then reads the route check
  once and continues: it never waits for them. The **first issuance in an account takes about 30 minutes**,
  and the route check confirms certificates only once an agent connects, so start the agent right after
  setup; it bootstraps once issuance finishes. Reusing an existing proxy never issues certificates (that
  needs `OWNERSHIP`); setup warns when certificates are not confirmed, naming
  `SELECT SYSTEM$ISSUE_PER_ACCOUNT_CERTIFICATES()` for the owner to run.
- `--dcp` takes effect when the worker service is **created**. On a worker that is already deployed, re-run
  with `--yes` to recreate it with the tunnel; without `--yes`, setup warns and leaves the worker as it is.
- Creating a proxy needs `CREATE DATA CONNECTIVITY PROXY` on the account. Reusing one does not.
- Workers sharing a proxy are added one at a time: while setup changes the proxy's integration list it
  holds a disabled integration named `SCAI_DCP_LOCK_<PROXY_NAME>_<HASH>` (a long proxy name is cut to
  fit Snowflake's 255-character limit; the hash keeps it unique) and drops it when done. Another setup
  waits up to 5 minutes for it, then stops without touching the proxy, saying since when the lock is
  held. Setup never drops a lock it did not create, however old: a run that died leaves its lock, and
  once no setup is running its owner runs the `DROP INTEGRATION` the error names.
  Adding an integration to a shared proxy therefore needs `CREATE INTEGRATION`; without it setup stops
  and names the integration for the proxy's owner to add by hand. A re-run whose integration is already
  attached needs neither.

## Step 2 — Mint the bootstrap token

The tool does not mint this: it needs `OWNERSHIP` on the proxy or ACCOUNTADMIN, which the migration role
often does not hold. Whoever owns the proxy runs:

```sql
SELECT SYSTEM$GENERATE_DATA_CONNECTIVITY_PROXY_BOOTSTRAP_TOKEN('<PROXY_NAME>', <days>);
```

The second argument is the validity in days, 1–90. Size it to the migration: a token that outlives the
run is a credential sitting on the agent host, and one that expires mid-run stops certificate rotation
until it is replaced.

The result must be an **Access JWT**. A value beginning `PAT_` is a programmatic access token, which the
agent rejects — and the failure would otherwise only surface much later as a bootstrap error on the
agent host. It is a credential: keep it out of deploy scripts and out of chat.

## Step 3 — Run the tunnel agent

This is the customer's step, on a host in the source's network with outbound 443. Place the token, then
start the agent:

```bash
sudo install -d -m 700 /etc/dcp-agent/secrets
sudo install -m 600 /dev/null /etc/dcp-agent/secrets/dcp-bootstrap-token
# paste the token minted in Step 2 into that file
```

```bash
docker run -d --name dcp-agent \
  --restart unless-stopped \
  -v /etc/dcp-agent/secrets:/etc/dcp-agent/secrets:ro \
  snowflakedb/dcp-client:latest
```

- The token path is the agent's **default**, so `--sf-bootstrap-credentials` is unnecessary.
- Mount the **directory**, not the token file. A file bind mount keeps the file it was started with, so
  a token replaced by rename (see *Rotate the bootstrap token*) would never reach the agent. The files must
  be readable by the container's user; if the agent does not run as root, give that uid the directory
  and the token file.
- The agent needs **direct outbound HTTPS**; `HTTPS_PROXY` and PrivateLink are outside its supported
  configurations.
- **For high availability, run this container on two or more hosts, each registering against the same
  proxy object with the same bootstrap token. The agents are stateless, so Snowflake spreads connections across whichever are connected and moves new connections
  to a survivor when one goes away.

## Step 4 — Verify

```sql
DESCRIBE DATA CONNECTIVITY PROXY <proxy>;
```

Expect `AGENT_HEALTH = HEALTHY`, `AGENT_STATUS = DCP_AGENT_LIFECYCLE_CONNECTED`,
`BOOTSTRAP_STATUS = DCP_AGENT_BOOTSTRAP_SUCCEEDED`, and
`DATA_PATH_STATUS = DCP_AGENT_DATA_PATH_HEALTHY`. `DOWN` on a proxy with no agent started yet is the
expected reading.

A healthy `DESCRIBE` only proves the agent is connected to Snowflake. It does not prove traffic reaches
the source. Check that with the route check, once the agent runs:

```sql
SELECT STAGE, STATUS, DETAIL, REASON
FROM TABLE(<METADATA_DB>.INFORMATION_SCHEMA.DCP_CLIENT_ROUTE_CHECK(
  AGENT_ID    => '<PROXY_NAME>',
  DESTINATION => '<HOST>:<PORT>'));
```

Every stage should report `SUCCESS`. The first stage that does not names where the fault is (the agent,
the network rule, or the source), so you fix the right thing instead of guessing. `scai data doctor`
does not run this check.

Do not take a TCP connect from the worker as evidence either: the link-local egress proxy at
`169.254.0.1` accepts a socket even when no tunnel exists. Only the route check is evidence.

---

## Diagnostics

Two behaviours where the symptom points somewhere other than the cause.

**1 — `token validation failed` points at the account network policy.** An **account-level**
`NETWORK POLICY` that omits the agent host's egress IP surfaces this way, with
`LAST_AUTH_FAILURE_REASON` empty and no bootstrap-failure row. Add the agent host's egress IP to the
account policy, and check that before re-minting the token.

**2 — `workload cert verification failed: cert expired`.** Cycle the consuming runtime so it re-mints
its workload certificate. The agent keeps running, since it re-reads its token file on rotation.

The first connection after an agent starts can reset while the tunnel weld settles. The worker retries
its source connections, so this needs no operator action.

---

## Operating a live tunnel

Each operation says whether it is safe during a migration, so you know which ones wait for a pause
between tables. Snowflake manages relay upgrades and keeps active connections up; the operations here
act on the agent the customer runs.

**Rotate the bootstrap token — safe during a migration.** The agent re-reads its credentials file on
each certificate-rotation cycle, so it picks up a replacement in place:

```bash
echo '<new-token>' > /etc/dcp-agent/secrets/dcp-bootstrap-token.new
chmod 600 /etc/dcp-agent/secrets/dcp-bootstrap-token.new
mv /etc/dcp-agent/secrets/dcp-bootstrap-token.new /etc/dcp-agent/secrets/dcp-bootstrap-token
```

Mint the replacement the same way as Step 2, with
`SELECT SYSTEM$GENERATE_DATA_CONNECTIVITY_PROXY_BOOTSTRAP_TOKEN('<proxy>', <days>);`. The agent applies
the new token on its next rotation cycle. Replace the token before it expires: certificate refresh
depends on a valid token, so an expired one stops rotation while the agent runs on its current
certificates.

**Upgrade the agent — drains the host being replaced.** Replacing the image closes that host's active
TCP connections. The agent drains on `SIGTERM`, so give it time to finish:

```bash
docker run -d --name dcp-agent-new ... snowflakedb/dcp-client:<new-version> ...
# once the routing table has shifted, drain the old one
docker stop --time 300 dcp-agent
```

With a second agent already running, new connections move to it and the worker's retry covers what was
in flight. With a single agent, upgrade between tables.

**Add an agent — safe during a migration.** Run the same `docker run` on another host in a separate
failure domain with the same bootstrap token; the agents are stateless, so the control plane starts
placing connections on it. Scope this correctly: **two agents give failover, and one destination still
gets the bandwidth of one agent** — Snowflake pins connections to a destination rather than spreading
them. For throughput, split destinations across agents with separate integrations.

**Losing an agent** closes the tunnels it held, and their TCP connections reset. The worker retries
source connections with backoff, so a migration continues while another agent is connected and resumes
when one returns. Confirm what happened with `DESCRIBE DATA CONNECTIVITY PROXY` (is an agent connected?)
and the route check from Step 4 (which stage fails?), which separate an absent agent from a rule that omits
the destination.

## Before you move data

```
- [ ] DESCRIBE reports AGENT_HEALTH = HEALTHY and a healthy data path
- [ ] The Step 4 route check reports SUCCESS for every stage to the source
- [ ] A second agent is running if the migration needs to survive losing one host
- [ ] Account-level network policy carries the agent hosts' egress IPs
- [ ] Bootstrap token expiry tracked, so certificate rotation cannot silently stop
```

## Appendix — hand the provisioning to the customer

Use this when the migration role cannot provision the tunnel itself. Setup reports that as one of:

- `CREATE DATA CONNECTIVITY PROXY` is missing, so the proxy cannot be created.
- `CREATE INTEGRATION` is missing, so the integration cannot be created.
- The proxy exists but the migration role has no `USAGE` on it. Snowflake reports an unreadable proxy
  the same way as an absent one, so setup names both ways out when it cannot create it: the
  `CREATE DATA CONNECTIVITY PROXY` privilege, or `GRANT USAGE ON DATA CONNECTIVITY PROXY <PROXY_NAME>`.

Do not retry, and do not switch roles hoping for a different result. Give the customer a script to run,
and resume when they confirm it. Their ACCOUNTADMIN provisions the same objects `--dcp` would, so the
later `scai data worker setup --dcp <PROXY_NAME>` run reads them, finds them matching, and issues no tunnel DDL.

**Resolve every value below before you send the script.** Send working SQL, not placeholders — the
customer cannot derive these names, and setup derives them exactly, so a name that differs by one
character reads as absent and setup creates a second object beside theirs:

| Placeholder | Value |
| --- | --- |
| `<PROXY_NAME>` | The name you will pass to `--dcp`; agree it with them |
| `<METADATA_DB>` | The migration metadata database, e.g. `SNOWCONVERT_AI` |
| `<TYPE>` | Source type, uppercase, e.g. `SQLSERVER` |
| `<PREFIX>` | Empty for the default worker service name, otherwise `<SERVICE_NAME>_` |
| `<HOST>:<PORT>` | The source endpoint as a **DNS hostname**, e.g. `mssql.internal:1433` |
| `<MIGRATION_ROLE>` | The role the worker runs as |
| `<DAYS>` | Bootstrap token validity, 1–90; size it to the migration |

The derived names are then:

- Network rule — `<METADATA_DB>.PUBLIC.<PREFIX><TYPE>_DCP_RULE`
- Integration — `SCAI_EAI_DCP_<PREFIX><TYPE>_<METADATA_DB>`

Tell them to run this as ACCOUNTADMIN. The order matters: the integration needs the rule, and the proxy
needs the integration.

```sql
-- 1. Name the private source endpoint.
--    MODE = DATA_CONNECTIVITY_PROXY_EGRESS is what makes this endpoint eligible for the tunnel.
--    A plain MODE = EGRESS rule is never applied to DCP, and the mode cannot be changed later.
--    Use a DNS hostname, not an IP address: the agent resolves this name in your network.
CREATE NETWORK RULE IF NOT EXISTS <METADATA_DB>.PUBLIC.<PREFIX><TYPE>_DCP_RULE
  MODE = DATA_CONNECTIVITY_PROXY_EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('<HOST>:<PORT>');

-- 2. Wrap the rule in an integration. The proxy attaches to this, not to the rule.
CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS SCAI_EAI_DCP_<PREFIX><TYPE>_<METADATA_DB>
  ALLOWED_NETWORK_RULES = (<METADATA_DB>.PUBLIC.<PREFIX><TYPE>_DCP_RULE)
  ENABLED = TRUE;

-- 3. Create the proxy. This is the statement the migration role cannot run.
CREATE DATA CONNECTIVITY PROXY IF NOT EXISTS <PROXY_NAME>
  EXTERNAL_ACCESS_INTEGRATIONS = (SCAI_EAI_DCP_<PREFIX><TYPE>_<METADATA_DB>)
  ENABLED = TRUE;

-- 4. Start certificate issuance. The reply "Certificates will be issued" reports only that
--    issuance started. The first call in an account takes about 30 minutes. Later calls do nothing.
SELECT SYSTEM$ISSUE_PER_ACCOUNT_CERTIFICATES();

-- 5. Optional: read where issuance stands. Do not wait for SUCCESS before the next steps:
--    the agent can start while issuance runs and bootstraps once it finishes.
--    IN_PROGRESS or an empty result (the proxy is not reporting yet, as before an agent connects)
--    are both fine here. Read only the CERTIFICATES row. Every later stage needs a running agent.
SELECT STATUS, DETAIL, REASON
FROM TABLE(INFORMATION_SCHEMA.DCP_CLIENT_ROUTE_CHECK(
  AGENT_ID    => '<PROXY_NAME>',
  DESTINATION => '<HOST>:<PORT>'))
WHERE STAGE = 'CERTIFICATES';

-- 6. Let the migration role read the proxy and run the route check.
--    Without USAGE, Snowflake reports the proxy as not existing, and setup tries to create one.
GRANT USAGE ON DATA CONNECTIVITY PROXY <PROXY_NAME> TO ROLE <MIGRATION_ROLE>;
GRANT USAGE ON INTEGRATION SCAI_EAI_DCP_<PREFIX><TYPE>_<METADATA_DB> TO ROLE <MIGRATION_ROLE>;

-- 7. Confirm the handover, and report both outputs back.
--    EXTERNAL_ACCESS_INTEGRATIONS must list the integration from step 2.
--    VALUE_LIST must carry the exact host:port the worker connects to.
--    AGENT_HEALTH = DOWN is correct here: no agent has started yet.
DESCRIBE DATA CONNECTIVITY PROXY <PROXY_NAME>;
DESCRIBE NETWORK RULE <METADATA_DB>.PUBLIC.<PREFIX><TYPE>_DCP_RULE;

-- 8. Give the agent a bootstrap token. Choose one option.
--    Option A - mint it yourself. The grants in step 6 do not permit this call, so every
--    replacement token also comes from you. Validity is in days, 1 to 90.
--    Option B - transfer ownership, so the migration role mints its own tokens:
--      GRANT OWNERSHIP ON DATA CONNECTIVITY PROXY <PROXY_NAME> TO ROLE <MIGRATION_ROLE>;
SELECT SYSTEM$GENERATE_DATA_CONNECTIVITY_PROXY_BOOTSTRAP_TOKEN('<PROXY_NAME>', <DAYS>);
```

Size `<DAYS>` to the migration, as in [Step 2](#step-2--mint-the-bootstrap-token): a token that outlives
the run sits on the agent host longer than it needs to, and one that expires mid-run stops certificate
rotation until it is replaced. The customer places it themselves, following
[Step 3](#step-3--run-the-tunnel-agent).

Two objects stay out of what you send them. The **source secret** is rewritten by every setup run, so
creating it here has no effect. The worker's **direct-egress integration** is a separate object that
worker setup maintains; if the migration role lacks `CREATE INTEGRATION`, that run needs their
ACCOUNTADMIN too, and `../worker-spcs/SKILL.md` covers it.

When they report back, re-run `scai data worker setup --dcp <PROXY_NAME>`. It should now read every object
as matching and issue no tunnel DDL. If it still reports the proxy as not visible, the `USAGE` grant did not
land, or a name differs from what setup derives — compare the two `DESCRIBE` outputs against the derived names above
before asking them for anything else.

## Done

Return to `../worker-spcs/SKILL.md` to finish deploying the worker. Routing detail:
[Affinity](../references/affinity-reference.md).
