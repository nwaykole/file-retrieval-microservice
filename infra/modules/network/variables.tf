variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }

variable "nodes_cidr" {
  type    = string
  default = "10.10.0.0/20"
}

variable "pods_cidr" {
  type    = string
  default = "10.20.0.0/14"
}

variable "services_cidr" {
  type    = string
  default = "10.24.0.0/20"
}

variable "psa_base_address" {
  type    = string
  default = "10.30.0.0"
}
