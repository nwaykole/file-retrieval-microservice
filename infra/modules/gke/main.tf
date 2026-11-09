# Regional GKE Autopilot cluster.
# Why Autopilot: Google runs the nodes (patching, hardening, bin-packing), pods are billed per
# request, and secure defaults (Workload Identity, Shielded nodes, Dataplane V2 / NetworkPolicy,
# no privileged pods) are enforced. Regional = control plane + nodes spread over 3 zones.

resource "google_container_cluster" "this" {
  project  = var.project_id
  name     = var.name
  location = var.region # regional, not zonal: survives a zone outage

  enable_autopilot    = true
  deletion_protection = var.deletion_protection
  network             = var.network_name
  subnetwork          = var.subnet_name

  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }

  private_cluster_config {
    enable_private_nodes    = true  # nodes have no public IPs
    enable_private_endpoint = false # public endpoint, but locked to authorised CIDRs below
    master_global_access_config { enabled = true }
  }

  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.master_authorized_cidrs
      content {
        cidr_block   = cidr_blocks.value
        display_name = "authorised-${cidr_blocks.key}"
      }
    }
  }

  release_channel { channel = "REGULAR" }

  gateway_api_config { channel = "CHANNEL_STANDARD" } # Gateway API -> global external ALB

  security_posture_config {
    mode               = "BASIC"
    vulnerability_mode = "VULNERABILITY_BASIC" # workload CVE scanning
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus { enabled = true } # scrapes the app's /metrics via PodMonitoring
  }

  logging_config { enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"] }

  maintenance_policy {
    recurring_window {
      start_time = "2026-01-01T02:00:00Z"
      end_time   = "2026-01-01T06:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=SA,SU" # upgrades only in low-traffic windows
    }
  }
}
