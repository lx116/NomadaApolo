# Prueba E2E de `Yurbaco.m4a`

**Estado:** Propuesto. Pendiente de implementación y ejecución. Requisito: AC-015.

## Objetivo

Definir la aceptación final del pipeline síncrono usando el binario real `Yurbaco.m4a`, desde validación hasta JSON/TXT agregados y limpieza.

## Alcance

Incluye prerequisitos, procedimiento, invariantes, mediciones, diagnósticos y criterios de finalización. No incluye publicación web, Celery ni cambios de producto.

## Requisitos funcionales

- **AC-015:** el archivo se procesa completo, sin modificarlo, y genera una salida estructural y una legible.
- La prueba debe ejecutar 01-05 en orden y conservar `job_id`, hash del origen, configuración y versiones.
- Todo segmento final debe tener timestamps absolutos, texto y procedencia.

## Requisitos no funcionales

La prueba debe ser repetible en la misma máquina y reportar duración de audio, tiempo total, ratio de tiempo real, memoria máxima aproximada, modelo, device, compute type, FFmpeg y cantidad de chunks/segmentos.

## Diseño técnico

### Prerrequisitos

- Archivo legible en una ruta fuera del repositorio.
- FFmpeg y ffprobe disponibles.
- Pesos locales de faster-whisper disponibles; la prueba no debe depender de red.
- Espacio temporal y de salida suficiente.
- Configuración de idioma, modelo, dispositivo y compute type registrada antes de iniciar.

### Procedimiento

1. Calcular y registrar `source_id` sin alterar el archivo.
2. Ejecutar validación de duración y chunking con límite 300 s y overlap 1 s.
3. Preprocesar cada chunk con contrato mono/16 kHz/16-bit.
4. Transcribir reutilizando una instancia del modelo.
5. Agregar y validar resultados; producir un JSON y un TXT fuera del workspace temporal.
6. Verificar invariantes y hash del original.
7. Confirmar cleanup y conservar el reporte de aceptación.

## Contratos

Salidas esperadas, con nombres derivados de `source_name` y `job_id`:

```text
<output_dir>/Yurbaco.<job_id>.json
<output_dir>/Yurbaco.<job_id>.txt
```

El JSON cumple el contrato de [04](04_agregacion_resultados.md). El TXT usa el formato de Fase 1. El reporte E2E añade comandos, versiones, métricas, hash, estados y diagnóstico; no reemplaza las salidas.

## Dependencias

[01](01_chunking_sincrono.md), [02](02_preprocesamiento_audio.md), [03](03_transcripcion_por_segmento.md), [04](04_agregacion_resultados.md) y [05](05_progreso_reanudacion.md). `Yurbaco.m4a` es un prerrequisito externo y no se copia al repositorio.

## Riesgos

- La duración o calidad reales pueden revelar una política de overlap insuficiente; conservar evidencia y no ajustar silenciosamente.
- El modelo puede no estar en caché; marcar bloqueo de entorno, no atribuirlo al pipeline.
- Un resultado aparentemente completo puede omitir chunks; comparar manifiesto con salida final.

## Plan de pruebas

| Verificación | Resultado esperado |
|---|---|
| Hash antes/después | idéntico |
| Cobertura de ventanas | inicio 0, fin igual a duración, sin huecos |
| Duración de chunks | máximo 300 s |
| Contrato de audio | mono, 16 kHz, 16-bit |
| Estado del manifiesto | todos los chunks completados |
| JSON | parseable, ordenado, con procedencia |
| TXT | misma secuencia que JSON |
| Cleanup | workspace ausente tras terminar |
| Repetición | mismo contenido estructural con misma configuración |

## Criterios de aceptación

La prueba se considera completada cuando:

- se procesa el archivo completo sin modificar el origen;
- todos los invariantes anteriores pasan;
- JSON y TXT se generan y son coherentes;
- los errores, si los hubo durante retries, quedan documentados;
- las métricas permiten comparar tiempo total con duración de audio;
- no se introduce Celery por el solo hecho de ejecutar esta prueba.

Un fallo de entorno se clasifica como `bloqueo de prerrequisito`; un fallo de contrato, pérdida de segmentos, corrupción del origen o cleanup incompleto bloquea la aceptación.

## Entregables

Reporte de ejecución, JSON final, TXT final y evidencia de invariantes. Los binarios intermedios son temporales y no se incorporan al repositorio.

## Siguiente paso

Si la aceptación síncrona pasa, revisar las métricas y decidir explícitamente si AC-014 justifica una futura especificación/aplicación de Celery.
