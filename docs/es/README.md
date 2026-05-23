<p align="center">
  <img src="../assets/kace_banner.png" width="1000">
</p>

<h1 align="center">🚀 KACE — Klipper Automated Configuration Ecosystem</h1>

<p align="center">
  <a href="https://github.com/3D-uy/kace/actions/workflows/ci.yml">
    <img src="https://github.com/3D-uy/kace/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI">
  </a>
  <img src="https://img.shields.io/badge/version-v0.9.0-blue?style=flat-square" alt="Versión">
  <img src="https://img.shields.io/badge/configs%20validadas-192-brightgreen?style=flat-square" alt="Configs Validadas">
  <img src="https://img.shields.io/badge/plataforma-Linux%20%7C%20Raspberry%20Pi-green?style=flat-square" alt="Plataforma">
  <img src="https://img.shields.io/github/license/3D-uy/KACE?style=flat-square" alt="Licencia">
</p>

<p align="center">
🌐 <strong>Idioma</strong><br>
🇺🇸 <a href="../../README.md">English</a> | 🇪🇸 Español | 🇧🇷 <a href="../pt/README.md">Português</a>
</p>

---

## ⚡ Instala Klipper sin dolores de cabeza

KACE automatiza todo el proceso de configuración de **Klipper**, desde la detección de hardware hasta la compilación de firmware y la generación de configuración lista para usar.

👉 Menos errores  
👉 Menos tiempo  
👉 Más impresión

---

## 🧠 ¿Qué es KACE?

Un **motor inteligente de configuración y firmware** que:

- 🔍 Detecta automáticamente tu hardware (MCU)
- 📦 Obtiene las configuraciones oficiales de Klipper desde GitHub
- ⚙️ Genera un `printer.cfg` limpio y listo para usar
- 🔥 Compila el firmware (`klipper.bin` / `.uf2` / `.hex`)
- 🧭 Te guía interactivamente solo cuando es estrictamente necesario
- 🌐 Funciona en Español, Inglés y Portugués

---

## ⚡ Instalación en una línea

