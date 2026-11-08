{{- /*
Helpers for the release's own ECR pull secret (see ecr-pull-secret.yaml).
*/ -}}

{{/* Name of the pull secret: ecrPullSecret.name, else <release>-ecr-pull-secret. */}}
{{- define "registryEcr.secretName" -}}
{{- .Values.ecrPullSecret.name | default (printf "%s-ecr-pull-secret" .Release.Name) -}}
{{- end -}}

{{/* Name shared by the refresher ServiceAccount, Role, RoleBinding and CronJob. */}}
{{- define "registryEcr.refresher" -}}
{{ .Release.Name }}-ecr-refresh
{{- end -}}

{{/* ECR registry host (<account>.dkr.ecr.<region>.amazonaws.com); required when the secret is enabled. */}}
{{- define "registryEcr.registry" -}}
{{- $registry := required "ecrPullSecret.registry is required when ecrPullSecret.enabled (<account>.dkr.ecr.<region>.amazonaws.com)" .Values.ecrPullSecret.registry -}}
{{- if not (regexMatch `^[0-9]+\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com$` $registry) -}}
{{- fail (printf "ecrPullSecret.registry %q is not an ECR registry host (<account>.dkr.ecr.<region>.amazonaws.com)" $registry) -}}
{{- end -}}
{{- $registry -}}
{{- end -}}

{{- define "registryEcr.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}-ecr-refresh
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end -}}

{{/* Job spec that fetches an ECR token and writes the pull secret. Takes dict root, serviceAccount. */}}
{{- define "registryEcr.jobSpec" -}}
{{- $v := .root.Values.ecrPullSecret -}}
{{- $registry := include "registryEcr.registry" .root -}}
backoffLimit: 2
activeDeadlineSeconds: 300
template:
  metadata:
    labels:
      app.kubernetes.io/name: {{ .root.Chart.Name }}-ecr-refresh
      app.kubernetes.io/instance: {{ .root.Release.Name }}
  spec:
    serviceAccountName: {{ .serviceAccount }}
    restartPolicy: Never
    initContainers:
      - name: get-token
        image: {{ $v.awsCliImage }}
        command: ["/bin/sh", "-c", "aws ecr get-login-password --region {{ index (splitList "." $registry) 3 }} > /token/ecr"]
        volumeMounts:
          - name: token
            mountPath: /token
    containers:
      - name: write-secret
        image: {{ $v.kubectlImage }}
        command:
          - /bin/sh
          - -c
          - |
            set -eu
            kubectl create secret docker-registry {{ include "registryEcr.secretName" .root }} \
              --namespace {{ .root.Release.Namespace }} \
              --docker-server={{ $registry }} \
              --docker-username=AWS \
              --docker-password="$(cat /token/ecr)" \
              --dry-run=client -o yaml | kubectl apply -f -
{{- range $v.serviceAccounts }}
            kubectl patch serviceaccount {{ . }} \
              --namespace {{ $.root.Release.Namespace }} \
              -p '{"imagePullSecrets":[{"name":"{{ include "registryEcr.secretName" $.root }}"}]}'
{{- end }}
        volumeMounts:
          - name: token
            mountPath: /token
            readOnly: true
    volumes:
      - name: token
        emptyDir:
          medium: Memory
{{- end -}}
