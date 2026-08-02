# 🍓 Configuração do Raspberry Pi Imager (Mainsail OS)

<p align="center">
  <img src="../assets/pi_imager/pi_imager_logo.png" width="300">
</p>

<p align="center">

🌐 **Idioma**  
🇺🇸 <a href="../pi_imager.md">English</a> | 🇪🇸 <a href="../es/pi_imager.md">Español</a> | 🇧🇷 Português

</p>

---

## 📦 Visão geral

Este guia descreve o fluxo manual com o Raspberry Pi Imager para instalar o **Mainsail OS** antes de executar o KACE no host da impressora.

Para o fluxo integrado no Windows —imagem, primeira inicialização, descoberta, SSH e bootstrap fixado do KACE— use o [KACE Studio](https://github.com/3D-uy/KACE-studio).

---

## ⚠️ Antes de começar

Certifique-se de ter:

- Um Raspberry Pi  
- Um cartão microSD (recomendado: 16GB ou mais)  
- Conexão de internet estável  

💡 *A gravação prepara o sistema operacional e o acesso à rede. O KACE ainda precisa gerar e implantar a configuração específica do Klipper, e a impressora deve ser comissionada com segurança.*

---

### 🔹 Passo 1 — Abrir o Raspberry Pi Imager
Abra o aplicativo Raspberry Pi Imager.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_1.png" width="500">
</p>

---

### 🔹 Passo 2 — Selecionar dispositivo
Escolha o modelo do seu Raspberry Pi.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_2.png" width="500">
</p>

---

### 🔹 Passo 3 — Escolher sistema operacional
Selecione:

**Other specific-purpose OS**

<p align="center">
  <img src="../assets/pi_imager/pi_imager_3.png" width="500">
</p>

---

### 🔹 Passo 4 — Categoria 3D Printing
Selecione:

**3D Printing**

<p align="center">
  <img src="../assets/pi_imager/pi_imager_4.png" width="500">
</p>

---

### 🔹 Passo 5 — Selecionar Mainsail OS
Escolha **Mainsail OS** na lista.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_5.png" width="500">
</p>

---

### 🔹 Passo 6 — Escolher versão
Selecione:

**Mainsail OS 2.x.x (Raspberry Pi)**

<p align="center">
  <img src="../assets/pi_imager/pi_imager_6.png" width="500">
</p>

---

### 🔹 Passo 7 — Selecionar armazenamento
Escolha o cartão SD.

⚠️ *Certifique-se de selecionar o dispositivo correto — todos os dados serão apagados.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_7.png" width="500">
</p>

---

### 🔹 Passo 8 — Nome do dispositivo (Hostname)
Defina o nome do dispositivo.

Exemplo:
```bash
klipper
````

💡 *Você usará isso depois para se conectar via rede.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_8.png" width="500">
</p>

---

### 🔹 Passo 9 — Configuração regional

Configure:

* Fuso horário
* Região
* Layout do teclado

<p align="center">
  <img src="../assets/pi_imager/pi_imager_9.png" width="500">
</p>

---

### 🔹 Passo 10 — Credenciais do usuário

Defina:

* Nome de usuário
* Senha

💡 *Guarde essas informações — você precisará para o SSH.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_010.png" width="500">
</p>

---

### 🔹 Passo 11 — Configuração WiFi

Informe:

* Nome da rede (SSID)
* Senha

💡 *Certifique-se de que é a rede correta.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_011.png" width="500">
</p>

---

### 🔹 Passo 12 — Ativar SSH

Ative a autenticação SSH.

👉 Este passo é **crítico** para acessar o Raspberry Pi remotamente.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_012.png" width="500">
</p>

---

### 🔹 Passo 13 — Gravar imagem

Inicie o processo de gravação.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_013.png" width="500">
</p>

---

### ⚠️ Passo 14 — Aviso

Confirme o aviso para continuar.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_014.png" width="500">
</p>

---

### 🔹 Passo 15 — Download e gravação

O sistema irá:

* Baixar o sistema operacional
* Gravá-lo no cartão SD

⏳ *Este processo pode levar alguns minutos.*

<p align="center">
  <img src="../assets/pi_imager/pi_imager_015.png" width="500">
</p>

---

### ✅ Passo 16 — Concluído

A gravação foi finalizada com sucesso.

<p align="center">
  <img src="../assets/pi_imager/pi_imager_016.png" width="500">
</p>

---

## 🚀 Próximo passo

Agora você pode:

1. Inserir o cartão SD no Raspberry Pi
2. Ligá-lo
3. Conectar via SSH usando ferramentas como **MobaXterm**
   ou pelo navegador

Use o hostname que você configurou:

```bash id="i6yq2z"
klipper.local
```

---

💡 **Dica:**
Se `klipper.local` não funcionar, verifique o IP no seu roteador.


