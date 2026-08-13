# Agregación de resultados

**Estado:** Propuesto. Pendiente de implementación. Requisitos: AC-009 a AC-011.

## Objetivo

Construir una única transcripción JSON/TXT a partir de resultados por chunk, con orden determinista, timestamps absolutos y reconciliación explícita del solapamiento.

## Alcance

Incluye ordenamiento, deduplicación de bordes, normalización temporal, procedencia, validación y exportación. No incluye corrección gramatical ni eliminación de contenido por calidad.

## Requisitos funcionales

- **AC-009:** ordenar por `start`, `end`, `chunk_index` y `segment_id`, en ese orden.
- Comparar los segmentos dentro del solapamiento y eliminar solo duplicación textual suficientemente demostrada.
- Si dos textos son ambiguos o parcialmente distintos, conservar ambos de forma trazable o marcar la ambigüedad; nunca descartar silenciosamente.
- **AC-010:** TXT y JSON deben derivar de la misma lista final y conservar la misma secuencia.
- **AC-011:** incluir métricas de chunks esperados/completados, segmentos antes/después de reconciliación y duración total.

## Requisitos no funcionales

La agregación debe ser pura respecto de sus entradas, determinista y repetible. La comparación no debe depender de hash aleatorio ni del orden de llegada de tareas.

## Diseño técnico

1. Validar que todos los chunks requeridos estén completados.
2. Convertir timestamps locales remanentes a absolutos si aún no lo hizo 03.
3. Ordenar con la clave contractual.
4. Examinar pares consecutivos cuyo intervalo temporal se solapa.
5. Deduplicar únicamente frases idénticas o una coincidencia de borde inequívoca; dejar registro de la decisión.
6. Validar monotonicidad, rangos y procedencia.
7. Escribir JSON y TXT de manera atómica.

La política exacta para coincidencias parciales de borde queda como **[Pendiente de decisión]**: debe elegirse entre una comparación léxica mínima y una alineación basada en timestamps después de medir casos reales de `Yurbaco.m4a`. La implementación inicial debe conservar el texto ante duda.

## Contratos

```json
{
  "contract_version": "audio-transcription/v1",
  "job_id": "job-...",
  "source_id": "sha256:...",
  "source_name": "Yurbaco.m4a",
  "language": "es",
  "duration": 1842.7,
  "segments": [
    {
      "id": "job-...:chunk-000000:segment-000012",
      "start": 12.4,
      "end": 16.8,
      "text": "Texto literal.",
      "provenance": {"chunk_index": 0, "source_start": 0.0, "source_end": 300.0}
    }
  ],
  "metrics": {"chunks": 7, "segments_before": 120, "segments_after": 119}
}
```

El TXT usa `[HH:MM:SS - HH:MM:SS]` y el texto de cada segmento en la línea siguiente. El JSON es la fuente estructural; ambos se generan juntos o ninguno se anuncia como final.

## Dependencias

Resultados de [03](03_transcripcion_por_segmento.md), manifiesto de [01](01_chunking_sincrono.md), serialización JSON estándar y filesystem temporal/salida final.

## Riesgos

- Una deduplicación agresiva puede perder palabras; el sesgo obligatorio es conservar.
- Timestamps iguales o invertidos pueden romper orden; se rechaza el contrato y se informa el segmento responsable.
- Un chunk faltante puede producir una salida incompleta; la validación debe bloquear la salida final.

## Plan de pruebas

| Prueba | Cobertura |
|---|---|
| Resultados fuera de orden | AC-009 |
| Segmentos idénticos en solapamiento | deduplicación |
| Textos parcialmente distintos | no descarte silencioso |
| Timestamps inválidos | validación |
| JSON y TXT con misma secuencia | AC-010 |
| Repetición de agregación | determinismo e idempotencia |

## Criterios de aceptación

- La salida final es completa solo si todos los chunks están validados.
- La ordenación es idéntica entre ejecuciones.
- Cada segmento conserva procedencia y offsets absolutos.
- Las ambigüedades son visibles en datos o diagnósticos.
- JSON parsea y TXT refleja exactamente la lista final.

## Entregables

Agregador determinista, exportadores TXT/JSON, validadores y pruebas de solapamiento.

## Siguiente paso

Integrar estado y checkpoints mediante [05 Progreso y reanudación](05_progreso_reanudacion.md).
