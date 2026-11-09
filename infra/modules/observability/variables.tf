variable "project_id" { type = string }
variable "name" { type = string }
variable "domain" { type = string }
variable "alert_email" { type = string }

variable "namespace" {
  type    = string
  default = "files"
}

variable "gateway_name" {
  type    = string
  default = "files-gateway"
}

variable "availability_goal" {
  type    = number
  default = 0.999
  validation {
    condition     = var.availability_goal > 0.9 && var.availability_goal < 1
    error_message = "Goal must be between 0.9 and 1 (exclusive)."
  }
}

variable "latency_goal" {
  type    = number
  default = 0.999
}

variable "latency_threshold_ms" {
  type    = number
  default = 300
}
