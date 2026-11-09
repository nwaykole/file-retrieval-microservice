# Two stores, two jobs:
#  - Cloud Storage holds the file CONTENT (the bytes).
#  - Cloud SQL holds the file METADATA (who owns it, name, type, size, status) so the
#    service can answer "does this customer own this file?" with one fast indexed query.
#
# Replaces the starting diagram's "Database Pod" and "Google Compute Disk":
#  - A Compute Disk can only be mounted read-write by one node in one zone, so many pods
#    can't share it and a zone outage takes it away. Cloud Storage has neither problem.
#  - A database in a pod means we own replication, failover and backups. Cloud SQL does that.

resource "random_id" "suffix" {
  byte_length = 3
}

# ---------------- File content ----------------
resource "google_storage_bucket" "files" {
  project                     = var.project_id
  name                        = "${var.name}-files-${random_id.suffix.hex}"
  location                    = var.bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true       # permissions via IAM only, no per-object ACLs
  public_access_prevention    = "enforced" # the bucket can never be made public
  force_destroy               = false

  versioning { enabled = true } # recover from accidental overwrite or delete

  soft_delete_policy { retention_duration_seconds = 7 * 24 * 3600 }

  lifecycle_rule { # keep at most 3 old versions of each file
    condition {
      num_newer_versions = 3
      with_state         = "ARCHIVED"
    }
    action { type = "Delete" }
  }
}

# ---------------- File metadata ----------------
resource "google_sql_database_instance" "metadata" {
  project             = var.project_id
  name                = "${var.name}-metadata-${random_id.suffix.hex}"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "REGIONAL" # standby in a second zone, automatic failover
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false # private IP only, not reachable from the internet
      private_network = var.network_id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "02:00"
      backup_retention_settings { retained_backups = 14 }
    }

    database_flags {
      name  = "cloudsql.iam_authentication" # app logs in with its Google identity, no password
      value = "on"
    }

    insights_config { query_insights_enabled = true }
  }
  depends_on = [var.psa_connection]
}

resource "google_sql_database" "files" {
  project  = var.project_id
  name     = "files"
  instance = google_sql_database_instance.metadata.name
}
