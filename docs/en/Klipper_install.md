# 🚀 KLIPPER easy installation

![Firmware](https://img.shields.io/badge/Firmware-Klipper-orange)
![Board](https://img.shields.io/badge/Board-SKR%201.4%20%2F%201.4%20Turbo-blue)
![Raspberry](https://img.shields.io/badge/Raspberry-Pi%203B-red)
![Interface](https://img.shields.io/badge/UI-Mainsail-purple)
![Guide](https://img.shields.io/badge/Guide-Simple%20installation-success)

<p align="center">

🌐 **Language**  
🇺🇸 English | 🇪🇸 <a href="../es/Klipper_install.md">Español</a> | 🇧🇷 <a href="../pt/Klipper_install.md">Português</a>

</p>

# 🧠 The ultimate guide to installing Klipper

This tutorial is designed to be followed along with the video.  
Simply copy each block of code and paste it into the terminal.  
You don’t need to type commands manually.

---

# 📋 REQUIREMENTS

- 🧠 Raspberry Pi (as an example we will use a Raspberry Pi 3B)
- 🧩 Example board: SKR 1.4 Turbo
- 💾 Good quality SD card for the Raspberry
- 💾 SD card to load firmware on the SKR
- 🔌 USB cable between Raspberry and SKR
- 💻 Windows PC
- 🖥️ MobaXterm installed

## 🔗 All links can be found below

---

# 💿 PART 1 — Flash MainsailOS to the SD card

Before starting, you need to flash the operating system onto the Raspberry Pi SD card.

We will use **Raspberry Pi Imager**, the official tool.

📥 Download here  

  Official website https://www.raspberrypi.com/software/

[Guide to install **Raspberry Pi Imager**](pi_imager.md)

The program will download the image and flash it automatically.

# 📥 Meanwhile download the following program

## 🖥️ Download MobaXterm

   Official website  
   https://mobaxterm.mobatek.net/download.html

---

# ⚡ When finished installing **Raspberry Pi Imager**

1. Remove the SD card
2. Insert it into the **Raspberry Pi**
3. Power on the Raspberry

  ## Wait approximately **1 to 2 minutes** for the system to fully boot.


# 📡 PART 2  Open MainsailOS.

### Open your browser and go to:
```
klipper.local
```
*(Or the custom hostname you set in Raspberry Pi Imager)*
If Mainsail opens → perfect.

---

# 🔐 PART 3 — Connect via SSH with MobaXterm

### 🖥️ Open MobaXterm → Session → SSH

Remote host:
```
klipper.local
```
*(Or the custom hostname you set in Raspberry Pi Imager)*

Username: (The username you created in Pi Imager)
```
pi
```
Password: (The password you created in Pi Imager)
```
raspberry
```
## If you can log in → you are inside the Raspberry.

---

# ⚡ PART 4 — Install and use KACE (ALL in one)

KACE simplifies the ENTIRE process:

* 🔧 Compiles the firmware
* ⚙️ Generates the `printer.cfg`
* 🚀 Leaves Klipper ready to use

---


## ⚡ One-Line Install (recommended for convenience)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> **Security tradeoff:** this streams code from the network directly to Bash. You cannot inspect or verify the exact file before it runs. Use it only when you trust the KACE GitHub source and your network path.

> This will install all dependencies, clone the repository, and set up the global `kace` command automatically.

### Verified installation (recommended when integrity verification matters)

```bash
# Choose a release and copy its published installer SHA-256 from a trusted channel.
INSTALL_REF='vX.Y.Z'
EXPECTED_SHA256='paste-the-trusted-sha256-here'

curl -fsSLo install.sh "https://raw.githubusercontent.com/3D-uy/KACE/${INSTALL_REF}/install.sh"
printf '%s  %s\n' "$EXPECTED_SHA256" install.sh | sha256sum -c -
bash install.sh  # Run only after sha256sum reports "install.sh: OK"
```

If verification fails, do not run the file. Do not fetch the expected checksum from the same mutable branch as the installer. This check verifies the installer script; the installer currently installs KACE from `main`.

## 📦 Final result

After running KACE you will have:

```
~/kace/
├── printer.cfg
├── klipper.bin / klipper.uf2 / klipper.hex
```

---

## 🚀 Next Steps

1. Flash firmware to your board (SD / USB)
2. Upload `printer.cfg` to Klipper
3. Restart services:

```bash
sudo reboot
```

---

### 🎉 READY TO START

You now have your compiled firmware and your `printer.cfg` file generated automatically.

Now it's just a matter of adjusting it to your needs, calibrating your printer and getting the most out of Klipper.

🚀 Enjoy the process and HAPPY PRINTING!

---

## 🙌 Contribute and feedback

KACE evolves with the community:

* 🐛 Report bugs
* 💡 Suggest improvements
* 🤝 Contribute code

👉 Every contribution counts.

---

## 🙏 Acknowledgments

This project relies on the incredible work of the **Klipper** community.

KACE seeks to make that ecosystem more accessible for everyone.

---

<p align="center">

⭐ If you like this project, give it a star
🚀 Built to simplify Klipper

</p>

---
