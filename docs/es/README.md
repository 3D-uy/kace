# KACE

🌐 [English](../../README.md) · [Español](../../docs/es/README.md) · [Português](../../docs/pt/README.md)

![KACE](../../docs/assets/kace_banner.png)

KACE es la CLI en Python que se ejecuta en el host de la impresora para preparar, revisar y desplegar configuración Klipper y artefactos de firmware MCU. [KACE Studio](https://github.com/3D-uy/KACE-studio/blob/main/docs/es/README.md) prepara la Raspberry Pi desde Windows y ofrece SSH/SFTP; KACE conserva la autoridad sobre configuración e instalación.

**Pre-1.0; calificación controlada.** [VERSION](../../VERSION) declara la versión y [CHANGELOG](../../CHANGELOG.md) describe el candidato actual. Los cambios de código sin commit no forman parte del instalador fijado. La validación automática no certifica hardware físico ni una release estable.

## Inicio rápido

Requiere Linux/Raspberry Pi, Python 3.11+, Git, red para las dependencias y los permisos necesarios para el flujo elegido. Docker/toolchains solo son necesarios en los flujos de compilación y validación documentados.

Para una Pi nueva, usa **KACE Studio**. Para un host Linux existente, el siguiente instalador verifica su identidad inmutable antes de ejecutarse. Revísalo antes de usarlo: instala la revisión fijada, que puede diferir del código que estás leyendo.

```bash
KACE_COMMIT='b7988b57b5fc80fbc55c3d1326768289dbccb179'
KACE_INSTALL_SHA256='de7db74da6f6261bf28fa329067f9d3424bc3e5abde5db4dd91c3f66861f3500'
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" &&
printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - &&
KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

Para ejecutar el checkout actual del código:

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

También puedes preparar el host manualmente: en Raspberry Pi Imager selecciona la Pi exacta y un SO compatible, almacenamiento de destino, hostname, usuario, red y SSH; revisa y confirma la escritura destructiva. Expulsa de forma segura, arranca la Pi y conecta usando su hostname o la IP asignada por el router. Instala KACE allí con el comando verificado anterior. Preparar el SO no configura ni calibra la impresora.

## 🧭 Uso

1. Ejecuta `kace` tras instalar, o `python kace.py` desde el entorno del código activado. Selecciona idioma y nivel de experiencia.
2. Selecciona placa/MCU exacta, geometría, motores, probes y demás recursos admitidos; revisa pines y requisitos eléctricos.
3. Revisa los artefactos en `~/kace/`. Sigue el procedimiento de entrega del firmware y la verificación de identidad física.
4. Revisa el diff de configuración y los ajustes conservados, acepta aplicación/activación y espera la finalización verificada. Moonraker local en la Pi usa `127.0.0.1:7125`.
5. Comprueba sensores, endstops, movimiento y calentamiento por separado con la guía de hardware. Ante una interrupción, sigue el checkpoint y las instrucciones de recuperación.

## ⚠️ Alcance y límites

- Hay flujos Cartesian/CoreXY; encontrar un perfil upstream no garantiza compatibilidad. Firmware runtime, provisional, solo preparación y solo configuración son categorías diferentes.
- Se bloquean pantallas desconocidas, circuitos obligatorios no soportados y dependencias de perfiles sin revisar. Consulta [alcance](../../docs/en/SUPPORT_SCOPE.md) y [pantallas](../../docs/es/DISPLAYS.md).
- No guardes cambios desde Mainsail/SSH durante la publicación. La escritura local usa locks cooperativos y reemplazo atómico por archivo, no una transacción de todo el directorio frente a editores externos. Los planes remotos modificados y el reemplazo de archivos existentes pueden requerir propuestas manuales.
- El rollback conserva cambios vivos y snapshots duraderos si no puede probar una restauración segura. `Ready` no basta: se requieren activación y evidencia de artefactos y firmware.
- La responsabilidad cubre la instalación inicial y sus reanudaciones pendientes hasta `DONE`/`COMPLETE`; no se promete supervisar ni revalidar ediciones posteriores del usuario.

## 🛠️ Desarrollo

Consulta [Desarrollo (EN)](../../docs/DEVELOPMENT.md) para arquitectura, contribución y pruebas. Ejecuta primero la regresión específica y después los gates afectados. La suite completa incluye funciones pytest que unittest no recoge. Nunca actualices snapshots solo para hacer pasar un fallo.

## 📚 Documentación

| Necesidad | Guía |
| --- | --- |
| Desarrollo, arquitectura y pruebas (EN) | [DEVELOPMENT.md](../DEVELOPMENT.md) |
| Despliegue y recuperación (EN) | [DEPLOYMENT.md](../../docs/en/DEPLOYMENT.md) |
| Calificación de hardware (EN) | [HARDWARE_TESTING.md](../../docs/HARDWARE_TESTING.md) |
| Alcance (EN) | [SUPPORT_SCOPE.md](../../docs/en/SUPPORT_SCOPE.md) |
| Pantallas | [DISPLAYS.md](../../docs/es/DISPLAYS.md) |
| Release (EN) | [RELEASE.md](../../docs/RELEASE.md) |
| Código de conducta (EN) | [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |
| Notas del candidato actual | [CHANGELOG.md](../../CHANGELOG.md) |
| Seguridad (EN) | [SECURITY.md](../../SECURITY.md) |

## Licencia

[GPL-3.0](../../LICENSE).