```bash
bash <(curl -s https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> Instala todas las dependencias, clona el repositorio (shallow + sparse) y configura el comando global `kace` automáticamente.

---

## 📋 Requisitos

✔ Raspberry Pi con Mainsail OS / FluiddPI (Klipper + Moonraker preinstalados)  
✔ Acceso SSH a tu Pi

❌ Ya **no necesitas**:

- Compilar firmware manualmente
- Crear archivos `printer.cfg` a mano

---

## 🎬 Documentación

| Guía | Enlace |
|------|--------|
| Guía de Testing | [`docs/en/TESTING.md`](../en/TESTING.md) |
| Contribución | [`docs/en/CONTRIBUTING.md`](../en/CONTRIBUTING.md) |
| Release Engineering | [`docs/RELEASE.md`](../RELEASE.md) |
| Compatibilidad de Pantallas 🖥️ | [`docs/es/DISPLAYS.md`](DISPLAYS.md) |
| Configuración Pi Imager 🇪🇸 | [`docs/es/pi_imager.md`](pi_imager.md) |
| Instalación Klipper 🇪🇸 | [`docs/es/Klipper_install.md`](Klipper_install.md) |
| **Resultados del Sweep Completo 📊** | [`SWEEP_RESULTS.md`](../../SWEEP_RESULTS.md) |
| English 🇺🇸 | [`README.md`](../../README.md) |
| Português 🇧🇷 | [`docs/pt/README.md`](../pt/README.md) |

---

## 🟢 Estado de Validación

KACE ha sido validado contra la **biblioteca completa de configuraciones oficiales de Klipper** usando su framework de regresión automatizado.

**Último sweep completo — 192 configs probadas contra [Klipper master](https://github.com/Klipper3d/klipper/tree/master/config):**

| Resultado | Cantidad | Significado |
|-----------|----------|-------------|
| ✅ **PASS** | **172** | Parse + generación de config completados con éxito |
| 🔵 **UNSUPPORTED** | **20** | Config usa secciones fuera del alcance actual de KACE (neopixel, adxl345) |
| 🟠 **SAFE\_ABORT** | **0** | — |
| 🔴 **FAILURE** | **0** | **Cero crashes** |

- **Cero excepciones Python** en las 192 configs oficiales
- **Cero fallos de template** — todas las configs parseables se generan limpiamente
- **Cero regresiones del parser** — output determinístico en cada ejecución
- **10 advertencias de generación** — todas impresoras delta donde el propio Klipper incluye pines `TODO` por diseño

Las configs no soportadas contienen funcionalidades fuera del alcance actual de KACE:
controladores RGB/neopixel, expansores GPIO SX1509 o acelerómetros ADXL345.
KACE **las reporta de forma elegante** en lugar de fallar.

📄 **[Ver los resultados completos del sweep → SWEEP_RESULTS.md](../../SWEEP_RESULTS.md)**  
Incluyendo el desglose por config de las 192 placas, impresoras y pantallas.

> Ejecuta el sweep tú mismo: `python3 tests/run_tests.py --full-klipper-sweep`

---

## 🧪 Pruebas Automatizadas

KACE incluye un framework de pruebas de nivel productivo construido sobre la biblioteca estándar de Python — **sin dependencias de testing externas**.

| Qué | Cómo |
|-----|------|
| Tests unitarios | Lógica de derivación, carga YAML, inyección BLTouch, deployer offline |
| Regresión por snapshot | Archivos `.cfg` dorados bloqueados por placa — falla ante cualquier diferencia de caracteres |
| Integridad YAML | Validación de schema + verificación de precedencia de patrones en cada ejecución |
| Sweep de configs completo | 192+ configs oficiales de Klipper parseadas y clasificadas en cada push a `main` |
| Pipeline CI | GitHub Actions — 5 etapas, cancelación de concurrencia, bloqueo de merge |

```
Estado actual: 59/59 tests pasando ✅
```

```bash
python3 tests/run_tests.py                       # suite completa
python3 tests/run_tests.py --yaml-check          # solo integridad YAML
python3 tests/run_tests.py --full-klipper-sweep  # sweep de 192 configs
```

Ver [`docs/en/TESTING.md`](../en/TESTING.md) para la guía completa de testing.

---

## 🏗️ Aspectos Arquitectónicos Destacados

- **Base de datos de hardware en YAML** — agrega una placa nueva con solo editar YAML, sin cambios en Python
- **Derivación modular de firmware** — MCU → parámetros Kconfig mediante coincidencia de patrones ordenados
- **Recuperación automática con fallback** — cada carga de datos tiene un fallback codificado; los fallos de YAML nunca afectan la producción
- **Instalador sparse + shallow** — mínima descarga en hardware Raspberry Pi
- **Dependencias opcionales diferidas** — el soporte SSH se instala al primer uso, no durante la instalación
- **Generación de config determinística** — el renderizado Jinja2 está protegido por snapshots y es reproducible
- **Clasificación de sweep en 4 códigos** — `PASS / SAFE_ABORT / UNSUPPORTED / FAILURE` para diagnósticos claros

Ver [`docs/en/ARCHITECTURE.md`](../en/ARCHITECTURE.md) para la referencia completa.

---

## 🛠️ Características Principales

| Característica | Descripción |
| --- | --- |
| 🔍 **Auto-detección de MCU** | Identifica tu placa conectada via USB/serial |
| 🧠 **Motor Inteligente** | Deriva la config de firmware sin `make menuconfig` manual |
| ⚙️ **Config Generator** | Genera un `printer.cfg` limpio desde datos oficiales de Klipper |
| 🔥 **Firmware Builder** | Compila `klipper.bin` / `.uf2` / `.hex` automáticamente |
| 🧪 **Pre-validación** | Detecta pines TODO y errores antes de llegar a tu impresora |
| 🌐 **GitHub Scraper** | Siempre usa configuraciones oficiales y actualizadas de Klipper |
| 💻 **CLI Interactiva** | Wizard guiado en ES / EN / PT con interfaz ANSI a color |
| 📡 **Dashboard del Sistema** | Detecta Klipper, Moonraker, Mainsail, Fluidd, Crowsnest al inicio |

---

## 🧭 Cómo funciona

```
1. 🔍 Detectar MCU via USB/serial
2. 📦 Obtener config oficial de Klipper para tu placa
3. 🧠 Derivar parámetros de firmware (familia MCU → Kconfig)
4. 💬 Preguntar solo lo que no puede asumirse con seguridad
5. ⚙️ Generar printer.cfg (Jinja2, validado, sin pines TODO)
6. 🔥 Compilar firmware automáticamente
7. 📁 Desplegar en ~/kace/ (o USB / SSH)
```

---

## 📦 Resultado Final

```
~/kace/
├── printer.cfg          # Configuración de Klipper lista para usar
└── klipper.bin          # Firmware compilado (o .uf2 / .hex)
```

---

## 🚀 Siguientes Pasos

1. Flashear firmware en tu placa (tarjeta SD / USB)
2. Subir `printer.cfg` a Klipper / Moonraker
3. Reiniciar:

```bash
sudo reboot
```

---

## 🙌 Contribuir y Feedback

KACE evoluciona con la comunidad:

* 🐛 [Reportar bugs](https://github.com/3D-uy/kace/issues)
* 💡 Sugerir mejoras
* 🤝 [Contribuir — leer la guía](../en/CONTRIBUTING.md)

---

## ⚠️ Aviso Legal

KACE es una herramienta open-source diseñada para simplificar la configuración de Klipper.

El uso del software es **bajo tu propia responsabilidad**.  
El autor no se responsabiliza por **daños de hardware, configuraciones incorrectas o comportamientos inesperados** resultantes de la configuración generada.

👉 Siempre revisa el `printer.cfg` generado antes de imprimir.  
👉 Verifica el firmware antes de flashear.

---

## 🗑️ Desinstalar

```bash
sudo rm -f /usr/local/bin/kace   # o: rm -f ~/.local/bin/kace
rm -rf ~/kace
```

---

## 📜 Licencia

KACE está licenciado bajo GPL-3.0 🛠️

Para uso comercial, distribución en productos de pago o cambio de marca, contacta al autor.  
El nombre "KACE" y su imagen de marca no pueden usarse en productos comerciales sin permiso.

---

<p align="center">

⭐ Si te gusta este proyecto, dale una estrella  
🚀 Hecho para simplificar Klipper

</p>
