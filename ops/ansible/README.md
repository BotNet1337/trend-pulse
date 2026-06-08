# ops/ansible — env source of truth (skeleton)

Per ADR-005 §4–5, **Ansible is the single source of truth** for environment
variables, both locally and on prod. `make ansible-unpack` materializes:

- `development/env/deploy.env`  ← `group_vars/all.yml`   (non-secret defaults, committed)
- `development/env/sensitive.env` ← `group_vars/vault.yml` (secrets, **gitignored**)

## task-001 (now)

A dependency-free stub renderer (`development/scripts/ansible-unpack.sh`) reads the
two `group_vars` YAML files and writes the env files — no `ansible`/`ansible-vault`
binary required. `vault.yml` holds plaintext placeholders.

## task-012 (later)

- Real playbooks + `inventory.ini` hosts
- `vault.yml` encrypted with `ansible-vault`; `ansible-unpack` decrypts it
- Same files delivered to the VPS during deploy
