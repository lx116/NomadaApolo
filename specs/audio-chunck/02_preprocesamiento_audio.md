# Preprocesamiento de audio por chunk

**Estado:** Propuesto. Pendiente de implementación. Requisitos: AC-005 a AC-007.

## Objetivo

Producir una representación Whisper-compatible por chunk usando FFmpeg, con filtros conservadores y sin confundir eliminación de silencios con reducción general de ruido.

## Alcance

Incluye normalización de formato, sample rate, canales, profundidad, filtros opcionales y errores. No decide el texto ni reemplaza la señal original.

## Requisitos funcionales

- **AC-006:** cada chunk procesado genera PCM mono, 16 kHz, 16-bit, en WAV o el formato local acordado por Fase 1.
- **AC-007:** VAD/silence trimming y denoising son opciones separadas, registradas en metadatos.
- FFmpeg debe recibir el chunk y escribir en el workspace del job, nunca sobre el origen.
- El comando, versión de FFmpeg, parámetros y duración de entrada/salida quedan registrados.

## Requisitos no funcionales

La configuración predeterminada no debe aplicar denoising agresivo. No se debe borrar texto por heurística acústica en esta etapa. Si el preprocesamiento cambia la duración, la salida debe conservar el mapeo temporal al intervalo original.

## Diseño técnico

La ruta mínima es conversión de codec, `-ac 1`, `-ar 16000` y profundidad PCM compatible. El VAD puede eliminar regiones silenciosas para acelerar la transcripción, pero no es un denoiser general: no limpia reverberación, música, voces superpuestas ni ruido estacionario por sí solo.

El denoising, si se habilita, debe usar un filtro explícito y conservador, por ejemplo `afftdn` con parámetros fijados por prueba. No se habilitará automáticamente por detectar ruido. La ejecución debe usar argumentos estructurados, no interpolación insegura de rutas.

## Contratos

```json
{
  "input_chunk": "chunks/000000.wav",
  "output_audio": "preprocessed/000000.wav",
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "s16",
  "vad": {"enabled": true, "mode": "silence-context-only"},
  "denoising": {"enabled": false, "filter": null},
  "source_start": 0.0,
  "source_end": 300.0,
  "ffmpeg_version": "reported-at-runtime"
}
```

El resultado fallido no se considera un chunk procesado. Un archivo parcial se elimina antes de propagar el error.

## Dependencias

FFmpeg instalado y accesible; manifiesto de [01](01_chunking_sincrono.md); workspace aislado. `faster-whisper` consume la salida, pero no se carga aquí.

## Riesgos

- Filtros demasiado agresivos degradan consonantes y timestamps; se mantiene desactivado el denoising por defecto.
- El VAD puede retirar silencios significativos; la decisión se registra y se conserva el chunk original.
- Versiones distintas de FFmpeg pueden producir pequeñas diferencias; la versión forma parte de las métricas.

## Plan de pruebas

| Prueba | Cobertura |
|---|---|
| Inspección con `ffprobe` de salida | AC-006 |
| FFmpeg ausente | error accionable y limpieza |
| Codec de entrada válido e inválido | AC-006, errores |
| VAD activado/desactivado | AC-007, configuración separada |
| Denoising desactivado por defecto | AC-007 |
| Filtro fallido a mitad de escritura | AC-005, no dejar salida parcial |
| Comparación de duración y offsets | contrato temporal |

## Criterios de aceptación

- Toda salida válida cumple mono, 16 kHz y 16-bit.
- El origen conserva hash y tamaño.
- Los metadatos distinguen inequívocamente VAD de denoising.
- Los fallos incluyen comando, stderr resumido, chunk y ruta de salida.
- Éxito y fallo limpian temporales conforme a [05](05_progreso_reanudacion.md).

## Entregables

Adaptador FFmpeg, contrato de audio normalizado, configuración explícita de filtros y pruebas de contrato.

## Siguiente paso

Entregar la salida normalizada a [03 Transcripción por segmento](03_transcripcion_por_segmento.md).
