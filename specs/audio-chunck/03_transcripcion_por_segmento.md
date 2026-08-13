# Transcripción por segmento

**Estado:** Propuesto. Pendiente de implementación. Requisitos: AC-007, AC-008, AC-011 y AC-012.

## Objetivo

Transcribir cada chunk normalizado con faster-whisper, mantener el texto literal y transformar sus timestamps locales a offsets del archivo original.

## Alcance

Incluye ciclo de vida del modelo, ejecución por chunk, corrección de offsets, métricas, reintentos e idempotencia. No incluye diarización, resumen ni edición lingüística.

## Requisitos funcionales

- **AC-008:** cada segmento emitido conserva `start`, `end`, `text` y `source_start`/`source_end` absolutos.
- El texto se preserva literalmente, incluidos signos, mayúsculas, repeticiones y palabras dudosas devueltas por el modelo.
- El modelo se carga una vez por proceso síncrono y se reutiliza para todos los chunks compatibles.
- Un chunk ya validado no se reprocesa durante una reanudación con el mismo `source_id` y configuración.
- **AC-011:** se registran tiempos, modelo, dispositivo, número de segmentos y errores.

## Requisitos no funcionales

La ejecución debe ser local y reproducible con idioma, modelo, device, compute type y versión definidos. La memoria debe permanecer acotada y no debe cargarse una instancia por chunk.

## Diseño técnico

`WhisperModel` se inicializa antes del primer chunk y se libera al terminar el job. Para cada resultado local se calcula:

```text
absolute_start = chunk.source_start + local_start
absolute_end   = chunk.source_start + local_end
```

Los segmentos se almacenan provisionalmente con `chunk_index` y un identificador estable derivado de `job_id`, chunk e índice local. Un retry se limita al chunk fallido; no repite chunks confirmados.

La lógica de confianza puede registrar probabilidades o `no_speech_probability`, pero no puede eliminar texto automáticamente. La política de retry es limitada y explícita: errores transitorios de proceso pueden repetirse hasta el máximo configurado; errores de entrada o modelo se marcan como definitivos.

## Contratos

```json
{
  "segment_id": "job-...:chunk-000000:segment-000012",
  "job_id": "job-...",
  "source_id": "sha256:...",
  "chunk_index": 0,
  "local_start": 12.4,
  "local_end": 16.8,
  "start": 12.4,
  "end": 16.8,
  "text": " Texto literal devuelto por el modelo. ",
  "language": "es",
  "model": "medium",
  "status": "completed"
}
```

No se recorta ni normaliza `text` en esta etapa; la presentación TXT puede aplicar solo el formato de línea definido por [04](04_agregacion_resultados.md).

## Dependencias

`faster-whisper`, pesos locales, salida de [02](02_preprocesamiento_audio.md) y el contrato de [01](01_chunking_sincrono.md). No introduce colas ni persistencia externa.

## Riesgos

- El modelo puede repetir palabras en el solapamiento; 04 resuelve la duplicación.
- El modelo puede devolver timestamps fuera del chunk; se valida y se registra, nunca se corrige silenciosamente fuera de los límites sin evidencia.
- La memoria de `large-v3` puede impedir ejecución local; el modelo es configurable y la concurrencia futura queda acotada en [06](06_celery_ejecucion_asincrona.md).

## Plan de pruebas

| Prueba | Cobertura |
|---|---|
| Mock de `WhisperModel` sobre dos chunks | AC-008, offsets |
| Texto con espacios y repeticiones | preservación literal |
| Modelo creado una sola vez | ciclo de vida |
| Retry de un chunk fallido | AC-012, idempotencia |
| Error definitivo de modelo/entrada | diagnóstico |
| Métricas de duración y conteo | AC-011 |
| Prueba opcional con modelo tiny local | integración real sin red |

## Criterios de aceptación

- Los offsets absolutos son monotónicos dentro de tolerancia numérica y no pierden el `source_start`.
- Un retry no duplica resultados válidos.
- Los segmentos ambiguos permanecen visibles y trazables.
- El modelo no se carga por chunk.

## Entregables

Adaptador de transcripción por chunk, contrato de segmento, métricas y pruebas unitarias/integración.

## Siguiente paso

Pasar los segmentos a [04 Agregación de resultados](04_agregacion_resultados.md).
