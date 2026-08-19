<p align="center">
  <img src="../assets/kace_banner.png" width="1000" alt="Banner de KACE">
</p>

<h1 align="center">KACE</h1>

<p align="center">
  <strong>Klipper Automated Configuration Ecosystem</strong><br>
  El acompañante interactivo para convertir las decisiones de una impresora en artefactos de Klipper revisables.
</p>

<p align="center">
  <a href="https://github.com/3D-uy/KACE/actions/workflows/ci.yml"><img src="https://github.com/3D-uy/KACE/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <img src="https://img.shields.io/badge/status-pre--1.0-yellow" alt="Estado del proyecto: pre-1.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11 o posterior">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-green" alt="Linux y Raspberry Pi">
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="Licencia GPL-3.0"></a>
</p>

<p align="center">
  <a href="../../README.md">English</a> · <strong>Español</strong> · <a href="../pt/README.md">Português</a>
</p>

> [!WARNING]
> KACE está en desarrollo activo pre-1.0. La rama `main` puede cambiar sin garantías de compatibilidad hacia atrás hasta que exista un proceso de versiones estables.

## Índice

- [¿Qué es KACE?](#qué-es-kace)
- [Inicio rápido](#inicio-rápido)
- [Cómo fluye el ecosistema](#cómo-fluye-el-ecosistema)
- [¿Por qué KACE?](#por-qué-kace)
- [Características](#características)
- [Estado actual](#estado-actual)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Flujo completo](#flujo-completo)
- [Arquitectura](#arquitectura)
- [Tecnologías](#tecnologías)
- [Pruebas y validación](#pruebas-y-validación)
- [Docker](#docker)
- [CI/CD](#cicd)
- [Compatibilidad y límites](#compatibilidad-y-límites)
- [Roadmap](#roadmap)
- [Contribuir](#contribuir)
- [Licencia](#licencia)

---

## ¿Qué es KACE?

KACE es la CLI interactiva que se ejecuta del lado de Raspberry Pi dentro del ecosistema KACE. Guía a la persona usuaria por las decisiones de hardware de la impresora, deriva una configuración de Klipper, puede compilar el firmware correspondiente para el MCU y despliega los artefactos generados mediante rutas locales o remotas compatibles.

> [!WARNING]
> KACE no reemplaza Klipper ni elimina la puesta en marcha de la impresora. La persona responsable de la máquina debe comprobar el cableado, las asignaciones de pines, los límites de movimiento, calentadores, sensores, homing y el primer movimiento controlado.

## Inicio rápido

| Punto de partida | Ruta recomendada |
| --- | --- |
| Nuevo host de impresora Raspberry Pi | Usa [KACE Studio](https://github.com/3D-uy/KACE-studio) para grabar la imagen, configurar el primer arranque, descubrir la Pi, conectar por SSH e iniciar el flujo bootstrap fijado. |
| Host Linux Debian-family existente | Ejecuta el comando de instalación de abajo y luego inicia `kace`. |
| Clon del código fuente o configuración de contribución | Clona el repositorio, instala las dependencias bloqueadas y ejecuta `python kace.py`. |

```bash
KACE_COMMIT='8c6822553b966b3e7ce657cf5369b33730c37e07'; KACE_INSTALL_SHA256='29b4a5124d36bcdef852f4d6e966db7bf73ba853920c080826da8251b6dde930'; installer=$(mktemp); trap 'rm -f "$installer"' EXIT; curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" && printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - && KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

> [!WARNING]
> El comando fija un commit exacto, verifica el instalador antes de ejecutarlo y entrega la misma identidad inmutable al instalador transaccional. Actualiza commit y checksum solamente como un par revisado desde un canal confiable.

## Cómo fluye el ecosistema

```text
KACE Studio (Windows)
        │ imagen, ajustes de primer arranque, descubrimiento y SSH
        ▼
Host de impresora Raspberry Pi
        │ bootstrap.sh fijado aprovisiona el host
        ▼
KACE (CLI interactiva Linux)
        │ configuración y artefactos de firmware opcionales
        ▼
Klipper + puesta en marcha de la impresora
```

| Etapa | Responsabilidad |
| --- | --- |
| 🪟 [KACE Studio](https://github.com/3D-uy/KACE-studio) | Escribe una imagen de Raspberry Pi, inyecta archivos de red, primer arranque y bootstrap de KACE; después del arranque descubre la Pi, se conecta por SSH e inicia el `bootstrap.sh` inyectado. |
| 🍓 Bootstrap | Aprovisiona Klipper, Moonraker, la interfaz web seleccionada, soporte opcional de Crowsnest y KACE. Studio fija el bootstrap por commit Git inmutable y SHA-256 en CI. El bootstrap fija la URL del instalador de KACE, revisión y SHA-256 como un contrato. |
| 🧩 KACE | Guía las elecciones de la impresora, genera configuración y artefactos de firmware específicos y ofrece rutas de despliegue compatibles. |
| 🔧 Klipper y la persona operadora | Ejecutan Klipper y completan la secuencia oficial de verificación eléctrica, mecánica, térmica, homing y movimiento. |

Los marcadores legibles por máquina de etapas y errores en `scripts/bootstrap.sh` son consumidos por la interfaz de Studio y deben permanecer sincronizados.

## ¿Por qué KACE?

| Ruta manual | Ruta asistida por KACE |
| --- | --- |
| Reunir detalles de placa, movimiento, endstops, calentadores, sensores, sonda, pantalla y software en pasos separados. | Recopilar esas decisiones en un único flujo guiado de CLI. |
| Montar manualmente los artefactos de configuración y firmware. | Resolver perfiles mantenidos de placa y MCU, y después generar configuración, macros y artefactos de firmware opcionales. |
| Elegir transferencia y recuperación de manera ad hoc. | Usar rutas compatibles de medio local/extraíble, SSH/SFTP, Moonraker o despliegue de firmware USB protegido, con respaldo, validación y rollback donde estén implementados. |
| Validar físicamente la impresora después de cada cambio. | Validar físicamente la impresora después de cada cambio; KACE vuelve más repetibles los artefactos y el flujo, pero no reemplaza la puesta en marcha. |

## Características

| Área | Lo que proporciona KACE |
| --- | --- |
| 🧭 Configuración guiada | CLI interactiva en inglés, español y portugués. |
| 🧠 Perfiles | Resolución de perfiles de placa y MCU desde datos YAML mantenidos. |
| 🖨️ Movimiento y sondas | Generación de configuración para flujos Cartesian y CoreXY implementados; sin sonda, BLTouch, CR Touch, inductiva y sonda personalizada. |
| 🖥️ Pantallas | Comprobaciones de compatibilidad y configuración de pantalla generada donde se admite. |
| 📄 Artefactos generados | Generación de configuración y macros de Klipper desde plantillas del proyecto, almacenadas bajo `~/kace/` en el host de impresora. |
| ⚙️ Firmware | Derivación y compilación opcionales de firmware Klipper para MCU; estrategias exactas por placa para AVRDUDE, tarjeta SD y preparación UF2 validadas, con placas desconocidas limitadas a solo preparar. |
| 📦 Despliegue | Rutas de despliegue de configuración por medio local/extraíble, SSH/SFTP y Moonraker; soporte de respaldo, validación y rollback alrededor del despliegue. |

Se espera que las selecciones incompatibles o contradictorias fallen de forma segura, en lugar de producir una configuración que se sabe inválida.

## Estado actual

KACE está en desarrollo activo pre-1.0. Sus generadores de configuración, pruebas snapshot, comprobaciones de cobertura de placas, matrices de Klipper fijado y compilaciones de firmware en contenedor se ejecutan en CI. Esas comprobaciones automáticas no sustituyen la validación física en cada controladora, sonda, pantalla o impresora compatible.

La versión autoritativa del proyecto se guarda en `VERSION`.

> [!NOTE]
> Las pruebas automatizadas no prueban físicamente cada controladora, impresora, sonda, pantalla, disposición de cableado ni secuencia de puesta en marcha.

## Requisitos

| Público | Requisitos |
| --- | --- |
| Personas usuarias | Un host de impresora Linux de familia Debian, normalmente una Raspberry Pi; Python 3.11 o posterior; Git y paquetes estándar del sistema instalados por `install.sh`; acceso de red para la instalación y operaciones que obtienen datos upstream de Klipper; acceso adecuado al destino de despliegue elegido. |
| Personas contribuidoras | Python 3.11, Git y Docker para la matriz de validación con Klipper fijado y las compilaciones de firmware en contenedor. |

## Instalación

### Aprovisionar un nuevo host de impresora con KACE Studio

Para una Raspberry Pi nueva, usa [KACE Studio](https://github.com/3D-uy/KACE-studio). Studio gestiona la grabación de imagen, configuración del primer arranque, descubrimiento, acceso SSH y el flujo bootstrap fijado de KACE.

### Instalar directamente en un host Linux existente

El comando standalone instala desde un commit inmutable revisado:

```bash
KACE_COMMIT='8c6822553b966b3e7ce657cf5369b33730c37e07'; KACE_INSTALL_SHA256='29b4a5124d36bcdef852f4d6e966db7bf73ba853920c080826da8251b6dde930'; installer=$(mktemp); trap 'rm -f "$installer"' EXIT; curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" && printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - && KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

El instalador se descarga a un archivo temporal, se verifica antes de la ejecución y queda vinculado al mismo commit completo mediante `KACE_SOURCE_REF` y `KACE_EXPECTED_COMMIT`. El instalador verifica el commit obtenido y el checkout, crea un entorno virtual nuevo en staging y publica únicamente los paths de runtime que controla, con rollback. El launcher `kace` instalado compara en cada ejecución el pin persistido por bootstrap con el `HEAD` del repositorio local, por lo que no puede ejecutar silenciosamente otra revisión. Los artefactos generados existentes bajo `~/kace/` permanecen intactos.

### Ejecutar desde un clon del código fuente

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

Ejecuta `python kace.py --help` para ver las opciones disponibles de la CLI.

<details>
<summary>Recordatorio de seguridad de instalación</summary>

`main` es mutable. Fijar el instalador y la revisión fuente, comprobar un SHA-256 confiable por separado e inspeccionar el script es la ruta auditable cuando se requiere ese nivel de control.

</details>

## Flujo completo

1. Aprovisiona o prepara el host Linux de la impresora.
2. Inicia KACE con `kace` después de instalarlo, o con `python kace.py` desde un clon.
3. Selecciona el idioma y describe las elecciones de impresora, controladora, sistema de movimiento, endstops, cama, calentadores, sensores, sonda, pantalla y software.
4. Deja que KACE resuelva el perfil de placa y genere la configuración de Klipper bajo `~/kace/`.
5. Compila el firmware del MCU cuando lo requiera el flujo de la placa seleccionada.
6. Revisa los artefactos generados y desplíegalos mediante el destino local o remoto elegido.
7. Flashea el MCU únicamente de acuerdo con el procedimiento documentado por el fabricante de la controladora.
8. Inicia Klipper y completa su secuencia oficial de verificación antes de energizar calentadores u ordenar movimiento sin restricciones.

Para una ruta de firmware integrada, KACE muestra el progreso transaccional de instalación directamente en una terminal interactiva y mantiene `Ctrl+C` disponible para una cancelación segura. La salida redirigida, pipes, CI y terminales sin capacidades dinámicas reciben en su lugar líneas de progreso ASCII simples. Los mismos eventos canónicos de flujo se emiten como líneas JSON `KACE_WORKFLOW_EVENT` para KACE Studio; ninguna vista de terminal controla ni reconstruye la máquina de estados de instalación.

La identidad del MCU posterior al flasheo solo se acepta automáticamente cuando una evaluación puntuada incluye el puerto USB físico capturado o la topología `by-path` y el VID/PID de aplicación esperado por el perfil, sin evidencia contradictoria. Un serial estable agrega confianza, pero nunca reemplaza un puerto diferente o un VID/PID incorrecto. Los candidatos ambiguos requieren confirmación física explícita y la decisión queda registrada en el evento del workflow.

> [!TIP]
> Revisa los artefactos generados antes de desplegarlos y trata el primer encendido, homing, calentadores, sensores y comprobaciones de movimiento como pasos de seguridad controlados por la persona operadora.

## Arquitectura

| Área | Responsabilidad |
| --- | --- |
| `kace.py` | Punto de entrada de CLI, análisis de argumentos y orquestación de alto nivel. |
| `core/wizard/` | Flujo interactivo y selecciones normalizadas de la persona usuaria. |
| `core/scraper.py`, `core/hardware_detector.py` | Obtención de configuración upstream y descubrimiento de hardware. |
| `core/generator.py`, `core/templates.py` | Generación de configuración y macros de Klipper. |
| `firmware/` | Derivación/compilación de firmware más artefactos tipados y estrategias exactas de despliegue por placa. |
| `data/firmware_deployments.yaml` | IDs exactos de placa, nombres nativos/finales, offsets de bootloader, instrucciones de entrada, identidad USB esperada, método físico y contrato de verificación posterior. |
| `core/deployer.py`, `core/moonraker.py`, `core/moonraker_deployer.py` | Rutas de despliegue, instalación transaccional, transferencia remota, respaldo y rollback. |
| `core/terminal_progress.py` | Vistas TTY nativas y orientadas a líneas de los eventos canónicos de instalación. |
| `data/`, `templates/`, `config/` | Contratos de placa, traducciones, plantillas de contenido generado y datos de configuración. |
| `scripts/bootstrap.sh` | Contrato de integración que usa KACE Studio para aprovisionar un host de impresora. |
| `tests/` | Validación unitaria, regresión, snapshot, esquema, sweep y matriz de Klipper fijado. |

Los artefactos generados para la impresora permanecen separados del árbol fuente en `~/kace/`.

## Tecnologías

- Python, Questionary, PyYAML y Jinja2.
- Paramiko para la ruta opcional de despliegue SSH/SFTP.
- Bash para instalación y aprovisionamiento del host.
- Docker para análisis reproducible de Klipper y validación de compilación de MCU.
- GitHub Actions para CI.

## Pruebas y validación

Instala las dependencias de ejecución bloqueadas y luego ejecuta la validación más acotada necesaria para el cambio:

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
```

La matriz completa por pares está pensada para uso manual o previo a una versión:

```bash
python tests/matrix/run_matrix.py --profile full
```

La matriz genera configuraciones a través del flujo real de KACE, valida los casos aceptados con un commit fijo de Klipper dentro de Docker, distingue rechazos seguros esperados de fallos y escribe informes Markdown y JSON. El sweep más amplio de configuración upstream está disponible con:

```bash
python tests/run_tests.py --full-klipper-sweep --verbose
```

Los modos de actualización de snapshots son operaciones de mantenimiento y no deben usarse solamente para hacer que una prueba fallida pase. Consulta [Pruebas](TESTING.md) para la distribución y expectativas de las pruebas.

## Docker

KACE se instala directamente en el host de la impresora; no se distribuye como contenedor de ejecución. La imagen Docker del repositorio existe para desarrollo y validación reproducibles:

```bash
docker build -f docker/ci/Dockerfile -t kace-dev .
docker run --rm -it -v "$PWD:/workspace" kace-dev
```

El ejecutor de matrices también utiliza Docker para ejecutar el cargador real de configuración desde su revisión fijada de Klipper. Ningún dispositivo físico es accedido por estos trabajos de validación.

## CI/CD

GitHub Actions comprueba actualmente:

- Sintaxis de Python.
- Pruebas unitarias y de regresión snapshot.
- Esquema y reglas de precedencia de `boards.yaml`.
- Una matriz reducida de KACE a Klipper en pull requests y pushes.
- El sweep completo y fijado de configuración upstream en pushes a `main`, o mediante activación manual explícita.
- Una matriz completa por pares cuando se ejecuta manualmente.
- Compilaciones de firmware en contenedor para objetivos representativos LPC1769, STM32, RP2040 y AVR.

CI valida el código fuente y los artefactos generados. No publica una versión ni prueba impresoras reales ni flashea controladoras físicas.

## Compatibilidad y límites

- Objetivo de ejecución: hosts Linux de familia Debian con Python 3.11 o posterior.
- Cobertura de generación automatizada: flujos Cartesian y CoreXY implementados, y todos los contratos de placa requeridos por la matriz.
- Cobertura de sondas automatizada: ninguna, BLTouch, CR Touch, inductiva y personalizada; las combinaciones dockable no compatibles se clasifican como rechazos seguros.
- KACE Studio realiza el flujo de aprovisionamiento del lado Windows; KACE se ejecuta en el host Linux de la impresora.
- Klipper upstream, las definiciones de placas y las interfaces web de terceros pueden cambiar de forma independiente. La matriz fijada detecta incompatibilidades del parser, pero no puede demostrar seguridad eléctrica o mecánica.

## Roadmap

Antes de 1.0, el proyecto debe priorizar versiones reproducibles, sincronización de contratos entre ambos repositorios, calificación de hardware documentada, evidencia de instalación de extremo a extremo y cierre de riesgos conocidos de seguridad y compatibilidad. Después de 1.0, el trabajo debe centrarse en cobertura de placas medida, estabilidad de migración y diagnósticos para contribuidores. La automatización más amplia o familias de hardware adicionales pertenecen a un roadmap posterior solo después de contar con pruebas y mantenedores.

Consulta [CHANGELOG.md](../../CHANGELOG.md) para los cambios registrados. Los elementos del roadmap son intenciones, no funciones ya entregadas.

## Contribuir

Lee la [guía de contribución](CONTRIBUTING.md), la [política de seguridad](../../SECURITY.md) y el [código de conducta](../../CODE_OF_CONDUCT.md) antes de abrir un cambio. Mantén los cambios acotados, añade la cobertura de regresión relevante más pequeña y no actualices snapshots sin revisar la diferencia generada.

Los issues y pull requests se gestionan en el [repositorio de KACE](https://github.com/3D-uy/KACE).

## Licencia

KACE se distribuye bajo la [GNU General Public License v3.0](../../LICENSE).
