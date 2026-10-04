![KACE — Klipper Automated Configuration Ecosystem](../assets/kace_banner.png)

# KACE

### Klipper Automated Configuration Ecosystem

**Configuración guiada de impresoras, preparación de firmware y despliegue para Klipper.**

[![KACE version 0.9.4-rc.3](https://img.shields.io/badge/KACE-0.9.4--rc.3-e88c30?style=flat-square)](../../VERSION)
[![Status: pre-release](https://img.shields.io/badge/status-pre--release-d29b32?style=flat-square)](#estado-del-proyecto)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](../en/INSTALLATION.md)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-2d718f?style=flat-square)](../../LICENSE)
[![GitHub Actions: KACE CI](https://img.shields.io/github/actions/workflow/status/3D-uy/kace/ci.yml?branch=main&style=flat-square&label=tests&logo=githubactions&logoColor=white)](https://github.com/3D-uy/kace/actions/workflows/ci.yml)<br>
[![Host: Linux](https://img.shields.io/badge/host-Linux-454545?style=flat-square&logo=linux&logoColor=white)](../en/INSTALLATION.md)
[![Host: Raspberry Pi](https://img.shields.io/badge/host-Raspberry_Pi-A22846?style=flat-square&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/software/)
[![For Klipper](https://img.shields.io/badge/for-Klipper-e88c30?style=flat-square)](https://www.klipper3d.org/)
[![API: Moonraker](https://img.shields.io/badge/API-Moonraker-5965a8?style=flat-square)](https://moonraker.readthedocs.io/en/latest/)
[![GitHub stars](https://img.shields.io/github/stars/3D-uy/kace?style=flat-square&logo=github&label=stars&color=e3b341)](https://github.com/3D-uy/kace)

🌐 [English](../../README.md) · [Español](README.md) · [Português](../pt/README.md)

KACE te guía por las decisiones de hardware de tu impresora para generar y revisar su configuración de Klipper.
Su asistente de terminal prepara firmware MCU cuando está admitido y te acompaña hasta la aplicación y verificación de la instalación.

[Inicio rápido](#inicio-rápido) · [Hardware](#hardware-y-plataformas) · [KACE Studio](#kace-studio) · [Documentación](#documentación)

<a id="qué-hace-kace"></a>

## ✨ Qué hace KACE

| Capacidad | Qué obtienes |
| --- | --- |
| 🔌 **Elegir hardware** | Selección de placa/MCU, motores, sondas, termistores y ventiladores. |
| 📄 **Generar configuración** | `printer.cfg` y las macros correspondientes en `~/kace/`, a partir de perfiles revisados y tus respuestas. |
| ⚙️ **Preparar firmware** | Compilación para las MCU declaradas, con el método de instalación disponible y los pasos manuales necesarios. |
| 🔎 **Revisar cambios** | Diferencias antes de aplicar, conservando los valores de calibración admitidos y las secciones del usuario. |
| ✅ **Aplicar y verificar** | Despliegue en el host y comprobaciones de activación e identidad de firmware requeridas. |

<a id="un-vistazo-al-asistente"></a>
<a id="configuración-guiada"></a>

## 🧙 Configuración guiada

El asistente de terminal ofrece **español, inglés y portugués**, con modos **Principiante** y **Avanzado**.

> **Elegir hardware** → **Configuración guiada** → **Generar configuración Klipper**<br>
> → **Compilar firmware MCU** → **Revisar** → **Aplicar** → **Verificar**

Los pasos de firmware dependen del destino admitido y del flujo elegido.

<!-- Insertar aquí una captura real del asistente/revisión: docs/assets/kace-wizard.png.
     Incluir texto alternativo y la versión de KACE capturada. No usar un mockup como captura del producto. -->

Los drivers TMC extraíbles usan el cableado revisado del conector aunque el ejemplo del perfil nombre otro chip. El mapeo entre modelos requiere corrientes explícitas; ver [alcance y perfiles admitidos (EN)](../TMC_SOCKET_MAPPING.md).

<a id="inicio-rápido"></a>

## 🚀 Inicio rápido

En una **Raspberry Pi o un host Linux existente**, abre una terminal o conecta por SSH.
Necesitas **Python 3.11+**, Git, Bash, soporte venv de Python y acceso a internet.
El instalador puede solicitar sudo para dependencias del sistema y el comando `kace`.

```bash
git clone https://github.com/3D-uy/KACE.git kace-source &&
cd kace-source &&
KACE_SOURCE_REF="$(git rev-parse HEAD)" bash install.sh
```

Esto instala en `~/kace/` la revisión que acabas de clonar y abre KACE.
Ejecuta `kace` para volver a abrirlo. Esta opción sigue la rama predeterminada actual del repositorio; para el candidato fijo, usa la opción verificada siguiente.

Tras revisar los cambios, confirma la aplicación y activación, y realiza las [comprobaciones de hardware (EN)](../HARDWARE_TESTING.md) antes de imprimir.

Aplicar y verificar la configuración requiere un host con Klipper/Moonraker funcionando.
Para una Pi nueva, comienza con [KACE Studio](#kace-studio) o la [preparación manual del host (EN)](../en/INSTALLATION.md).

<a id="instalación-verificada-pinned"></a>

### 🔒 Instalación verificada / pinned

Para usar un candidato fijo y verificar el checksum del instalador, utiliza el comando siguiente.
Conserva la referencia fijada existente y puede diferir del código actual.

<details>
<summary>Mostrar el comando de instalación fijada</summary>

Requiere `curl` y `sha256sum`. Revisa el script antes de ejecutarlo.

```bash
KACE_COMMIT='b7988b57b5fc80fbc55c3d1326768289dbccb179'
KACE_INSTALL_SHA256='de7db74da6f6261bf28fa329067f9d3424bc3e5abde5db4dd91c3f66861f3500'
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" &&
printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - &&
KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

</details>

<a id="kace-studio"></a>

## 🖥️ KACE Studio

[KACE Studio](https://github.com/3D-uy/KACE-studio) es la aplicación de escritorio complementaria para preparar una Raspberry Pi desde **Windows 10/11**.

- Escribe una imagen de Pi en SD/USB y configura hostname, cuenta, red y SSH para el primer arranque.
- Descubre la Pi y conecta mediante un espacio de trabajo SSH.
- Explora y descarga archivos por SFTP, y continúa la configuración con KACE en la Pi.

**Studio prepara el host; KACE configura la impresora.** Studio requiere Microsoft Edge WebView2 Runtime y también está en fase previa a 1.0.
Consulta sus [instrucciones de inicio](https://github.com/3D-uy/KACE-studio/blob/main/docs/es/README.md) para instalación e imágenes/plataformas disponibles.

<a id="hardware-y-plataformas"></a>

## 🔌 Hardware y plataformas

| Área | Alcance actual |
| --- | --- |
| Host de KACE | Raspberry Pi / Linux con Python 3.11+; la activación utiliza Klipper y Moonraker. |
| Configuración de impresora | Cartesiana y CoreXY, un extrusor principal y cama caliente, con los flujos admitidos de motores, sondas y ventiladores. |
| Preparación desde escritorio | KACE Studio en Windows 10/11; Studio valida las opciones de modelo de Pi y SO. |

Los [contratos de placa actuales](../../data/board_contracts/v1/) declaran flujos de firmware en ejecución para estos destinos exactos:

| Placa | Variante MCU | Conexión al host |
| --- | --- | --- |
| BTT SKR Mini E3 v3.0 | STM32G0B1 | USB nativo |
| BTT SKR v1.4 / v1.4 Turbo | LPC1768 / LPC1769, respectivamente | USB nativo |
| BTT SKR Pico v1.0 | RP2040 | USB nativo |
| Creality v4.2.7 | STM32F103 | Puente serie USB, USART1 de la MCU |
| MKS Robin Nano V3 | STM32F407 | USB nativo |

Son flujos implementados en software, **no una lista de impresoras certificadas físicamente**.
La revisión de placa, MCU, cableado, bootloader y método de instalación deben coincidir con el destino elegido.
Otras entradas pueden ser provisionales, de solo configuración o de solo preparación; encontrar un perfil de Klipper no acredita soporte completo.
Consulta el [alcance (EN)](../en/SUPPORT_SCOPE.md) y los [perfiles de instalación de firmware](../../data/firmware_deployments.yaml).

<a id="estado-del-proyecto"></a>

## 🧪 Estado del proyecto

KACE está en fase **previa a 1.0**. Consulta [VERSION](../../VERSION) para la versión del código, [CHANGELOG](../../CHANGELOG.md) para los cambios y [ROADMAP](ROADMAP.md) para el trabajo pendiente.

- La validación física sigue pendiente; debes comprobar sensores, endstops, movimiento y calentamiento en tu impresora.
- Múltiples extrusores, IDEX/toolchangers y la migración general de perfiles arbitrarios de Klipper quedan fuera del alcance actual.
- La generación guiada de pantallas activas aún no dispone de una combinación placa/pantalla calificada; consulta [soporte de pantallas](DISPLAYS.md).
- Algunos cambios remotos requieren aplicación manual. KACE cubre la instalación inicial y sus reanudaciones pendientes; no supervisa ediciones posteriores.

<a id="documentación"></a>

## 📚 Documentación

| Para… | Consulta |
| --- | --- |
| Preparar el host, instalar y ejecutar desde código | [Guía de instalación (EN)](../en/INSTALLATION.md) |
| Revisar configuración, desplegar, coordinar ediciones y recuperar | [Guía de despliegue (EN)](../en/DEPLOYMENT.md) |
| Consultar límites de hardware y funciones | [Alcance (EN)](../en/SUPPORT_SCOPE.md) · [Pantallas](DISPLAYS.md) |
| Comprobar la impresora antes de usarla | [Pruebas de hardware (EN)](../HARDWARE_TESTING.md) |
| Arquitectura, contratos, pruebas y entornos de compilación | [Guía de desarrollo (EN)](../DEVELOPMENT.md) |
| Versiones fijadas, checksums y validación de releases | [Guía de releases (EN)](../RELEASE.md) |
| Trabajo previsto y cambios recientes | [Roadmap](ROADMAP.md) · [Changelog](../../CHANGELOG.md) |

<a id="desarrollo-y-contribuciones"></a>

## 🛠️ Desarrollo y contribuciones

Puedes contribuir con reportes de errores, mejoras de documentación y soporte de hardware revisado.
Comienza por la [guía de desarrollo (EN)](../DEVELOPMENT.md) para conocer el código, preparar el entorno y ejecutar las pruebas relevantes.
Al reportar un error, incluye revisión de KACE, entorno del host, placa/MCU exactas y pasos de reproducción, sin credenciales.

Respeta el [código de conducta (EN)](../../CODE_OF_CONDUCT.md). Reporta vulnerabilidades según la [política de seguridad (EN)](../../SECURITY.md).

<a id="comunidad-y-agradecimientos"></a>

## ❤️ Comunidad y agradecimientos

**Un agradecimiento especial al proyecto Klipper y a su comunidad** por el firmware, los ejemplos de configuración, la documentación y el conocimiento compartido que hacen posible KACE.

| Proyecto | Su relación con KACE |
| --- | --- |
| [<img src="https://www.klipper3d.org/img/klipper.svg" width="24" height="24" alt="">&nbsp;Klipper](https://www.klipper3d.org/) | Firmware y sistema de configuración al que se dirige KACE; los perfiles revisados y el código upstream sustentan la generación y compilación MCU. |
| [<img src="https://moonraker.readthedocs.io/en/latest/assets/images/favicon.png" width="24" height="24" alt="">&nbsp;Moonraker](https://moonraker.readthedocs.io/en/latest/) | API del host utilizada para acceder a configuraciones, activar cambios y comprobar el estado de impresora/firmware. |
| [<img src="https://docs.mainsail.xyz/assets/logo.svg" width="24" height="24" alt="">&nbsp;Mainsail](https://docs.mainsail.xyz/) y<br>[<img src="https://docs.mainsail.xyz/assets/logo.svg" width="24" height="24" alt="">&nbsp;MainsailOS](https://docs.mainsail.xyz/mainsailos/) | Interfaz ofrecida por el bootstrap y base de imagen preconfigurada utilizada por Studio. |
| [<img src="https://raw.githubusercontent.com/fluidd-core/fluidd/7a75e4857282a24d733540ebf07cf6b1bc7717e9/public/img/icons/favicon-32x32.png" width="24" height="24" alt="">&nbsp;Fluidd](https://docs.fluidd.xyz/) | Interfaz alternativa que instala el bootstrap cuando se selecciona, incluida su configuración cliente. |
| [<img src="https://downloads.raspberrypi.com/raspios_armhf/Raspberry_Pi_OS_(32-bit).png" width="24" height="24" alt="">&nbsp;Raspberry&nbsp;Pi](https://www.raspberrypi.com/software/) | Ecosistema del host, opciones de imagen Raspberry Pi OS e Imager para la preparación manual. |
| [<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mainsail-crew/crowsnest/436042452f564f3d737e3b980a213f849a8a0562/.github/crowsnest-logo-darkmode.png"><img src="https://raw.githubusercontent.com/mainsail-crew/crowsnest/436042452f564f3d737e3b980a213f849a8a0562/.github/crowsnest-logo-lightmode.png" width="24" height="24" alt=""></picture>&nbsp;Crowsnest](https://docs.mainsail.xyz/crowsnest/) | Streaming de cámara opcional instalado mediante el bootstrap. |

Reporta errores y propone mejoras mediante los [issues de KACE](https://github.com/3D-uy/kace/issues).

**KACE es un proyecto independiente y no está oficialmente afiliado ni respaldado por Klipper ni por los demás proyectos aquí mencionados.**

<a id="licencia"></a>

## 📜 Licencia

KACE es software open source bajo la [GNU GPL v3](../../LICENSE).
