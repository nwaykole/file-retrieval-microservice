variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "network_name" { type = string }
variable "subnet_name" { type = string }
variable "pods_range_name" { type = string }
variable "services_range_name" { type = string }

variable "master_authorized_cidrs" {
  description = "CIDRs allowed to reach the Kubernetes API (CI runners, admin VPN)."
  type        = list(string)
  validation {
    condition     = !contains(var.master_authorized_cidrs, "0.0.0.0/0")
    error_message = "The control plane must not be open to the internet."
  }
}

variable "deletion_protection" {
  type    = bool
  default = true
}
