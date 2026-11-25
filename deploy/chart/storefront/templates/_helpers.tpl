{{- define "storefront.labels" -}}
app.kubernetes.io/part-of: storefront
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Scheduling shared by both tiers: run on the tier's own node group, spread across zones and nodes. */}}
{{- define "storefront.scheduling" -}}
nodeSelector:
  tier: {{ .tier }}
tolerations:
  - key: dedicated
    operator: Equal
    value: {{ .tier }}
    effect: NoSchedule
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app: {{ .app }}
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app: {{ .app }}
{{- end -}}
