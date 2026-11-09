# Testing the file service

The service is tested at four levels. Each level catches a different kind of mistake, and the
cheap ones run first.

| Level | What it proves | Backends | Command (from `app/`) | When it runs |
|---|---|---|---|---|
| Unit | API logic: login, the login page and its security headers, tenant isolation, input validation, timeouts, probes, metrics | In-memory fakes | `pytest` | Every commit, ~2 s |
| **Integration** | The code works against **real** Postgres and the Cloud Storage API: SQL, schema, grants, sessions, file bytes | Postgres 16 + GCS emulator in Docker | `pytest -m integration` | Every commit, ~30 s |
| Smoke | The deployed stack answers over HTTPS | GKE + Cloud SQL + GCS | `curl -I https://<domain>/` | After each deploy |
| Load / SLO | 6k req/s within the latency and error SLOs | GKE + Cloud SQL + GCS | `k6 run loadtest/k6-slo.js` | Before promoting a release |

## Why integration tests

Unit tests swap Postgres and Cloud Storage for in-memory fakes. That keeps them fast, but the
fakes can't catch these mistakes:

* SQL that is wrong, or doesn't match `db/schema.sql` (column names, ordering, the status filter).
* Missing **database grants**. In the cloud, the app logs in as the Cloud SQL IAM user. That
  user can't read a table until someone grants it access, and the health check still passes
  without the grant.
* Session expiry and cascade deletes, which are enforced by Postgres and not by Python.
* How the Google Cloud Storage client behaves: downloads, and errors for missing objects.
* The whole request path wired together: cookie, then session lookup, then metadata, then bytes.

## What the integration tests cover

Files are in `app/tests/integration/`.

| File | Tests | Checks |
|---|---|---|
| `test_postgres_repository.py` | 14 | Lookups are scoped to the customer. Listing is newest first and returns only `available` files. The schema rejects an unknown status. The full session lifecycle works. Expired sessions are rejected and purged. Deleting a user revokes their sessions. **Least privilege:** the app role can't insert, update or delete files or accounts, or drop tables. |
| `test_gcs_storage.py` | 3 | Reads real object bytes, raises `NotFound` for a missing object, and sees the bucket. |
| `test_end_to_end.py` | 5 | Runs the real FastAPI app on Postgres and the GCS emulator. Login, list, download and logout work. A cookie replayed after logout is rejected. Customer A can't read customer B's file. Expired sessions get 401. A missing object returns **503 with Retry-After**, not 500. `/readyz` checks the real database. |

How they're built:

* **The production schema, run as a least-privilege user.** Each test recreates the tables from
  `db/schema.sql`. That file also creates the `file_service_app` role with only the grants the
  service needs. The app then connects as `it_app`, a login role that gets its permissions only
  through `file_service_app`. That's the same way the Cloud SQL IAM user gets them in GCP, so
  a missing grant fails here, before it fails in production.
* **Isolated tests.** Every test gets empty tables and its own new bucket, so the tests don't
  depend on order and can be re-run.
* **Test data is written with admin rights.** The `seed` fixture inserts rows as the Postgres
  superuser and uploads objects to the bucket, the way the upload service or an operator would.
  The code under test only ever uses the restricted role.

## How to run

You need **Docker** (Docker Desktop on Windows or macOS) and **Python 3.11 or newer**.

### Linux / macOS (bash)

```bash
cd app
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,gcp]"

docker compose -f docker-compose.it.yml up -d --wait   # Postgres :55432, GCS emulator :4443
pytest -m integration -v                               # integration tests
pytest                                                 # unit tests
docker compose -f docker-compose.it.yml down -v        # stop and delete the data
```

### Windows (PowerShell)

```powershell
cd app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,gcp]"

docker compose -f docker-compose.it.yml up -d --wait
pytest -m integration -v
pytest
docker compose -f docker-compose.it.yml down -v
```

To run everything at once, use `pytest -m ""`. An empty marker expression turns the default
filter off.

Run a single file or test:

```bash
pytest -m integration tests/integration/test_end_to_end.py -v
pytest -m integration -k tenant -v
```

### Settings

The defaults match `docker-compose.it.yml`. To point the tests at other backends (for example a
CI service container), set these variables:

| Variable | Default |
|---|---|
| `FS_IT_ADMIN_DSN` | `postgresql://postgres:postgres@localhost:55432/files` |
| `FS_IT_APP_DSN` | `postgresql://it_app:it-app-password@localhost:55432/files` |
| `FS_IT_GCS_ENDPOINT` | `http://localhost:4443` |

The tests drop and recreate the `files`, `users` and `sessions` tables, so **never point
them at a real database**.

## In CI

`.github/workflows/ci.yml` has an `integration` job. It starts the same compose file, runs
`pytest -m integration`, and always tears the containers down. The `image` job waits for the
unit and integration jobs, so an image is only built and pushed when both pass.

## What these tests don't cover, and where it is covered

| Not covered here | Why | Covered by |
|---|---|---|
| Signed URLs for large files | Signing calls the IAM signBlob API as the pod's service account, which the emulator can't do | Unit tests (the redirect logic) and the deployed smoke test |
| Cloud SQL IAM login and the Auth Proxy | They need a real GCP identity | The deployment's readiness probe (`/readyz` runs a query) |
| Latency SLOs | Docker on a laptop isn't representative | The k6 load test against the deployed service |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Postgres not reachable at ...` | Start the backends: `docker compose -f docker-compose.it.yml up -d --wait`. Check `docker compose -f docker-compose.it.yml ps`. |
| `GCS emulator not reachable at ...` | Same as above. Check that port 4443 isn't already in use. |
| A port is already in use | Change the host port in `docker-compose.it.yml` and set the matching `FS_IT_*` variable. |
| `ModuleNotFoundError: asyncpg` or `google.cloud` | Install the `gcp` extra: `pip install -e ".[dev,gcp]"`. |
| `pytest -m integration` reports "0 selected" | Run it from `app/`, so pytest finds `pyproject.toml`. |

## Applying the grants in GCP

The integration tests prove that `file_service_app` has the right permissions. In each
environment, after applying `db/schema.sql` as the `postgres` user, give that role to the
service's IAM database user (from `terraform output db_iam_user`):

```sql
GRANT file_service_app TO "fs-dev-files@<project>.iam";
```
