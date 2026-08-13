# Ejecución asíncrona con Celery

**Estado:** Diferido. Propuesto para una infraestructura posterior; pendiente de implementación. Requisito: AC-014.

## Objetivo

Definir una transición segura del pipeline síncrono a trabajos en segundo plano solo si las mediciones muestran que la espera bloqueante o la experiencia de uso lo justifican.

## Alcance

Incluye factibilidad, topología Redis/Celery, workflow, concurrencia, retries, observabilidad, limpieza, seguridad, pruebas y rollout. No autoriza cambios inmediatos en Django, API, base de datos o autenticación.

## Requisitos funcionales

- **AC-014:** primero deben existir una ejecución síncrona validada y mediciones de latencia, memoria y cancelación sobre audios representativos.
- La tarea raíz crea un `job_id` y delega etapas; un `group` procesa chunks y un `chord` agrega solo cuando todos terminan.
- Retries se limitan a errores transitorios y conservan idempotencia por `job_id`, `chunk_index`, `source_id` y configuración.
- La concurrencia se limita por memoria del modelo, no por número arbitrario de CPUs.
- El workspace continúa aislado por job y se limpia en éxito, fallo, cancelación o expiración.

## Requisitos no funcionales

Redis no debe convertirse en almacenamiento de audio ni de resultados finales. Los mensajes deben ser pequeños y contener referencias seguras a artefactos locales compartidos. El sistema debe poder explicar qué worker procesó cada chunk.

## Diseño técnico

Topología propuesta: productor local/API futura -> broker Redis -> workers Celery -> workspace compartido por job -> agregador final. El `group` representa chunks; el callback del `chord` valida completitud y ejecuta agregación. La topología exacta queda **[Pendiente de decisión]** hasta confirmar si los workers compartirán máquina y filesystem; si no, será necesario un almacenamiento de artefactos, que está fuera de este slice.

Cada worker carga como máximo la cantidad de modelos que la memoria permita. La primera versión debe preferir un pool de procesos pequeño y una cola dedicada a transcripción. El tiempo de visibilidad, backoff, límite de retries y expiración se configuran después de medir.

## Contratos

El mensaje solo referencia `{job_id, chunk_index, source_id, config_fingerprint}`. El resultado de tarea reutiliza el contrato de [03](03_transcripcion_por_segmento.md); el callback produce el contrato de [04](04_agregacion_resultados.md). Redis no contiene audio, texto literal completo ni secretos.

## Dependencias

Pipeline síncrono completo, Redis, Celery, workers configurados y una frontera de artefactos compartida. No se agrega ninguna dependencia para el primer chunking síncrono.

## Riesgos

- Concurrencia excesiva duplica consumo de memoria y mata workers; usar límites medidos.
- Reintentos de tareas no idempotentes duplican segmentos; usar claves estables y resultados atómicos.
- Redis perdido puede perder coordinación; el manifiesto local y la recuperación deben seguir siendo la fuente de verdad del job.
- La introducción prematura agrega complejidad sin resolver una necesidad; AC-014 la bloquea.

## Plan de pruebas

| Prueba | Cobertura |
|---|---|
| Chord con todos los chunks | workflow completo |
| Retry de un chunk | idempotencia |
| Worker muerto | recuperación |
| Límite de concurrencia | memoria |
| Cancelación | no iniciar tareas nuevas y cleanup |
| Redis no disponible | error y recuperación |
| Inspección de payload | no transportar audio/secretos |

## Criterios de aceptación

- Existe evidencia cuantitativa de que el modo síncrono no satisface la UX o latencia objetivo.
- La topología elegida comparte artefactos de manera segura y documentada.
- El resultado asíncrono es byte-equivalente al síncrono con la misma configuración, salvo metadatos operativos.
- Retries y concurrencia no producen duplicados ni agotamiento de memoria.

## Entregables

Solo después de aprobar el go/no-go: configuración Celery/Redis, tareas, límites operativos, métricas y runbook. No incluye Django/API/database/auth en esta especificación inicial.

## Siguiente paso

Completar [07](07_prueba_e2e_yurbaco.md), medir el pipeline síncrono y registrar la decisión de introducir o no esta infraestructura.

## No objetivos explícitos

- No introducir Celery en los documentos 01-05 ni como requisito de su implementación.
- No crear endpoints, modelos Django, usuarios, autenticación o persistencia de producto.
- No usar Redis como reemplazo del manifiesto de trazabilidad.
