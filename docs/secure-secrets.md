# Secure secret profiles

Agent skills should be reusable without publishing a user's infrastructure or loading every credential into the agent process. This guide defines the recommended boundary between a public skill, a private local profile, and a secret manager.

## Core rules

- A public skill documents only its generic runtime inputs. It must not bundle user-specific profiles, hosts, usernames, vault names, item names, or secret references.
- Ask which secret manager the user prefers before configuring credentials. Proton Pass is the author's method, not a requirement.
- Inject only the selected profile into one child process. Do not export all secrets into the shell or the long-lived agent environment.
- Never pass secrets as CLI arguments or print environment variables, resolved references, session contents, or connection strings.
- Use least-privilege accounts and keep TLS verification enabled. Client-side safety checks are not an authorization boundary.

## Private local profiles

Keep local profiles outside the installed skill, for example:

```text
~/.config/agent-skills/profiles/<skill>/<profile>
```

Profile names and formats belong to the user. Treat the whole directory as private even when it contains only references:

```text
~/.config/agent-skills/          0700
profiles/                        0700
profile files                    0600
```

A profile maps one of the user's systems to the generic inputs already supported by the skill. A PostgreSQL profile might supply `PGHOST`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`; it must not add organization-specific names to the public skill.

### Static targets

A static profile records one explicit target and the references needed for that target. Only that profile is injected for a run.

### Dynamic targets

A private profile may define a hostname template such as:

```text
db-{environment}.{tenant}.example.net
```

The agent must:

1. ask for missing placeholder values;
2. accept only declared placeholders and allowlisted or strictly validated values;
3. reject shell syntax, paths, URL schemes, whitespace, and control characters;
4. build and validate the non-secret target without `eval`;
5. show a new or sensitive target before connecting;
6. inject credentials only after the target is valid.

Never copy the author's host patterns or infer a user's infrastructure from examples.

If an application needs a derived connection URL or DSN, build it at runtime from validated target fields and the selected credentials using a proper URL/DSN encoder, not string concatenation. The derived value is itself a secret: pass it only in the child environment and never print, persist, or place it in CLI arguments.

## Secret-manager-neutral execution

Use the user's chosen manager and its official process-scoped execution mechanism. Reference syntax and commands differ between Proton Pass, Bitwarden, 1Password, and other products; do not pretend they are interchangeable.

If the manager has no safe one-process runner, explain the available options and risks before creating a wrapper or temporary file. Do not silently fall back to plaintext `.env` files.

## Author's method: Proton Pass

The author keeps one pointer file per local profile:

```env
PGHOST=db.example.net
PGDATABASE=analytics
PGUSER=pass://<vault>/<item>/<field>
PGPASSWORD=pass://<vault>/<item>/<field>
```

It is executed only for the selected child process:

```bash
pass-cli run \
  --env-file ~/.config/agent-skills/profiles/postgres-readonly/<profile>.env \
  -- <skill-command>
```

Keep output masking enabled. Do not resolve pointers into another file or preload them into the agent's environment.

## Agent setup protocol

When a user asks to configure a skill:

1. inspect the skill's generic configuration;
2. ask which secret manager and local profiles the user wants;
3. ask whether each target is static or dynamic; never guess names, hosts, or templates;
4. show the proposed paths, mappings, and permissions without resolved values;
5. obtain approval before creating files or changing a vault;
6. inject only the selected profile into the skill process;
7. verify only that required values are present, never their contents or length;
8. report missing variable names without dumping manager errors that may contain sensitive metadata.

If the user says **use the author's method**, offer the per-profile Proton Pass layout above. Otherwise use the user's manager.

## Session files and private keys

OAuth sessions, cookies, private keys, and application session databases are credential files, not ordinary environment variables. Store them in the platform's private user-data directory with `0700` directories and `0600` files. Never commit, print, or upload them. Materialize a temporary file from a secret manager only when the application requires it, and remove it reliably after use.

## Public examples

Use placeholders and reserved domains such as `example.net`. Before publishing, scan for real tokens, usernames, local paths, private domains, profile names, vault/item names, session files, and generated artifacts.
