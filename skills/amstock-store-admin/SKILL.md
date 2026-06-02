---
name: amstock-store-admin
description: Manage AMStock local store users with the admin token. Use when the user wants to create, list, rename, activate, or deactivate local portfolio ledger users. Admin commands require the hardcoded token configured in `src/amstock/config.py`.
---

# AMStock Store Admin

Use `amstock_store admin user ...` from the AMStock project root. These commands manage
local ledger users only. They do not authenticate OS users or grant application sessions.

Admin commands require `--admin-token`. The configured token is hardcoded in
`src/amstock/config.py` as `DEFAULT_STORE_ADMIN_TOKEN`.

## Commands

Create a local ledger user:

```powershell
uv run amstock_store admin user create --username alice --display-name 张三 --admin-token amstock-store-admin-token
```

List users:

```powershell
uv run amstock_store admin user list --admin-token amstock-store-admin-token
uv run amstock_store admin user list --include-inactive --admin-token amstock-store-admin-token
```

Rename a user's display name:

```powershell
uv run amstock_store admin user rename --username alice --display-name 张三丰 --admin-token amstock-store-admin-token
```

Deactivate or reactivate a user:

```powershell
uv run amstock_store admin user deactivate --username alice --admin-token amstock-store-admin-token
uv run amstock_store admin user activate --username alice --admin-token amstock-store-admin-token
```

The CLI emits one JSON object. Failed admin-token checks emit `ok: false` and exit non-zero.
