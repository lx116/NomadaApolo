# Especificación de audio por segmentos

**Estado:** Propuesto. Pendiente de implementación.

Este conjunto define una ampliación local y modular del motor de transcripción de la Fase 1. Divide audios largos en unidades procesables, conserva los offsets respecto del original, transcribe cada unidad y agrega una salida única reproducible. La ejecución inicial es síncrona; Celery y Redis quedan diferidos hasta demostrar una necesidad operativa.

## Objetivo

Procesar `Yurbaco.m4a` y otros audios largos sin cargar toda la transformación en una única operación frágil, manteniendo trazabilidad desde cada segmento hasta el archivo original.

## Alcance

Incluye chunking, preprocesamiento FFmpeg, transcripción `faster-whisper`, agregación, progreso y reanudación local, y una especificación posterior para ejecución asíncrona. No incluye cambios en Django, API, base de datos, autenticación, Flutter, diarización ni redacción automática.

## Principios

- **Trazabilidad:** cada resultado conserva `source_id`, índice de chunk y offsets del original.
- **Modularidad:** cada documento y etapa puede probarse aisladamente.
- **Local-first:** el pipeline síncrono se prueba localmente antes de introducir infraestructura.
- **Original inmutable:** el archivo de origen nunca se modifica ni se usa como espacio temporal.
- **Infraestructura incremental:** Redis/Celery solo se incorporan con evidencia de latencia o experiencia de uso.
- **Conservación literal:** la ambigüedad se registra; no se elimina silenciosamente texto dudoso.

## Dependencia y orden de ejecución

```text
00 índice
  -> 01 chunking síncrono
     -> 02 preprocesamiento FFmpeg
        -> 03 transcripción por segmento
           -> 04 agregación
              -> 05 progreso y reanudación
                 -> 07 prueba E2E Yurbaco
              -> 06 Celery (posterior, no bloquea 01-05)
```

| Documento | Dependencia | Estado |
|---|---|---|
| [01 Chunking](01_chunking_sincrono.md) | Fase 1, duración FFprobe | Propuesto |
| [02 Preprocesamiento](02_preprocesamiento_audio.md) | 01, FFmpeg | Propuesto |
| [03 Transcripción](03_transcripcion_por_segmento.md) | 02, faster-whisper | Propuesto |
| [04 Agregación](04_agregacion_resultados.md) | 03 | Propuesto |
| [05 Progreso](05_progreso_reanudacion.md) | 01-04 | Propuesto |
| [06 Celery](06_celery_ejecucion_asincrona.md) | Pipeline síncrono probado, evidencia de necesidad | Diferido |
| [07 E2E](07_prueba_e2e_yurbaco.md) | 01-05, binario `Yurbaco.m4a` | Propuesto |

## Requisitos funcionales

| ID | Requisito | Documento principal |
|---|---|---|
| AC-001 | El original permanece inmutable y fuera del espacio temporal. | 01 |
| AC-002 | Un audio menor de 5 minutos evita el chunking; el límite por defecto es 300 s. | 01 |
| AC-003 | Un audio de al menos 300 s se divide en chunks de máximo 300 s con solapamiento de 1-2 s. | 01 |
| AC-004 | Cada chunk tiene metadatos, nombre determinista y offsets del original. | 01 |
| AC-005 | El espacio temporal queda aislado por job y se limpia en éxito, fallo y cancelación. | 01, 05 |
| AC-006 | FFmpeg produce una representación normalizada y conservadora por chunk. | 02 |
| AC-007 | VAD y denoising se distinguen; ninguno altera silenciosamente el texto literal. | 02, 03 |
| AC-008 | faster-whisper transcribe chunks y corrige timestamps al offset original. | 03 |
| AC-009 | La agregación ordena determinísticamente y reconcilia el solapamiento sin perder ambigüedad. | 04 |
| AC-010 | TXT y JSON comparten la misma secuencia y metadatos de procedencia. | 04 |
| AC-011 | El pipeline registra métricas y errores accionables. | 03, 07 |
| AC-012 | Los chunks completados pueden reanudarse de forma idempotente. | 05 |
| AC-013 | La cancelación detiene trabajo nuevo y limpia temporales sin borrar el original. | 05 |
| AC-014 | Celery/Redis solo se introduce después de validar el pipeline síncrono y medir necesidad. | 06 |
| AC-015 | `Yurbaco.m4a` cumple la aceptación E2E y sus invariantes. | 07 |

## Requisitos no funcionales

- El comportamiento debe ser reproducible con los mismos parámetros y versión de herramientas.
- Los contratos deben ser JSON válido, explícitos y versionables.
- La memoria de modelo debe estar acotada; la concurrencia no puede multiplicar modelos sin control.
- Los errores no deben ocultar el chunk, etapa ni comando que falló.

## Diseño técnico

Las etapas intercambian artefactos de filesystem dentro de `.tmp/<job_id>/`, nunca dentro del repositorio. El manifiesto del job es la fuente de verdad del estado; los nombres y offsets permiten reconstruir el flujo sin depender del orden de creación de archivos.

## Contratos

Todos los tiempos se expresan en segundos `float`, relativos al inicio del archivo original. Todo resultado debe incluir `contract_version`, `job_id`, `source_id`, `chunk_index`, `chunk_start`, `chunk_end` y `source_start`/`source_end` cuando corresponda.

## Dependencias

FFmpeg/ffprobe del sistema, `faster-whisper`, Python y filesystem local. La elección exacta de modelo y parámetros de denoising se mantiene en la configuración de Fase 1 salvo evidencia de que deba cambiarse.

## Riesgos

- El solapamiento puede duplicar palabras; 04 define una reconciliación conservadora.
- La normalización puede alterar señales útiles; 02 limita filtros y conserva el original.
- Modelos grandes pueden agotar memoria; 03 y 06 acotan concurrencia.
- Una interrupción durante escritura puede dejar artefactos parciales; 05 exige escritura atómica y validación.

## Plan de pruebas

Ejecutar pruebas unitarias por etapa, pruebas de contrato entre etapas, una reanudación simulada y la prueba E2E de [07](07_prueba_e2e_yurbaco.md). Cada prueba debe identificar los `AC-*` que cubre.

## Criterios de aceptación

- Los ocho documentos existen, enlazan a nombres reales y no afirman implementación terminada.
- La implementación futura debe satisfacer AC-001 a AC-015 antes de considerar cerrado este slice.

## Entregables

Estos ocho `.md`, una vez implementado el diseño, los módulos correspondientes y las pruebas asociadas. Esta entrega solo contiene documentación.

## Reglas de trazabilidad

Cada cambio de contrato debe actualizar este índice y los documentos afectados. Cada prueba, log y salida E2E debe mencionar el `job_id`, `source_id`, `chunk_index` y requisito `AC-*` cubierto. Una decisión todavía no fijada debe marcarse como `[Pendiente de decisión]` y no convertirse en un valor implícito.

## Siguiente paso

Implementar y probar [01 Chunking síncrono](01_chunking_sincrono.md) sin introducir Celery, Redis ni cambios de aplicación web.
