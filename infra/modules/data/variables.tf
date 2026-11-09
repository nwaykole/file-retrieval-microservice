variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "network_id" { type = string }
variable "psa_connection" { type = string }

variable "bucket_location" {
  type    = string
  default = "EUROPE-WEST2"
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "deletion_protection" {
  type    = bool
  default = true
}
