# Architecture: what each piece does and why

Diagram: [`architecture-diagram.html`](architecture-diagram.html) (open it in a browser).

## Design goals

Keep it simple, use managed services, and make every part survive the loss of one zone.
Anything not needed to meet the core requirements (6k req/s, plus success-rate and latency
SLOs) is listed under "Future improvements" instead of being built now. The brief asks for
99.99%; this single-region design targets 99.9%. The README section "Capacity and SLOs"
explains why and what 99.99% would need.

## Changes from the starting diagram

| Starting diagram | Problem | Changed to |
|---|---|---|
| HTTP traffic | Not encrypted | HTTPS load balancer |
| Cluster Ingress | Fine, but older API with fewer options | Gateway API (creates the same Google load balancer) |
| One pod | One failure takes the service down; can't handle 6k req/s | 30–100 pods spread over 3 zones |
| Database pod | We'd have to run failover, backups and upgrades ourselves | Cloud SQL with high availability |
| Compute Disk | Mounts read-write on one node in one zone only | Cloud Storage bucket |

## Each component

**HTTPS load balancer.** The single public entry point. It holds the TLS certificate, checks
which pods are healthy and spreads requests across all three zones. It is a Google-managed
global service, so it scales well beyond 6k req/s without tuning.

**GKE Autopilot cluster (regional).** Runs our containers. Regional means the control plane
and nodes are spread over three zones. Autopilot means Google creates, patches and sizes the
nodes; we only describe pods. Nodes have no public IPs.

**file-service pods.** The application. Stateless, so any pod can serve any request. An
autoscaler keeps 30–100 running based on CPU, and they are spread evenly over the three
zones so a zone failure loses at most a third.

**Authentication.** Customers log in with a username and password (`POST /auth/login`).
There is no JWT and no external identity provider. Passwords are stored as scrypt hashes.
A successful login sets an opaque, random session cookie (HttpOnly, Secure, SameSite=Lax,
12 hours), and the database stores only the cookie's SHA-256 hash. Every request looks up the
session to find the customer id, and logout deletes the session on the server. An
administrator creates accounts; there is no self sign-up.

**Cloud SQL for PostgreSQL (high availability).** Stores customer accounts, login sessions
and file details (owner, name, type, size, status). Lets the service check "is this session
valid?" and "does this customer own this file?" with indexed queries that take a few
milliseconds. High availability keeps a standby copy in a second zone and
fails over automatically. Private IP only; the app logs in with its Google identity, so
there is no database password.

**Cloud Storage bucket.** Stores the file content. Data is automatically spread across
zones, versioned, and can never be made public. For large files the service creates a
signed link that works for 5 minutes, so customers download straight from Cloud Storage.

**Cloud Monitoring and Logging.** Measures the success-rate and latency targets at the load
balancer, alerts when we are using up the error budget too fast, collects app metrics and
logs, and runs an uptime check from outside.

**Supporting pieces.** A private VPC network with Cloud NAT (so private nodes can reach the
internet for updates), Artifact Registry for container images, and a Google service account
for the app bound to its Kubernetes service account (Workload Identity, so no key files).

## Common questions

**Why both a database and a bucket?** They do different jobs. The bucket stores the bytes;
the database stores facts about them. Checking ownership, listing a customer's files sorted
by date, or hiding a deleted file is one fast query in Postgres. Doing the same with bucket
listings is slower and limited. A simpler v0 could skip the database and use object paths
like `customer-id/file-id`, but listing, status and future features (sharing, scanning)
would soon need a database. The starting diagram also included one.

**Do we need network endpoint groups (NEGs)?** We don't create them ourselves. When the
Gateway creates the load balancer on GKE, it automatically registers pod IPs in NEGs, so
traffic goes straight to a pod instead of first landing on a node and being forwarded. That
removes an extra hop and gives more accurate health checks. It's the default; nothing extra
to manage.

**Why no Pub/Sub?** Downloads are synchronous, so v1 doesn't need a queue. Pub/Sub becomes
useful when uploads arrive: Cloud Storage would publish a "new file" event, and worker pods
would virus-scan it and mark it available, without slowing downloads. That is listed as the
first future improvement and answers the brief's "async workload patterns" question.

**Why GKE and not Cloud Run?** For one stateless API, Cloud Run would be simpler. I used GKE
because the brief's diagram is built on it and a platform team usually runs many services
on a shared cluster.

## Trade-offs

| Choice | Alternative | Reason / cost |
|---|---|---|
| Signed link for large files | Stream every file through the pod | Pods stay fast whatever the file size; customer makes a second request |
| In-memory cache in each pod | Redis | No extra service; each pod has its own copy, up to 30 s out of date |
| GKE Autopilot | GKE Standard | Less to manage; less control over nodes |
| Cloud SQL | Firestore | Familiar SQL and simple queries; must manage connection counts |
| Terraform for cloud, Helm for Kubernetes objects | Terraform `kubernetes` provider | Standard release tooling (rollback, `--atomic`, history); a deploy can't touch the database; no live cluster needed at Terraform plan time |
| Single region | Multi-region | Simpler and cheaper; meets 99.9%, not 99.99% |
| Username/password with server-side sessions | JWTs from an external identity provider | No external dependency; logout takes effect immediately; costs one indexed lookup per request and the service has to protect passwords |

## Future improvements

1. **Upload scanning (async):** Cloud Storage event → Pub/Sub → worker pods virus-scan and
   mark files available, with retries and a dead-letter queue.
2. **Scale reads:** Redis (Memorystore) shared cache or a Cloud SQL read replica.
3. **99.99% availability:** second region, dual-region bucket, cross-region database replica.
4. **Data exfiltration protection:** Private Service Connect and VPC Service Controls.
5. **Supply chain:** image signing with Binary Authorization.
6. **Safer releases:** GitOps (Argo CD) with canary releases and automatic rollback.
7. **Observability:** distributed tracing, dashboards as code.
8. **Tenant isolation layer 2:** Postgres row-level security.
9. **Identity:** log in through an external identity provider (OIDC/JWT), and add Cloud Armor
   with per-IP rate limits on `/auth/login`.
