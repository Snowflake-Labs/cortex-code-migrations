# SQL Server Windows authentication on SPCS

Follow this file only when the SQL Server does not accept a SQL login and the Data Exchange Worker runs on Snowpark Container Services. A worker on a domain-joined Windows host signs in as the process account; that host stays in `worker-local-setup` and does not use this file.

`<metadata_database>` is `.scai/config/plugin.yml` `metadata_database` (`SNOWCONVERT_AI` unless overridden).

## Confirm it is required

Skip this question when the user already said Windows authentication is required, or the saved connection already has `auth_method = "windows"`.

Ask:

> Does this SQL Server accept a SQL login (username and password)?
> 1. Yes — use SQL authentication
> 2. No — Windows authentication only

**Wait for the user's response — do not proceed until they choose.**

| Answer | Action |
|--------|--------|
| Yes | Stop this file. Return to the caller and use `--auth standard`. |
| No | Continue with **Save the source connection**. |

## Save the source connection

Tell the user:

> The worker on Snowpark Container Services is Linux. It does not join the domain, and the ODBC driver does not fall back to NTLM. Sign-in uses a Kerberos ticket from a keytab.
>
> Active Directory needs two accounts:
> - The SQL Server service account, which owns `MSSQLSvc/<sql-server-fqdn>:<port>`.
> - A separate client account for the worker. That account owns an AES256 keytab. `kerberos_principal` is this account (`client@REALM`), not the SQL Server service account.
>
> Connect with the fully qualified hostname in that service principal. An IP address or a short name makes the lookup fail. The port in the connection, the service principal, the SQL Server listener, and the network rule has to be the same port.
>
> Grant the client account only the SQL Server permissions this migration or validation needs. The SQL Server service keytab stays out of Snowflake.

Ask for the connection name (if there is not one yet), the SQL Server FQDN, the port, the user database, and the client principal (`client@REALM`). **Wait for the user's response — do not proceed until they choose.**

Add the connection when it does not already exist:

```bash
scai connection add-sql-server \
  --source-connection <SOURCE_CONNECTION_NAME> \
  --auth windows \
  --server-url <SQL_SERVER_FQDN> \
  --port <PORT> \
  --database <DATABASE>
```

`scai connection add-sql-server` does not prompt for the principal. `scai data worker setup` rejects a Windows connection without it.

Run `scai connection list -l sqlserver --json`. The `configPath` in that result is the profile file. On the `[connections.<SOURCE_CONNECTION_NAME>]` table, set:

```toml
kerberos_principal = "<CLIENT_PRINCIPAL>"
```

Set that key only. Do not print the file: other connections in it may carry passwords.

Run `scai connection list -l sqlserver --json` again. In the row whose `name` is `<SOURCE_CONNECTION_NAME>`, `credentialsMaskedJson` must show `auth_method` `windows` and the same `kerberos_principal`. If either is missing, the key was written on the wrong table — fix that table and list again.

### When the local test cannot pass

`configure(source_connection=...)` tests from this machine and unsets `source_connection` when the test fails. A domain-joined Windows host should pass. A Mac, or Linux without a Kerberos ticket, fails even when the SPCS worker will succeed.

Call `configure(source_connection=<SOURCE_CONNECTION_NAME>)`.

- **`connection_test: ok`:** the profile is the session source. Continue.
- **Auth or Kerberos failure from this machine:** tell the user:

> The connection profile is saved, but this machine could not sign in to SQL Server, so I can't set it as the session source yet. That test runs here, not in the SPCS worker.

Ask:

> Does this machine need to query SQL Server (extract and assess), or will only the Snowpark Container Services worker sign in?
> 1. This machine must query SQL Server
> 2. Only the SPCS worker will sign in

**Wait for the user's response — do not proceed until they choose.**

| Answer | Action |
|--------|--------|
| This machine must query | On WSL or Linux, follow [`../../connection/sql-server-connection/references/wsl-windows-auth.md`](../../connection/sql-server-connection/references/wsl-windows-auth.md), then call `configure(source_connection=<SOURCE_CONNECTION_NAME>)` again. Keep `kerberos_principal`; the worker still uses it. |
| Only the SPCS worker | Leave the profile saved. Do not add a SQL password to make this test pass, and do not retry `configure` until a test from this machine can succeed. Worker setup below takes `--source-connection <SOURCE_CONNECTION_NAME>`. |

**Stop here** when the caller is the SQL Server connection skill. Return to that skill's Step 4. Secrets and the network rule wait until the SPCS worker skill loads this file again.

## Create the Kerberos secrets

Skip this section when both secrets already exist.

Tell the user:

> Create two secrets in `<metadata_database>.PUBLIC` before worker setup. Setup does not create them, and it does not store a SQL password for this connection.
>
> - `<metadata_database>.PUBLIC.DEW_KERBEROS_KEYTAB` — the client keytab as one line of base64.
> - `<metadata_database>.PUBLIC.DEW_KERBEROS_KRB5_CONF` — the full `krb5.conf`.
>
> A worker service name other than `DATA_EXCHANGE_WORKER_SERVICE` prefixes both names with that service name in uppercase and an underscore. The default service uses the names above.
>
> The worker cannot discover the domain controller from Active Directory DNS, so `krb5.conf` names the realm and every Key Distribution Center, turns DNS lookup off, and prefers TCP. Add a `kdc` line for each domain controller the worker should reach.
>
> Create the secrets in a Snowflake worksheet, or with `snow sql --enable-templating NONE`. The default Snowflake CLI templating removes `[libdefaults]`, `[realms]`, and `[domain_realm]`, and the worker then cannot find the realm.
>
> On Windows, one line of base64 is `[Convert]::ToBase64String([IO.File]::ReadAllBytes("dew-worker.keytab"))`. Put that line in the worksheet. Do not paste the keytab or `krb5.conf` into this chat.

