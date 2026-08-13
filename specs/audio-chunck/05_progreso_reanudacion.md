# Progreso y reanudación

**Estado:** Propuesto. Pendiente de implementación. Requisitos: AC-005, AC-012 y AC-013.

## Objetivo

Permitir observar, reanudar y cancelar un job local sin repetir chunks completados ni perder trazabilidad.

## Alcance

Incluye máquina de estados, manifiesto de checkpoint, idempotencia, cancelación, limpieza y recuperación. No incluye base de datos, API, Redis ni Celery.

## Requisitos funcionales

- **AC-012:** cada chunk completado se identifica por `source_id`, parámetros y hash del artefacto; un rerun compatible lo reutiliza.
- **AC-013:** cancelar impide iniciar trabajo nuevo, marca el job como `cancelled` y limpia el workspace.
- **AC-005:** éxito, fallo y cancelación ejecutan limpieza segura; el origen queda intacto.
- El manifiesto se escribe atómicamente después de cada transición relevante.

## Requisitos no funcionales

El manifiesto debe poder leerse tras un proceso abortado y permitir diagnóstico sin depender de logs volátiles. Las transiciones inválidas se rechazan. El progreso debe ser monotónico salvo una recuperación explícita de un chunk fallido.

## Diseño técnico

Estados de job: `created -> chunking -> preprocessing -> transcribing -> aggregating -> completed`. Estados terminales alternativos: `failed`, `cancelled`. Un chunk usa `pending -> processing -> completed` o `failed`; un retry devuelve `failed -> pending` solo si la política lo permite.

El checkpoint contiene versión de contrato, identidad de origen, configuración efectiva, lista de chunks, estados, rutas, hashes, errores, timestamps y métricas. Escrituras temporales usan archivo hermano y rename atómico. Un archivo existente con `source_id` o configuración incompatibles no se reutiliza.

La limpieza en éxito elimina temporales después de validar salidas finales. En fallo o cancelación elimina artefactos, conserva un resumen diagnóstico mínimo fuera del workspace y no elimina resultados finales ya confirmados sin una política explícita.

## Contratos

```json
{
  "contract_version": "audio-job/v1",
  "job_id": "job-...",
  "source_id": "sha256:...",
  "state": "transcribing",
  "cancel_requested": false,
  "chunks": [{"index": 0, "state": "completed", "artifact_hash": "sha256:..."}],
  "config_fingerprint": "sha256:...",
  "updated_at": "2026-08-13T12:00:00Z"
}
```

## Dependencias

Contratos de [01](01_chunking_sincrono.md), [02](02_preprocesamiento_audio.md), [03](03_transcripcion_por_segmento.md) y [04](04_agregacion_resultados.md). Filesystem local, sin persistencia externa.

## Riesgos

- Un rename no atómico en un filesystem no local puede corromper checkpoint; se limita el alcance a filesystem local.
- Reutilizar un artefacto con parámetros distintos contamina resultados; se compara `config_fingerprint`.
- La limpieza puede borrar evidencia útil; se conserva resumen y stderr fuera del workspace temporal.

## Plan de pruebas

| Prueba | Cobertura |
|---|---|
| Aborto tras cada etapa | recuperación |
| Reanudación con un chunk completado | AC-012 |
| Cambio de origen o configuración | no reutilización |
| Cancelación durante procesamiento | AC-013 |
| Fallo de limpieza | diagnóstico sin borrar origen |
| Escritura concurrente del checkpoint | transiciones válidas |

## Criterios de aceptación

- Un reinicio reanuda solo trabajo compatible y pendiente.
- No existen dos resultados finales para el mismo `segment_id`.
- Cancelación no inicia chunks posteriores.
- El workspace no sobrevive a éxito, fallo o cancelación salvo una retención diagnóstica explícita fuera de él.

## Entregables

Máquina de estados local, manifiesto versionado, limpieza idempotente y pruebas de interrupción/reanudación.

## Siguiente paso

Ejecutar [07 prueba E2E](07_prueba_e2e_yurbaco.md). Solo después evaluar [06 Celery](06_celery_ejecucion_asincrona.md).
