output "network_id" { value = google_compute_network.vpc.id }
output "network_name" { value = google_compute_network.vpc.name }
output "subnet_name" { value = google_compute_subnetwork.gke.name }
output "pods_range_name" { value = "pods" }
output "services_range_name" { value = "services" }
output "psa_connection" { value = google_service_networking_connection.psa.id }
output "psa_cidr" { value = "${google_compute_global_address.psa.address}/${google_compute_global_address.psa.prefix_length}" }
