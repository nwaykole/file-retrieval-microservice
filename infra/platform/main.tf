# Platform stack: everything that must exist before Kubernetes objects can be applied.
# Kubernetes objects are deployed separately by the Helm chart in infra/helm/file-service:
# platform changes are rarer and higher-risk than deploys, and app releases shouldn't need
# Terraform state access to the database or network.

locals {
  name = "${var.prefix}-${var.environment}"
  apis = [
    "container.googleapis.com", "compute.googleapis.com", "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com", "storage.googleapis.com",
    "monitoring.googleapis.com", "logging.googleapis.com", "cloudtrace.googleapis.com",
    "iamcredentials.googleapis.com", "artifactregistry.googleapis.com",
    "containerscanning.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

module "network" {
  source     = "../modules/network"
  project_id = var.project_id
  region     = var.region
  name       = local.name
  depends_on = [google_project_service.apis]
}

module "gke" {
  source                  = "../modules/gke"
  project_id              = var.project_id
  region                  = var.region
  name                    = local.name
  network_name            = module.network.network_name
  subnet_name             = module.network.subnet_name
  pods_range_name         = module.network.pods_range_name
  services_range_name     = module.network.services_range_name
  master_authorized_cidrs = var.master_authorized_cidrs
  deletion_protection     = var.deletion_protection
}

module "data" {
  source              = "../modules/data"
  project_id          = var.project_id
  region              = var.region
  name                = local.name
  network_id          = module.network.network_id
  psa_connection      = module.network.psa_connection
  bucket_location     = var.bucket_location
  deletion_protection = var.deletion_protection
}

module "edge" {
  source      = "../modules/edge"
  project_id  = var.project_id
  name        = local.name
  domain      = var.domain
  depends_on  = [google_project_service.apis]
}

module "observability" {
  source            = "../modules/observability"
  project_id        = var.project_id
  name              = local.name
  domain            = var.domain
  alert_email       = var.alert_email
  availability_goal = var.availability_goal
  latency_goal      = var.latency_goal
  depends_on        = [google_project_service.apis]
}

# ---------------- Identity: least-privilege Google SA bound to the K8s SA ----------------
resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "${local.name}-images"
  format        = "DOCKER"
  docker_config { immutable_tags = true } # a tag can't be silently re-pointed
  depends_on = [google_project_service.apis]
}

resource "google_service_account" "file_service" {
  project      = var.project_id
  account_id   = "${local.name}-files"
  display_name = "file-service workload identity"
}

# Workload Identity: only the KSA files/file-service can act as this GSA. No JSON keys anywhere.
resource "google_service_account_iam_member" "wi" {
  service_account_id = google_service_account.file_service.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.k8s_namespace}/file-service]"
}

# Needed to V4-sign URLs via IAM signBlob (the pod signs as itself).
resource "google_service_account_iam_member" "self_sign" {
  service_account_id = google_service_account.file_service.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = google_service_account.file_service.member
}

# Read-only, scoped to ONE bucket (not project-wide storage access).
resource "google_storage_bucket_iam_member" "reader" {
  bucket = module.data.bucket_name
  role   = "roles/storage.objectViewer"
  member = google_service_account.file_service.member
}

resource "google_project_iam_member" "sql" {
  for_each = toset(["roles/cloudsql.client", "roles/cloudsql.instanceUser", "roles/cloudtrace.agent"])
  project  = var.project_id
  role     = each.value
  member   = google_service_account.file_service.member
}

# IAM database user: the GSA logs into Postgres with a short-lived token (no stored password).
resource "google_sql_user" "file_service" {
  project  = var.project_id
  instance = module.data.sql_instance_name
  name     = trimsuffix(google_service_account.file_service.email, ".gserviceaccount.com")
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}
