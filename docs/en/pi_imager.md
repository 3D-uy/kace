# 🍓 Raspberry Pi Imager Setup (Mainsail OS)

<p align="center">
  <img src="../assets/pi_imager/pi_imager_logo.png" width="300">
</p>

<p align="center">

🌐 **Language**  
🇺🇸 English | 🇪🇸 <a href="../es/pi_imager.md">Español</a> | 🇧🇷 <a href="../pt/pi_imager.md">Português</a>

</p>

---

## 📦 Overview

This guide describes the manual Raspberry Pi Imager path for installing **Mainsail OS** before running KACE on the printer host.

For the integrated Windows workflow—imaging, first-boot configuration, discovery, SSH, and the pinned KACE bootstrap—use [KACE Studio](https://github.com/3D-uy/KACE-studio).

---

## ⚠️ Before you start

Make sure you have:

- A Raspberry Pi  
- A microSD card (recommended: 16GB or more)  
- A stable internet connection  

💡 *Imaging prepares the operating system and network access. KACE still has to generate and deploy the printer-specific Klipper configuration, and the printer must be commissioned safely.*

---

### 🔹 Step 1 — Open Raspberry Pi Imager
Launch the Raspberry Pi Imager application.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_1.png" width="500">
</p>

---

### 🔹 Step 2 — Select your device
Choose your Raspberry Pi model.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_2.png" width="500">
</p>

---

### 🔹 Step 3 — Choose OS
Select:

**Other specific-purpose OS**

<p align="center">
  <img src="../assets/pi_imager/pi_imager_3.png" width="500">
</p>

---

### 🔹 Step 4 — 3D Printing category
Select:

**3D Printing**

<p align="center">
  <img src="../assets/pi_imager/pi_imager_4.png" width="500">
</p>

---

### 🔹 Step 5 — Select Mainsail OS
Choose **Mainsail OS** from the list.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_5.png" width="500">
</p>

---

### 🔹 Step 6 — Choose version
Select:

**Mainsail OS 2.x.x (Raspberry Pi)**

<p align="center">
  <img src="../assets/pi_imager/pi_imager_6.png" width="500">
</p>

---

### 🔹 Step 7 — Select storage
Choose your SD card.

⚠️ *Make sure you select the correct device — all data will be erased.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_7.png" width="500">
</p>

---

### 🔹 Step 8 — Hostname
Set your device name.

Example:
```bash
klipper
````

💡 *You will use this later to connect via network.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_8.png" width="500">
</p>

---

### 🔹 Step 9 — Localization

Configure:

* Timezone
* Region
* Keyboard layout

<p align="center">
  <img src="../assets/pi_imager/pi_imager_9.png" width="500">
</p>

---

### 🔹 Step 10 — User credentials

Set:

* Username
* Password

💡 *Remember these credentials — you will need them for SSH.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_010.png" width="500">
</p>

---

### 🔹 Step 11 — WiFi setup

Enter:

* Network name (SSID)
* Password

💡 *Make sure it’s your correct network.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_011.png" width="500">
</p>

---

### 🔹 Step 12 — Enable SSH

Enable SSH authentication.

👉 This step is **critical** to access your Raspberry Pi remotely.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_012.png" width="500">
</p>

---

### 🔹 Step 13 — Write image

Start the flashing process.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_013.png" width="500">
</p>

---

### ⚠️ Step 14 — Warning

Confirm the warning to proceed.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_014.png" width="500">
</p>

---

### 🔹 Step 15 — Download & flashing

The system will:

* Download the OS
* Write it to the SD card

⏳ *This may take several minutes.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_015.png" width="500">
</p>

---

### ✅ Step 16 — Completed

Flashing finished successfully.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_016.png" width="500">
</p>

---

## 🚀 Next Step

Now you can:

1. Insert the SD card into your Raspberry Pi
2. Power it on
3. Connect via SSH using tools like **MobaXterm**
   or directly from your browser

Use the hostname you configured:

```bash
klipper.local
```

---

💡 **Tip:**
If `klipper.local` doesn’t work, find the IP address from your router.