Show this `krb5.conf` shape with their realm and domain controllers filled in:

```ini
[libdefaults]
    default_realm = CORP.EXAMPLE.COM
    dns_lookup_kdc = false
    udp_preference_limit = 0

[realms]
    CORP.EXAMPLE.COM = {
        kdc = dc01.corp.example.com
    }

[domain_realm]
    .corp.example.com = CORP.EXAMPLE.COM
    corp.example.com = CORP.EXAMPLE.COM
```

Show the statements with their realm, KDC hosts, and metadata database filled in. They replace `<one-line-base64-keytab>` in the worksheet themselves:

```sql
CREATE OR REPLACE SECRET <metadata_database>.PUBLIC.DEW_KERBEROS_KEYTAB
  TYPE = GENERIC_STRING
  SECRET_STRING = '<one-line-base64-keytab>';

CREATE OR REPLACE SECRET <metadata_database>.PUBLIC.DEW_KERBEROS_KRB5_CONF
  TYPE = GENERIC_STRING
  SECRET_STRING = $$<full krb5.conf>$$;
```

The role that owns the worker needs `READ` on both secrets. That role already has it when it creates them. When a different role creates them, grant `READ` to the service owner.

**Wait for the user to confirm both secrets exist before continuing.**

## Set up the worker

A network rule that already lists the SQL Server host, the driver-download hosts, and every domain controller is the `--skip-egress` path. Tell the user that setup without `--skip-egress` replaces that rule and drops domain controllers added ahead of time. **Wait** if you are not sure which path they want.

Default path (setup creates the rule, domain controllers are added after):

```bash
scai data worker setup --compute-pool <COMPUTE_POOL> --source-connection <SOURCE_CONNECTION_NAME>
```

Rule already complete:

```bash
scai data worker setup --compute-pool <COMPUTE_POOL> --source-connection <SOURCE_CONNECTION_NAME> --skip-egress
```

The warning `Windows authentication does not create a SQL password secret` means setup took this path. Continue. Do not create a SQL password secret to clear it.

Setup mounts the secrets at `/mnt/keytab` and `/mnt/krb5` and sets `DEW_WINDOWS_AUTH` and `DEW_KERBEROS_PRINCIPAL`. Confirm the command output names `DEW_KERBEROS_KEYTAB` and `DEW_KERBEROS_KRB5_CONF`. On the `--skip-egress` path, continue at **Resume and check**.

## Add the domain controllers

Setup creates `<metadata_database>.PUBLIC.SQLSERVER_EGRESS_RULE` for the SQL Server host and the driver-download hosts. It does not add domain controllers. `SET VALUE_LIST` replaces the whole list, so read the rule first and keep every host already on it:

```sql
DESC NETWORK RULE <metadata_database>.PUBLIC.SQLSERVER_EGRESS_RULE;
```

A new SQL Server rule contains the SQL host and port plus `packages.microsoft.com:443`, `pmc-geofence.trafficmanager.net:443`, `deb.debian.org:80`, and `deb.debian.org:443`. Use the live `VALUE_LIST` from `DESC`. Add `'<domain-controller-fqdn>:88'` for each domain controller:

```sql
ALTER NETWORK RULE <metadata_database>.PUBLIC.SQLSERVER_EGRESS_RULE SET
  VALUE_LIST = (
    '<sql-server-fqdn>:<port>',
    'packages.microsoft.com:443',
    'pmc-geofence.trafficmanager.net:443',
    'deb.debian.org:80',
    'deb.debian.org:443',
    '<domain-controller-fqdn>:88'
  );
```

A custom service name prefixes the rule the same way it prefixes the secrets.

On a public `HOST_PORT` rule, Snowflake can reject TCP port 88 with error `001435` and the text `unresolvable host name`. When that happens, publish the KDC on TCP 443, forward that port to TCP 88 on the domain controller, set the `kdc` port in `krb5.conf` to `443`, replace `DEW_KERBEROS_KRB5_CONF` with that file (worksheet or `snow sql --enable-templating NONE`), and put port `443` on the rule instead of `88`. A private `PRIVATE_HOST_PORT` rule can still use port 88.

Allow the Snowflake egress ranges on the SQL Server host and the domain controllers. Addresses can change within the published prefix. Do not open the source network to every address:

```sql
SELECT SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES();
```

## Resume and check

If setup finished before the domain controllers were on the rule, the container exits before the agent starts. Those errors name the missing principal, keytab, or `krb5.conf`. They do not print secret contents. After the rule includes the domain controllers:

```bash
scai data worker start
```

Check the service log for `Kerberos ticket acquired`. A missing principal, keytab, or `krb5.conf` is fixed in the secret or the profile, then start again.

## CHECKPOINT

- [ ] Profile has `auth_method = "windows"` and `kerberos_principal` set to the client account
- [ ] `DEW_KERBEROS_KEYTAB` and `DEW_KERBEROS_KRB5_CONF` exist; no SQL password secret was created for this connection
- [ ] `scai data worker setup` finished and named both keytab secrets
- [ ] The network rule lists the SQL Server host, the driver-download hosts, and every domain controller
- [ ] The service log shows `Kerberos ticket acquired`, or the service is READY after that rule change

Return to the SPCS worker skill at Step 5.
