# Internet edge: static anycast IP, managed TLS certificate and TLS policy.
# The load balancer itself is created by the GKE Gateway controller (Helm chart) and
# attaches to these by name.

resource "google_compute_global_address" "lb" {
  project = var.project_id
  name    = "${var.name}-lb-ip"
}

resource "google_compute_managed_ssl_certificate" "lb" {
  project = var.project_id
  name    = "${var.name}-cert"
  managed { domains = [var.domain] }
}

resource "google_compute_ssl_policy" "modern" {
  project         = var.project_id
  name            = "${var.name}-tls12-modern"
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"
}
