# Chunking síncrono de audio

**Estado:** Propuesto. Pendiente de implementación. Requisitos: AC-001 a AC-005.

## Objetivo

Convertir un audio largo en chunks locales, ordenados y trazables, con duración máxima de 300 segundos y solapamiento suficiente para evitar cortes de palabras.

## Alcance

Incluye validación de duración, bypass para audios cortos, extracción de chunks, metadatos, nombres deterministas, aislamiento y limpieza. No incluye transcripción, VAD ni Celery.

## Requisitos funcionales

- **AC-002:** si `duration < 300.0`, se usa el original como única unidad lógica y no se crean chunks físicos salvo que la etapa siguiente requiera normalización.
- **AC-003:** si `duration >= 300.0`, cada chunk tiene contenido principal de hasta 300 s y un solapamiento configurable entre 1 y 2 s. El valor propuesto es 1 s.
- **AC-004:** el índice empieza en 0 y los chunks se ordenan por `chunk_index` y `source_start`.
- **AC-001:** el archivo de origen se abre solo para lectura; no se sobrescribe, mueve ni renombra.
- **AC-005:** el workspace se crea como `<tmp_root>/<job_id>/` con permisos restringidos y no puede estar bajo `specs/`, `src/`, `output/` ni otra carpeta del repositorio.

## Requisitos no funcionales

El algoritmo debe ser determinista, tolerar el último chunk más corto y no requerir que todo el audio descomprimido resida en memoria. El límite de 300 s es una constante configurable solo para facilitar pruebas o calibración; cambiarlo requiere justificar memoria, timestamps y aceptación.

## Diseño técnico

1. Validar ruta, legibilidad y duración mediante el componente de audio de Fase 1.
2. Crear el workspace exclusivo del job.
3. Aplicar ventanas `[start, end]` con `end <= duration`; para audio largo, el siguiente inicio avanza por `300 - overlap`.
4. Escribir cada artefacto de manera atómica y verificar que exista y sea legible.
5. Emitir el manifiesto antes de permitir transcripción.

El solapamiento se considera contexto adicional. El `source_start` y `source_end` reflejan el intervalo real incluido; el `content_start` y `content_end` identifican la porción principal sin solapamiento cuando sea necesario para reanudar.

## Contratos

```json
{
  "contract_version": "audio-chunk/v1",
  "job_id": "job-20260813-001",
  "source_id": "sha256:...",
  "source_name": "Yurbaco.m4a",
  "source_duration": 1842.7,
  "chunk_index": 0,
  "source_start": 0.0,
  "source_end": 300.0,
  "content_start": 0.0,
  "content_end": 299.0,
  "overlap_before": 0.0,
  "overlap_after": 1.0,
  "path": "chunks/000000.wav"
}
```

Los nombres físicos usan `chunks/<chunk_index de seis dígitos>.<extensión-normalizada>`. El `source_id` se calcula sin modificar el archivo y permite detectar que una reanudación usa la misma entrada.

## Dependencias

FFprobe para duración y FFmpeg o el mecanismo de extracción definido por Fase 1. Filesystem temporal local. No requiere Django, Redis, Celery, base de datos ni API.

## Riesgos

- Un redondeo puede producir un chunk mayor que 300 s; se valida `source_end - source_start <= 300`.
- El último chunk puede ser muy corto; se conserva y se rechaza solo si FFmpeg lo declara ilegible.
- Un workspace preexistente podría mezclar jobs; `job_id` debe ser único y la creación debe fallar si ya existe.

## Plan de pruebas

| Prueba | Cobertura |
|---|---|
| Duración 299.9 s | AC-002, bypass |
| Duración 300.0 s | AC-003, frontera |
| Duración 601 s | AC-003, solapamiento y último chunk |
| Archivo inexistente o ilegible | error controlado |
| Repetir el mismo job | AC-004, idempotencia de nombres |
| Interrumpir durante escritura | AC-005, no dejar artefacto parcial válido |
| Verificar hash del origen antes/después | AC-001 |

## Criterios de aceptación

- Ningún chunk supera 300 s.
- Las ventanas cubren el audio completo sin huecos intencionales.
- Los chunks consecutivos tienen entre 1 y 2 s de contexto compartido, excepto los bordes.
- El manifiesto permite reconstruir orden, offsets y rutas.
- Éxito, fallo y cancelación limpian el workspace según [05](05_progreso_reanudacion.md).

## Entregables

Módulo síncrono de chunking, manifiesto versionado, pruebas unitarias y prueba con un audio corto y uno largo. No se entrega Celery en este paso.

## Siguiente paso

Con el manifiesto validado, implementar [02 Preprocesamiento de audio](02_preprocesamiento_audio.md).
