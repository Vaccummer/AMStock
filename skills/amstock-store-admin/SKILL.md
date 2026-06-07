---
name: amstock-store-admin
description: Manage AMStock local store users with the admin token. Use when the user wants to create, list, rename, activate, or deactivate local portfolio ledger users. Admin commands require the token configured in `AMSTOCK_ROOT/config/cli.toml`.
---

# AMStock Store Admin

Use `uv run amstock portfolio admin user ...` from the AMStock project root. These commands manage
local ledger users only. They do not authenticate OS users or grant application sessions.

Admin commands require `--admin-token`. The configured token is read from
`AMSTOCK_ROOT/config/cli.toml`.

`AMSTOCK_ROOT` must be set. If it is missing, cannot be created as a directory, or
`config/cli.toml` is missing, the CLI exits with a JSON configuration error.

Example config:

```toml
[database]
path = "data/amstock.sqlite3"

[store]
admin_token = "amstock-store-admin-token"
```

`database.path` may be relative. Relative database paths are resolved from `AMSTOCK_ROOT`.

## Commands

Create a local ledger user:

```powershell
uv run amstock portfolio admin user create --username alice --display-name 张三 --admin-token amstock-store-admin-token
```

List users:

```powershell
uv run amstock portfolio admin user list --admin-token amstock-store-admin-token
uv run amstock portfolio admin user list --include-inactive --admin-token amstock-store-admin-token
```

Rename a user's display name:

```powershell
uv run amstock portfolio admin user rename --username alice --display-name 张三丰 --admin-token amstock-store-admin-token
```

Deactivate or reactivate a user:

```powershell
uv run amstock portfolio admin user deactivate --username alice --admin-token amstock-store-admin-token
uv run amstock portfolio admin user activate --username alice --admin-token amstock-store-admin-token
```

The CLI emits one JSON object. Failed admin-token checks emit `ok: false` and exit non-zero. `amstock_store` remains available as a compatibility entry point.
