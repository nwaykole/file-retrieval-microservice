output "name" { value = google_container_cluster.this.name }
output "location" { value = google_container_cluster.this.location }
output "endpoint" {
  value     = google_container_cluster.this.endpoint
  sensitive = true
}
