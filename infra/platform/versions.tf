terraform {
  required_version = ">= 1.7.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state with locking; bucket created once by a bootstrap step (versioned, CMEK).
  backend "gcs" {
    bucket = "backend-file2"
    prefix = "file-service/platform-no-waf"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  default_labels = {
    service     = "file-service"
    environment = var.environment
    managed_by  = "terraform"
  }
}
