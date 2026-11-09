# `terraform test` with a mocked provider: runs in CI with no cloud credentials and no cost.
# Asserts the security guardrails we never want to regress.

mock_provider "google" {}

variables {
  project_id              = "test-project"
  region                  = "europe-west2"
  name                    = "fs-test"
  network_name            = "vpc"
  subnet_name             = "subnet"
  pods_range_name         = "pods"
  services_range_name     = "services"
  master_authorized_cidrs = ["203.0.113.0/24"]
}

run "cluster_is_private_regional_autopilot" {
  command = plan

  assert {
    condition     = google_container_cluster.this.enable_autopilot == true
    error_message = "Cluster must be Autopilot."
  }
  assert {
    condition     = google_container_cluster.this.location == "europe-west2"
    error_message = "Cluster must be regional (multi-zone), not zonal."
  }
  assert {
    condition     = google_container_cluster.this.private_cluster_config[0].enable_private_nodes == true
    error_message = "Nodes must not have public IPs."
  }
}

run "rejects_open_control_plane" {
  command = plan
  variables {
    master_authorized_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.master_authorized_cidrs]
}
