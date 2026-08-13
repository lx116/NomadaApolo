# SDD — Fase 1: Motor de Transcripción Audio → Texto (Python)

## 1. Objetivo

Construir un motor local en Python que reciba un archivo de audio y produzca una transcripción en español con timestamps por segmento, exportada a TXT y JSON, ejecutable desde línea de comandos.

Esta fase valida el núcleo técnico del producto. No incluye app móvil, backend web, autenticación ni resúmenes automáticos.

## 2. Alcance

### Incluido
- Recepción de un archivo de audio local (`.m4a`, `.mp3`, `.wav`, `.mp4`).
- Validación de existencia, extensión y legibilidad del archivo.
- Normalización del audio vía FFmpeg (formato/sample rate compatible con Whisper).
- Transcripción en español usando `faster-whisper`.
- Generación de timestamps por segmento (inicio/fin).
- Exportación a TXT y JSON.
- CLI con parámetros configurables.
- Registro de métricas básicas de ejecución.
- Al menos una prueba automática del flujo principal.

### Explícitamente fuera de alcance
Flutter, FastAPI, Redis, Celery, autenticación, usuarios, base de datos, resúmenes automáticos, redacción con LLM, diarización de hablantes, integración con Nómada.

## 3. Requisitos funcionales

| ID | Requisito |
|---|---|
| RF-01 | El sistema debe aceptar como entrada un archivo de audio local vía argumento CLI. |
| RF-02 | El sistema debe rechazar con un error controlado archivos con extensión no soportada. |
| RF-03 | El sistema debe rechazar con un error controlado archivos inexistentes o corruptos. |
| RF-04 | El sistema debe normalizar el audio antes de transcribir (vía FFmpeg) cuando el formato lo requiera. |
| RF-05 | El sistema debe transcribir el audio completo en español, generando texto por segmento. |
| RF-06 | Cada segmento debe incluir `start`, `end` y `text`. |
| RF-07 | El sistema debe exportar la transcripción a `.txt` con formato `[HH:MM:SS - HH:MM:SS]` por segmento. |
| RF-08 | El sistema debe exportar la transcripción a `.json` con la estructura definida en la sección 6. |
| RF-09 | El sistema debe permitir configurar: modelo Whisper, idioma, dispositivo (CPU/GPU), tipo de cómputo, directorio de salida, activación de VAD, formato de exportación. |
| RF-10 | El sistema debe imprimir/registrar métricas de la ejecución al finalizar. |

## 4. Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF-01 | Debe procesar un audio de al menos 30 minutos sin pérdida de segmentos por errores de lectura. |
| RNF-02 | Debe funcionar en CPU (modelo `medium`, `compute_type=int8`) sin GPU obligatoria. |
| RNF-03 | El código debe estar dividido en módulos con responsabilidad única (ver sección 5). |
| RNF-04 | Los errores de entrada (archivo inválido, formato no soportado) no deben provocar cierres abruptos sin mensaje. |
| RNF-05 | La salida JSON debe ser válida y parseable sin post-procesamiento. |
| RNF-06 | El sistema no debe requerir conexión a internet para transcribir (una vez el modelo esté descargado localmente). |

## 5. Diseño técnico

### 5.1 Stack
Python 3.10+, `faster-whisper`, `ffmpeg` (binario del sistema), `pathlib`, `argparse`, `json`, `python-docx` (reservado para exportaciones futuras, no usado en esta fase).

### 5.2 Estructura de módulos

```
transcriptor/
├── src/
│   ├── __init__.py
│   ├── transcriber.py   # carga de modelo, ejecución Whisper, VAD, normalización de segmentos
│   ├── audio.py         # validación, duración, conversión/normalización
│   ├── exporters.py     # TXT, JSON (arquitectura extensible a DOCX/SRT/PDF)
│   └── config.py        # parámetros por defecto, constantes
├── tests/
│   ├── test_audio.py
│   └── test_transcriber.py
├── samples/
├── output/
├── requirements.txt
├── .gitignore
└── README.md
```

### 5.3 Responsabilidad por módulo

**`audio.py`**
- Validar existencia del archivo (`FileNotFoundError` controlado).
- Validar extensión contra lista soportada (`.m4a`, `.mp3`, `.wav`, `.mp4`).
- Obtener duración (vía ffprobe o librería equivalente).
- Convertir/normalizar a formato compatible con Whisper cuando sea necesario.

**`transcriber.py`**
- Cargar `WhisperModel` con parámetros (modelo, device, compute_type).
- Ejecutar transcripción con idioma fijado (`es`).
- Activar/desactivar VAD según configuración.
- Normalizar la salida cruda de `faster-whisper` a la estructura de segmentos definida (sección 6).

