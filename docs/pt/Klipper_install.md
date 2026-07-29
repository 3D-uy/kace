# 🚀 KLIPPER instalação fácil

![Firmware](https://img.shields.io/badge/Firmware-Klipper-orange)
![Board](https://img.shields.io/badge/Board-SKR%201.4%20%2F%201.4%20Turbo-blue)
![Raspberry](https://img.shields.io/badge/Raspberry-Pi%203B-red)
![Interface](https://img.shields.io/badge/UI-Mainsail-purple)
![Guide](https://img.shields.io/badge/Guia-Instalação%20simples-success)

<p align="center">

🌐 **Idioma**  
🇺🇸 <a href="../en/Klipper_install.md">English</a> | 🇪🇸 <a href="../es/Klipper_install.md">Español</a> | 🇧🇷 Português

</p>

# 🧠 O guia definitivo para instalar o Klipper

Este tutorial foi projetado para ser seguido junto com o vídeo.  
Basta copiar cada bloco de código e colá-lo no terminal.  
Você não precisa digitar comandos manualmente.

---

# 📋 REQUISITOS

- 🧠 Raspberry Pi (como exemplo usaremos uma Raspberry Pi 3B)
- 🧩 Placa exemplo: SKR 1.4 Turbo
- 💾 Cartão SD de boa qualidade para a Raspberry
- 💾 Cartão SD para carregar firmware na SKR
- 🔌 Cabo USB entre Raspberry e SKR
- 💻 PC com Windows
- 🖥️ MobaXterm instalado

## 🔗 Todos os links você encontrará abaixo

---

# 💿 PARTE 1 — Gravar o MainsailOS no cartão SD

Antes de começar, você precisa gravar o sistema operacional no cartão SD da Raspberry Pi.

Usaremos o **Raspberry Pi Imager**, a ferramenta oficial.

📥 Baixar aqui  

  Site oficial https://www.raspberrypi.com/software/

[Guia para instalar o **Raspberry Pi Imager**](pi_imager.md)

O programa irá baixar a imagem e gravá-la automaticamente.

# 📥 Enquanto isso, baixe o seguinte programa

## 🖥️ Baixar MobaXterm

   Site oficial  
   https://mobaxterm.mobatek.net/download.html

---

# ⚡ Quando terminar de instalar o **Raspberry Pi Imager**

1. Remover o cartão SD
2. Inseri-lo na **Raspberry Pi**
3. Ligar a Raspberry

  ## Aguardar aproximadamente **1 a 2 minutos** para que o sistema inicialize completamente.


# 📡 PARTE 2  Abrir o MainsailOS.

### Abrir o navegador e acessar:
```
klipper.local
```
*(Ou o hostname personalizado que você configurou no Raspberry Pi Imager)*
Se abrir o Mainsail → perfeito.

---

# 🔐 PARTE 3 — Conectar via SSH com MobaXterm

### 🖥️ Abrir MobaXterm → Session → SSH

Remote host:
```
klipper.local
```
*(Ou o hostname personalizado que você configurou no Raspberry Pi Imager)*

Username: (O usuário que você criou no Pi Imager)
```
pi
```
Password:
```
raspberry
```
## Se entrar → estamos dentro da Raspberry.

---

# ⚡ PARTE 4 — Instalar e usar KACE (TUDO em um)

O KACE simplifica TODO o processo:

* 🔧 Compila o firmware
* ⚙️ Gera o `printer.cfg`
* 🚀 Deixa o Klipper pronto para usar

---


## ⚡ Instalação em uma linha (recomendada por conveniência)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> **Consideração de segurança:** este comando transmite código da rede diretamente para o Bash. Não é possível inspecionar ou verificar o arquivo exato antes da execução. Use-o somente se você confia na fonte do KACE no GitHub e na sua conexão.

> Isso instalará todas as dependências, clonará o repositório e configurará o comando global `kace` automaticamente.

### Instalação verificada (recomendada quando a verificação de integridade é importante)

```bash
# Escolha uma release e copie seu SHA-256 publicado de um canal confiável.
INSTALL_REF='vX.Y.Z'
EXPECTED_SHA256='cole-aqui-o-sha256-confiável'

curl -fsSLo install.sh "https://raw.githubusercontent.com/3D-uy/KACE/${INSTALL_REF}/install.sh"
printf '%s  %s\n' "$EXPECTED_SHA256" install.sh | sha256sum -c -
bash install.sh  # Execute somente se sha256sum informar "install.sh: OK"
```

Se a verificação falhar, não execute o arquivo. Não baixe a soma esperada da mesma branch mutável que o instalador. Esta verificação cobre o script instalador; atualmente ele instala o KACE a partir de `main`.

## 📦 Resultado final

Após executar o KACE você terá:

```
~/kace/
├── printer.cfg
├── klipper.bin / klipper.uf2 / klipper.hex
```

---

## 🚀 Próximos passos

1. Gravar firmware na sua placa (SD / USB)
2. Enviar `printer.cfg` para o Klipper
3. Reiniciar serviços:

```bash
sudo reboot
```

---

### 🎉 PRONTO PARA COMEÇAR

Você já tem seu firmware compilado e seu arquivo `printer.cfg` gerado automaticamente.

Agora só falta ajustá-lo às suas necessidades, calibrar sua impressora e começar a aproveitar ao máximo o Klipper.

🚀 Aproveite o processo e HAPPY PRINTING!

---

## 🙌 Contribuir e feedback

O KACE evolui com a comunidade:

* 🐛 Reportar bugs
* 💡 Sugerir melhorias
* 🤝 Contribuir com código

👉 Toda contribuição soma.

---

## 🙏 Agradecimentos

Este projeto se apoia no incrível trabalho da comunidade do **Klipper**.

O KACE busca tornar esse ecossistema mais acessível para todos.

---

<p align="center">

⭐ Se gostou deste projeto, deixe uma estrela
🚀 Feito para simplificar o Klipper

</p>

---
