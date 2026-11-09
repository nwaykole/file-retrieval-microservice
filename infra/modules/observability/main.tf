# SLOs measured at the load balancer = what customers actually experience (includes
# network, LB, pod and dependency failures). App-level Prometheus metrics are used for
# debugging; the LB view is the source of truth for the error budget.

locals {
  # Gateway-generated LB resources are named gkegw1-<hash>-<namespace>-<gateway>-<hash>
  lb_match = "monitoring.regex.full_match(\".*-${var.namespace}-${var.gateway_name}-.*\")"
  lb_base  = "resource.type=\"https_lb_rule\" AND resource.label.url_map_name=${local.lb_match}"
}

resource "google_monitoring_custom_service" "file_service" {
  project      = var.project_id
  service_id   = "${var.name}-file-service"
  display_name = "File service (${var.name})"
}

resource "google_monitoring_slo" "availability" {
  project             = var.project_id
  service             = google_monitoring_custom_service.file_service.service_id
  slo_id              = "availability"
  display_name        = "${var.availability_goal * 100}% of requests succeed (non-5xx), 28d"
  goal                = var.availability_goal
  rolling_period_days = 28

  request_based_sli {
    good_total_ratio {
      total_service_filter = "${local.lb_base} AND metric.type=\"loadbalancing.googleapis.com/https/request_count\""
      bad_service_filter   = "${local.lb_base} AND metric.type=\"loadbalancing.googleapis.com/https/request_count\" AND metric.label.response_code_class=500"
    }
  }
}

resource "google_monitoring_slo" "latency" {
  project             = var.project_id
  service             = google_monitoring_custom_service.file_service.service_id
  slo_id              = "latency-300ms"
  display_name        = "${var.latency_goal * 100}% of requests < ${var.latency_threshold_ms}ms, 28d"
  goal                = var.latency_goal
  rolling_period_days = 28

  request_based_sli {
    distribution_cut {
      distribution_filter = "${local.lb_base} AND metric.type=\"loadbalancing.googleapis.com/https/total_latencies\""
      range { max = var.latency_threshold_ms }
    }
  }
}

resource "google_monitoring_notification_channel" "oncall" {
  project      = var.project_id
  display_name = "File service on-call"
  type         = "email"
  labels       = { email_address = var.alert_email }
}

# Multi-window burn-rate alerts (Google SRE workbook): page on fast burn, ticket on slow burn.
locals {
  burn_alerts = {
    fast = { window = "3600s", threshold = 14.4, severity = "CRITICAL" } # 2% of budget in 1h
    slow = { window = "21600s", threshold = 6, severity = "WARNING" }    # 5% of budget in 6h
  }
  slos = {
    availability = google_monitoring_slo.availability.name
    latency      = google_monitoring_slo.latency.name
  }
  alert_matrix = { for p in setproduct(keys(local.slos), keys(local.burn_alerts)) : "${p[0]}-${p[1]}" => {
    slo = local.slos[p[0]], cfg = local.burn_alerts[p[1]]
  } }
}

resource "google_monitoring_alert_policy" "burn" {
  for_each     = local.alert_matrix
  project      = var.project_id
  display_name = "file-service ${each.key} SLO burn"
  combiner     = "OR"
  severity     = each.value.cfg.severity
  conditions {
    display_name = "${each.key} burn rate > ${each.value.cfg.threshold}x"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${each.value.slo}\", \"${each.value.cfg.window}\")"
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.cfg.threshold
      duration        = "0s"
    }
  }
  notification_channels = [google_monitoring_notification_channel.oncall.id]
  documentation {
    content   = "Runbook: check LB 5xx by backend, pod restarts, Cloud SQL CPU/connections, GCS errors. Dashboards: GKE workload + Cloud SQL insights."
    mime_type = "text/markdown"
  }
}

# Black-box check from multiple regions: catches DNS/cert/LB issues the app can't see.
resource "google_monitoring_uptime_check_config" "https" {
  project      = var.project_id
  display_name = "file-service /healthz"
  timeout      = "5s"
  period       = "60s"
  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type   = "uptime_url"
    labels = { project_id = var.project_id, host = var.domain }
  }
}
