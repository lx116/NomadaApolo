# Índice de SDD — Transcriptor de Audio y Voice-to-Draft

Este documento indexa los Software Design Documents (SDD) de cada fase del roadmap. Cada SDD es autocontenido y puede entregarse de forma independiente a quien ejecute esa fase, pero todos comparten los mismos principios rectores del proyecto.

## Principios rectores (aplican a todas las fases)

1. **Trazabilidad primero.** Ninguna transformación (limpieza, resumen, redacción) puede perder la referencia al segmento, timestamp y audio original.
2. **Modularidad.** Cada fase debe poder validarse de forma aislada, sin depender de que fases posteriores existan.
3. **Local antes que remoto.** El núcleo técnico (Fase 1–2) se valida en local antes de exponerse como servicio (Fase 3+).
4. **No sustituir el original.** La transcripción literal nunca se sobreescribe; las versiones derivadas (Fase 6) son capas adicionales.
5. **Crecimiento incremental de infraestructura.** No se introduce Redis, Celery, bases de datos o autenticación antes de que la fase que los requiere esté justificada por el roadmap.

## Mapa de fases y estado de diseño

| Fase | Nombre | Depende de | Introduce | Documento |
|---|---|---|---|---|
| 1 | Motor de transcripción (Python) | — | faster-whisper, ffmpeg, CLI | `sdd_fase1_motor_transcripcion.md` |
| 2 | Calidad y diarización | Fase 1 | pyannote.audio, SRT | `sdd_fase2_calidad_diarizacion.md` |
| 3 | API de procesamiento | Fase 1–2 | FastAPI, Docker | `sdd_fase3_api_procesamiento.md` |
| 4 | Jobs asíncronos | Fase 3 | Redis, Celery/RQ | `sdd_fase4_jobs_asincronos.md` |
| 5 | Aplicación Flutter | Fase 3–4 | Cliente móvil | `sdd_fase5_app_flutter.md` |
| 6 | Redactor automático (Voice-to-Draft) | Fase 1–5 | LLM pipeline | `sdd_fase6_voice_to_draft.md` |
| 7 | Exportación académica/documental | Fase 6 | DOCX, PDF, plantillas | `sdd_fase7_exportacion_documental.md` |
| 8 | Persistencia y usuarios | Fase 3–4 | PostgreSQL, S3, auth | `sdd_fase8_persistencia_usuarios.md` |
| 9 | Observabilidad y producción | Fase 3–8 | Sentry, métricas, rate limits | `sdd_fase9_observabilidad_produccion.md` |
| 10 | Integración con Nómada | Todas | Editor Nómada | `sdd_fase10_integracion_nomada.md` |

## Cómo usar estos documentos

- Cada SDD sigue la misma plantilla: Objetivo, Alcance, Requisitos funcionales, Requisitos no funcionales, Diseño técnico, Modelo de datos/contratos, Interfaces, Dependencias, Riesgos, Plan de pruebas, Criterios de aceptación, Entregables.
- El diseño no incluye código de implementación — es responsabilidad del rol ejecutor traducir el SDD en código, siguiendo la arquitectura descrita.
- Cuando una fase depende de decisiones no cerradas en una fase anterior, se marca explícitamente como **[Pendiente de decisión]**.
