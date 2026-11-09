{{/*
The app name is fixed: the platform stack binds Workload Identity to the KSA
<namespace>/file-service, so renaming it per release would break GCP access.
*/}}
{{- define "file-service.name" -}}file-service{{- end -}}

{{- define "file-service.isApp" -}}
{{- if eq .Values.appMode "file-service" -}}true{{- end -}}
{{- end -}}

{{/* distroless nonroot | nginx-unprivileged */}}
{{- define "file-service.runAsUser" -}}
{{- if include "file-service.isApp" . -}}65532{{- else -}}101{{- end -}}
{{- end -}}

{{/* Selector labels: unchanged from the Terraform stack (selectors are immutable). */}}
{{- define "file-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "file-service.name" . }}
{{- end -}}

{{- define "file-service.labels" -}}
{{ include "file-service.selectorLabels" . }}
app.kubernetes.io/part-of: file-platform
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* Service backendRef / policy targetRef. */}}
{{- define "file-service.targetRef" -}}
group: ""
kind: Service
name: {{ include "file-service.name" . }}
{{- end -}}
