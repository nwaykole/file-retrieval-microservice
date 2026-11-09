output "cluster_name" { value = module.gke.name }
output "cluster_location" { value = module.gke.location }
output "lb_ip_address" { value = module.edge.ip_address }
output "lb_ip_name" { value = module.edge.ip_name }
output "certificate_name" { value = module.edge.certificate_name }
output "ssl_policy_name" { value = module.edge.ssl_policy_name }
output "bucket_name" { value = module.data.bucket_name }
output "sql_connection_name" { value = module.data.sql_connection_name }
output "file_service_gsa" { value = google_service_account.file_service.email }
output "db_iam_user" { value = google_sql_user.file_service.name }
output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
output "psa_cidr" { value = module.network.psa_cidr }
