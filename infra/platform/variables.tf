variable "project_id" { type = string }

variable "region" {
  type    = string
  default = "europe-west2" # London: data residency + latency for UK customers
}

variable "prefix" {
  type    = string
  default = "fs"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "domain" {
  description = "Public hostname, e.g. files.example.com"
  type        = string
}

variable "alert_email" { type = string }

variable "master_authorized_cidrs" {
  type = list(string)
}

variable "bucket_location" {
  type    = string
  default = "EUROPE-WEST2"
}

variable "k8s_namespace" {
  type    = string
  default = "files"
}

variable "availability_goal" {
  type    = number
  default = 0.999
}

variable "latency_goal" {
  type    = number
  default = 0.999
}

variable "deletion_protection" {
  type    = bool
  default = true
}
