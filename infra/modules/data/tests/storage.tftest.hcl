mock_provider "google" {}
mock_provider "random" {}

variables {
  project_id     = "test-project"
  region         = "europe-west2"
  name           = "fs-test"
  network_id     = "projects/test-project/global/networks/vpc"
  psa_connection = "psa"
}

run "bucket_is_locked_down" {
  command = plan

  assert {
    condition     = google_storage_bucket.files.public_access_prevention == "enforced"
    error_message = "Customer file bucket must enforce public access prevention."
  }
  assert {
    condition     = google_storage_bucket.files.uniform_bucket_level_access == true
    error_message = "Use uniform bucket-level access (IAM only, no ACLs)."
  }
  assert {
    condition     = google_storage_bucket.files.versioning[0].enabled == true
    error_message = "Versioning must be enabled for recovery."
  }
}

run "database_is_private_and_ha" {
  command = plan

  assert {
    condition     = google_sql_database_instance.metadata.settings[0].ip_configuration[0].ipv4_enabled == false
    error_message = "Cloud SQL must not have a public IP."
  }
  assert {
    condition     = google_sql_database_instance.metadata.settings[0].availability_type == "REGIONAL"
    error_message = "Cloud SQL must be HA (regional)."
  }
  assert {
    condition     = google_sql_database_instance.metadata.settings[0].backup_configuration[0].point_in_time_recovery_enabled
    error_message = "PITR must be on."
  }
}
