output "ip_name" { value = google_compute_global_address.lb.name }
output "ip_address" { value = google_compute_global_address.lb.address }
output "certificate_name" { value = google_compute_managed_ssl_certificate.lb.name }
output "ssl_policy_name" { value = google_compute_ssl_policy.modern.name }