**`exporters.py`**
- Exportar a TXT y JSON en esta fase.
- Definir una interfaz común (p. ej. función `export(segments, format, path)`) que permita añadir DOCX, SRT y PDF en fases posteriores sin reescribir el núcleo.

**`config.py`**
- Valores por defecto: modelo `medium`, idioma `es`, device `cpu`, compute_type `int8`, VAD activado, directorio de salida `output/`.

### 5.4 Flujo de ejecución

```
Archivo de audio
      ↓
Validación (audio.py)
      ↓
Normalización / FFmpeg (audio.py)
      ↓
Carga de modelo + transcripción (transcriber.py)
      ↓
Segmentos + timestamps
      ↓
Construcción de transcripción normalizada
      ↓
Exportación TXT / JSON (exporters.py)
```

### 5.5 Configuración de modelo

CPU (desarrollo):
```python
WhisperModel("medium", device="cpu", compute_type="int8")
```

GPU NVIDIA (pruebas de precisión):
```python
WhisperModel("large-v3", device="cuda", compute_type="float16")
```

## 6. Modelo de datos / contratos de salida

### JSON
```json
{
  "language": "es",
  "duration": 2453.4,
  "segments": [
    {
      "start": 0.0,
      "end": 4.6,
      "text": "Buenos días, comenzamos la entrevista."
    }
  ]
}
```

### TXT
```
[00:00:00 - 00:00:04]
Buenos días, comenzamos la entrevista.
```

## 7. Interfaz (CLI)

```bash
python main.py Yurbaco.m4a
python main.py Yurbaco.m4a --model large-v3 --language es
```

Parámetros configurables: `--model`, `--language`, `--device`, `--compute-type`, `--output-dir`, `--vad` (on/off), `--format` (txt/json/ambos).

## 8. Dependencias externas

- Binario `ffmpeg` instalado en el sistema (no gestionado por pip).
- Descarga previa (o en primera ejecución) de los pesos del modelo Whisper elegido.
- Espacio en disco suficiente para modelos `medium`/`large-v3` (varios GB).

## 9. Métricas a registrar por ejecución

Duración del audio, tiempo total de procesamiento, modelo utilizado, dispositivo utilizado, idioma detectado, número de segmentos generados.

Ejemplo:
```
Audio: 40:13
Modelo: medium
Dispositivo: CPU
Procesamiento: 08:47
Segmentos: 423
Idioma: es
```

## 10. Plan de pruebas

| Prueba | Tipo | Qué valida |
|---|---|---|
| `test_audio.py` | Unitaria | Validación de extensión, manejo de archivo inexistente, cálculo de duración. |
| `test_transcriber.py` | Integración | Flujo completo sobre un audio corto de muestra (`samples/`), verificando estructura de segmentos y no pérdida de contenido. |
| Prueba manual de aceptación | E2E | Ejecutar CLI sobre `Yurbaco.m4a` (audio ≥30 min) y verificar TXT/JSON generados. |

## 11. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Modelos grandes (`large-v3`) inviables en máquinas sin GPU. | Definir `medium`/CPU como configuración por defecto; `large-v3` queda como opción explícita. |
| Archivos `.m4a`/`.mp4` con codecs no estándar fallan en la conversión. | Normalización obligatoria vía FFmpeg antes de pasar a Whisper; capturar y reportar errores de ffmpeg de forma clara. |
| Pérdida de segmentos en audios largos por timeouts o errores de memoria. | Procesamiento por streaming/segmentado de `faster-whisper`; prueba de aceptación explícita con audio ≥30 min. |
| Acoplamiento temprano a una única librería de exportación. | Interfaz común en `exporters.py` pensada para añadir formatos sin tocar `transcriber.py`. |

## 12. Criterios de aceptación

- Recibe correctamente un `.m4a`.
- Transcribe un audio de al menos 30 minutos sin pérdida de segmentos.
- Devuelve timestamps por segmento.
- Genera TXT y JSON válidos.
- Errores de entrada controlados (sin crashes no manejados).
- Código dividido en los módulos descritos.
- Existe al menos una prueba automática del flujo principal.
- **Meta de validación concreta:** ejecutar el comando sobre `Yurbaco.m4a` y obtener transcripción completa con timestamps, exportada en TXT y JSON, de forma reproducible.

## 13. Entregables

- Repositorio `transcriptor/` con la estructura descrita.
- `requirements.txt` con dependencias fijadas.
- `README.md` con instrucciones de instalación (incluyendo FFmpeg) y uso del CLI.
- Suite de pruebas mínima ejecutable con `pytest`.
