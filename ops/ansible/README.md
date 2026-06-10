# ops/ansible — env source of truth + host configuration

Per [ADR-005](../../docs/architecture/adr-005-infra-provisioning-and-secrets.md) §4–5,
**Ansible is the single source of truth** for environment variables, both locally
and on prod. All commands go through the root `Makefile` (CONVENTIONS) — never call
`ansible-playbook` by hand.

## Flow

```
group_vars/all.yml  (non-secret defaults) ─┐
group_vars/prod.yml (prod overrides)        ├─► roles/env (deploy.env.j2)    ─► development/env/deploy.env
vault/sensitive.vault.yml (ENCRYPTED)  ─────┴─► roles/env (sensitive.env.j2) ─► development/env/sensitive.env
                                                                                    │
                                                       compose env_file: [deploy.env, sensitive.env]
```

`make ansible-unpack` runs `playbooks/unpack-env.yml` on localhost
(`connection: local`), rendering both env files into `development/env/`.
`make up` then consumes them.

## Layout

| Path | Purpose |
|---|---|
| `ansible.cfg` | inventory path, `roles_path`, `vault_password_file = .vault-pass` |
| `inventory/hosts.ini` | `local` (localhost) + `prod` (VPS from Terraform `server_ip`, see `ops/terraform/environments/prod`) |
| `site.yml` | top playbook → imports `provision.yml` then `deploy.yml` |
| `playbooks/unpack-env.yml` | **localhost** — render `deploy.env` + decrypt `sensitive.env` into `development/env/` |
| `playbooks/provision.yml` | prod host setup — Docker + system packages |
| `playbooks/deploy.yml` | prod — ship env files + bring the stack up |
| `group_vars/all.yml` | non-secret defaults (DB names, ports, network names, feature flags) |
| `group_vars/prod.yml` | prod overrides (e.g. `auth_cookie_secure: "true"`) |
| `vault/sensitive.vault.yml` | **ansible-vault encrypted** secrets (`vault_*` vars) |
| `roles/env/` | renders the two `KEY=value` env files (`templates/*.env.j2`) |
| `requirements.yml` | Galaxy collections (`community.docker`, `ansible.posix`) |

## Make targets

```bash
make ansible-unpack   # render development/env/{deploy,sensitive}.env
make ansible-lint     # ansible-lint ops/ansible
make ansible-check    # site.yml --syntax-check + unpack-env.yml --check (dry-run)
```

## Vault

Secrets live ONLY in `vault/sensitive.vault.yml`, committed in encrypted
(`$ANSIBLE_VAULT;…`) form. The vault password is read from `.vault-pass`
(**gitignored** — never committed) or `--vault-password-file` /
`ANSIBLE_VAULT_PASSWORD_FILE` on prod/CI.

```bash
# edit / rotate a secret (re-encrypts in place)
ansible-vault edit  --vault-password-file .vault-pass vault/sensitive.vault.yml
# view
ansible-vault view  --vault-password-file .vault-pass vault/sensitive.vault.yml
```

**Rotation:** change the value in the vault → `make ansible-unpack` regenerates
`sensitive.env` → on prod re-run `deploy`. Treat the old value as compromised.

A wrong/missing vault password fails `ansible-unpack` loudly rather than emitting
an empty `sensitive.env`.
