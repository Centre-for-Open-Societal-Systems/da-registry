{{- define "coss.image" -}}
{{- $repository := required "enabled component requires image.repository" .repository -}}
{{- if .digest -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" .digest) -}}
{{- fail "image.digest must be sha256 followed by 64 lowercase hex characters" -}}
{{- end -}}
{{- printf "%s@%s" $repository .digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (required "enabled component requires image.tag or image.digest" .tag) -}}
{{- end -}}
{{- end -}}
