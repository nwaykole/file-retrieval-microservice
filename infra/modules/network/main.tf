# Private VPC for GKE + managed data services. No public IPs on nodes; egress via Cloud NAT.

resource "google_compute_network" "vpc" {
  project                         = var.project_id
  name                            = "${var.name}-vpc"
  auto_create_subnetworks         = false
  routing_mode                    = "REGIONAL"
  delete_default_routes_on_create = false
}

resource "google_compute_subnetwork" "gke" {
  project                  = var.project_id
  name                     = "${var.name}-gke"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.nodes_cidr
  private_ip_google_access = true # reach Google APIs (GCS, IAM) without public IPs

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }

  log_config { # VPC flow logs: network forensics / anomaly detection
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Proxy-only subnet is not needed for a *global* external LB, so it is intentionally omitted.

resource "google_compute_router" "router" {
  project = var.project_id
  name    = "${var.name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  project                            = var.project_id
  name                               = "${var.name}-nat"
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  min_ports_per_vm                   = 1024 # high request rate -> avoid SNAT port exhaustion
  enable_dynamic_port_allocation     = true
  max_ports_per_vm                   = 8192
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Private Service Access: Cloud SQL gets a private IP inside this VPC, no public endpoint.
resource "google_compute_global_address" "psa" {
  project       = var.project_id
  name          = "${var.name}-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = var.psa_base_address # fixed so NetworkPolicy can allow exactly this range
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa.name]

  # On destroy, drop the connection from state instead of calling the Service Networking
  # delete API. That API fails with "Producer services ... are still using this connection"
  # for a while after Cloud SQL is deleted, because Google releases the tenant side late.
  # The VPC peering is torn down when the network itself is deleted.
  deletion_policy = "ABANDON"
}
