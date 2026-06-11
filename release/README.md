# TrendPulse — release bundle (operator runbook)

Self-contained production deployment bundle. On the host you work **only** from
this directory: `make -C release <target>`. The bundle never references
`development/` or the root `Makefile`.

Orchestration is **Docker Swarm** (single-node): `docker stack deploy` is
declarative and idempotent (re-deploy = diff-convergence, not re-up), with
rolling updates + auto-rollback on failed healthchecks.

> In normal operation you do **not** run these targets by hand — `make deploy`
> from the repo root (Ansible) drives the whole flow. This runbook is for
> disaster recovery, debugging, and understanding the contract.

> **First deploy prerequisite:** `make deploy` enforces strict host-key checking
> (`ANSIBLE_HOST_KEY_CHECKING=True`). Add the VPS host key to `~/.ssh/known_hosts`
> before the first run: `ssh-keyscan -H <VPS_IP> >> ~/.ssh/known_hosts`
> (the IP comes from `terraform output` or your inventory/prod.yml).

## Layout

| Path | What |
|------|------|
| `Makefile` | operator entry point (`help`, `validate`, `render`, `deploy`, `deploy-wait`, `down`, `status`, `logs`, `smoke`, `backup-now`, `restore-check`) |
| `version.env` | **pinned** prod image tags (committed). `${APP_VERSION}` is set by Ansible at deploy. No `latest` anywhere. |
| `docker-compose.yml` | top assembly — `include:` of `compose/*` + `provisioning/*`, overlay networks |
| `compose/*.yml` | per-service fragments with swarm `deploy:` blocks |
| `provisioning/` | pgvector + migration swarm jobs; prod nginx envsubst template |
| `env/` | **gitignored** — rendered by Ansible (`deploy.env` non-secret, `sensitive.env` secrets) |
| `deployment.example/` | committed templates documenting every env key |
| `scripts/` | `pg_backup.sh`, `pg_restore_check.sh`, `smoke.sh` |

All files here are **static** except `env/`. The Ansible `env` role renders
`env/deploy.env` + `env/sensitive.env` from `group_vars` + the decrypted vault
(pattern: operators touch only `env/`). For a manual render, copy the templates:

```sh
cp deployment.example/deploy.env.example    env/deploy.env
cp deployment.example/sensitive.env.example env/sensitive.env
# fill the placeholders, then:
make -C release validate render
```

## Deploy flow (what `make deploy` runs)

```
render  =  docker compose --env-file version.env --env-file env/deploy.env \
             --env-file env/sensitive.env -f docker-compose.yml config \
           | sed '/^name:/d'                       # strip top-level name:
           | docker stack deploy --compose-file -   # over stdin — secrets never on disk
               --detach=false                       # wait for convergence, non-zero on fail
               --resolve-image never                # local images, don't pull from Hub
               trendpulse
```

`compose config` expands `include:`, inlines `env_file:` into `environment:`, and
interpolates `${...}`. `docker stack deploy` ignores `include:`/`env_file:`/
`build:`/`depends_on.condition`, which is **exactly why** the deploy must go
through `render` — never `docker stack deploy -c docker-compose.yml` directly
(that would fail on `include:`).

After deploy, `deploy-wait` polls `docker stack services` until every replicated
service is running and both provisioning jobs (`pg_vector_provisioner`,
`migration_runner`) report Complete, failing fast with `docker stack ps` output
if a job Failed or the timeout (`DEPLOY_WAIT_TIMEOUT`, default 300s) elapses.

## Update sequence

1. Bump `version.env` `APP_VERSION` to the new release tag (or let Ansible pass
   `-e app_version=vX.Y.Z`), and copy `env/` from the previous release.
2. Perform any one-time steps listed in `RELEASE.md` for the target version.
3. `make -C release deploy && make -C release deploy-wait`.

⚠️ **Changed an env value → run `make deploy`, NOT a service restart.** A restart
reuses the spec from the last `stack deploy`; only a re-deploy re-renders env.

## Validation (offline)

`make -C release validate` checks: env files present, Docker up, Swarm active —
each failure prints a human-readable hint. `make -C release render` emits the
rendered stack YAML; validate it parses with:

```sh
make -C release render | docker compose -f - config -q   # exits 0 if valid
```

(`docker stack deploy --dry-run` does not exist; this is the validation method.)

## Backups (TASK-034)

- `make -C release backup-now` — `pg_dump -Fc` → S3 (joins the live
  `trendpulse_postgres_net` overlay). Installed as a daily cron by the Ansible
  `backup` role.
- `make -C release restore-check` — pull the latest dump into a throwaway PG and
  smoke-check it (PASS/FAIL). No docker socket, fully isolated.

## TLS

Certs are issued on the host by the Ansible `tls` role (certbot) and bind-mounted
read-only into the nginx service at `/etc/letsencrypt`. The prod nginx config
(`provisioning/nginx/templates/nginx.conf.template`) listens on 443 with HSTS +
security headers and 301-redirects 80 → 443. `${DOMAIN}` is substituted by the
nginx image's envsubst at container start. Renewal runs via a systemd timer whose
`--deploy-hook` does `docker service update --force trendpulse_nginx`.
