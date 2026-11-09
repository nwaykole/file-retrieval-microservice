output "bucket_name" { value = google_storage_bucket.files.name }
output "sql_connection_name" { value = google_sql_database_instance.metadata.connection_name }
output "sql_instance_name" { value = google_sql_database_instance.metadata.name }
