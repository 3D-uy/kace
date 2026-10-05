![KACE — Klipper Automated Configuration Ecosystem](../assets/kace_banner.png)

# KACE

### Klipper Automated Configuration Ecosystem

**Configuração guiada de impressoras, preparação de firmware e implantação para Klipper.**

[![KACE version 0.9.4-rc.3](https://img.shields.io/badge/KACE-0.9.4--rc.3-e88c30?style=flat-square)](../../VERSION)
[![Status: pre-release](https://img.shields.io/badge/status-pre--release-d29b32?style=flat-square)](#estado-do-projeto)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](../en/INSTALLATION.md)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-2d718f?style=flat-square)](../../LICENSE)
[![GitHub Actions: KACE CI](https://img.shields.io/github/actions/workflow/status/3D-uy/kace/ci.yml?branch=main&style=flat-square&label=tests&logo=githubactions&logoColor=white)](https://github.com/3D-uy/kace/actions/workflows/ci.yml)<br>
[![Host: Linux](https://img.shields.io/badge/host-Linux-454545?style=flat-square&logo=linux&logoColor=white)](../en/INSTALLATION.md)
[![Host: Raspberry Pi](https://img.shields.io/badge/host-Raspberry_Pi-A22846?style=flat-square&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/software/)
[![For Klipper](https://img.shields.io/badge/for-Klipper-e88c30?style=flat-square)](https://www.klipper3d.org/)
[![API: Moonraker](https://img.shields.io/badge/API-Moonraker-5965a8?style=flat-square)](https://moonraker.readthedocs.io/en/latest/)
[![GitHub stars](https://img.shields.io/github/stars/3D-uy/kace?style=flat-square&logo=github&label=stars&color=e3b341)](https://github.com/3D-uy/kace)

🌐 [English](../../README.md) · [Español](../es/README.md) · [Português](README.md)

O KACE orienta as escolhas de hardware da impressora para gerar e revisar sua configuração do Klipper.
Seu assistente de terminal prepara firmware MCU quando suportado e acompanha a aplicação e a verificação da instalação.

[Início rápido](#início-rápido) · [Hardware](#hardware-e-plataformas) · [KACE Studio](#kace-studio) · [Documentação](#documentação)

<a id="o-que-o-kace-faz"></a>

## ✨ O que o KACE faz

| Capacidade | O que você obtém |
| --- | --- |
| 🔌 **Escolher hardware** | Seleção de placa/MCU, motores, sondas, termistores e ventoinhas. |
| 📄 **Gerar configuração** | `printer.cfg` e macros aplicáveis em `~/kace/`, a partir de perfis revisados e suas respostas. |
| ⚙️ **Preparar firmware** | Compilação para as MCUs declaradas, com o método de instalação disponível e as etapas manuais necessárias. |
| 🔎 **Revisar alterações** | Diferenças antes da aplicação, preservando valores de calibração suportados e seções do usuário. |
| ✅ **Aplicar e verificar** | Implantação no host e verificações de ativação e identidade de firmware exigidas. |

<a id="conheça-o-assistente"></a>
<a id="configuração-guiada"></a>

## 🧙 Configuração guiada

O assistente de terminal oferece **português, inglês e espanhol**, com modos **Iniciante** e **Avançado**.

> **Escolher hardware** → **Configuração guiada** → **Gerar configuração Klipper**<br>
> → **Compilar firmware MCU** → **Revisar** → **Aplicar** → **Verificar**

As etapas de firmware dependem do alvo suportado e do fluxo escolhido.

<!-- Inserir aqui uma captura real do assistente/revisão: docs/assets/kace-wizard.png.
     Incluir texto alternativo e a versão do KACE capturada. Não usar um mockup como captura do produto. -->

Drivers TMC removíveis usam a fiação revisada do conector mesmo quando o exemplo do perfil cita outro chip. O mapeamento entre modelos exige correntes explícitas; veja [escopo e perfis aceitos (EN)](../TMC_SOCKET_MAPPING.md).

<a id="início-rápido"></a>

## 🚀 Início rápido

Em um **Raspberry Pi ou host Linux existente**, abra um terminal ou conecte por SSH.
Você precisa de **Python 3.11+**, Git, Bash, suporte a venv do Python e acesso à internet.
O instalador pode solicitar sudo para dependências do sistema e o comando `kace`.

```bash
git clone https://github.com/3D-uy/KACE.git kace-source &&
cd kace-source &&
KACE_SOURCE_REF="$(git rev-parse HEAD)" bash install.sh
```

Isso instala em `~/kace/` a revisão que você acabou de clonar e abre o KACE.
Execute `kace` para abrir novamente. Esta opção acompanha a branch padrão atual do repositório; para o candidato fixo, use a opção verificada abaixo.

Após revisar as alterações, confirme a aplicação e ativação e siga as [verificações de hardware (EN)](../HARDWARE_TESTING.md) antes de imprimir.

Aplicar e verificar a configuração exige um host com Klipper/Moonraker funcionando.
Para um Pi novo, comece pelo [KACE Studio](#kace-studio) ou pela [preparação manual do host (EN)](../en/INSTALLATION.md).

<a id="instalação-verificada-pinned"></a>

### 🔒 Instalação verificada / pinned

Para usar um candidato fixo com verificação do checksum do instalador, utilize o comando abaixo.
Ele mantém a referência fixada existente e pode diferir do código atual.

<details>
<summary>Mostrar o comando de instalação fixada</summary>

Requer `curl` e `sha256sum`. Revise o script antes de executá-lo.

```bash
KACE_COMMIT='561f9b9463b0d443e386f8b1ef468980538093eb'
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

O [KACE Studio](https://github.com/3D-uy/KACE-studio) é o aplicativo desktop complementar para preparar um Raspberry Pi pelo **Windows 10/11**.

- Grave uma imagem de Pi em SD/USB e configure hostname, conta, rede e SSH para o primeiro boot.
- Descubra o Pi e conecte por um espaço de trabalho SSH.
- Navegue e baixe arquivos por SFTP e continue a configuração com o KACE no Pi.

**O Studio prepara o host; o KACE configura a impressora.** O Studio requer Microsoft Edge WebView2 Runtime e também está em fase anterior à 1.0.
Consulte suas [instruções iniciais](https://github.com/3D-uy/KACE-studio/blob/main/docs/pt/README.md) para instalação e imagens/plataformas disponíveis.

<a id="hardware-e-plataformas"></a>

## 🔌 Hardware e plataformas

| Área | Escopo atual |
| --- | --- |
| Host do KACE | Raspberry Pi / Linux com Python 3.11+; a ativação usa Klipper e Moonraker. |
| Configuração da impressora | Cartesiana e CoreXY, extrusor principal e mesa aquecida, com os fluxos suportados de motores, sondas e ventoinhas. |
| Preparação pelo desktop | KACE Studio no Windows 10/11; o Studio valida as opções de modelo de Pi e SO. |

Os [contratos de placa atuais](../../data/board_contracts/v1/) declaram fluxos de firmware em execução para estes alvos exatos:

| Placa | Variante MCU | Conexão ao host |
| --- | --- | --- |
| BTT SKR Mini E3 v3.0 | STM32G0B1 | USB nativo |
| BTT SKR v1.4 / v1.4 Turbo | LPC1768 / LPC1769, respectivamente | USB nativo |
| BTT SKR Pico v1.0 | RP2040 | USB nativo |
| Creality v4.2.7 | STM32F103 | Ponte serial USB, USART1 da MCU |
| MKS Robin Nano V3 | STM32F407 | USB nativo |

São fluxos implementados em software, **não uma lista de impressoras certificadas fisicamente**.
Revisão da placa, MCU, fiação, bootloader e método de instalação devem corresponder ao alvo escolhido.
Outras entradas podem ser provisórias, somente de configuração ou somente de preparação; encontrar um perfil Klipper não comprova suporte completo.
Consulte o [escopo (EN)](../en/SUPPORT_SCOPE.md) e os [perfis de instalação de firmware](../../data/firmware_deployments.yaml).

<a id="estado-do-projeto"></a>

## 🧪 Estado do projeto

O KACE está em fase **anterior à 1.0**. Consulte [VERSION](../../VERSION) para a versão do código, [CHANGELOG](../../CHANGELOG.md) para alterações e [ROADMAP](ROADMAP.md) para o trabalho pendente.

- A validação física ainda está pendente; sensores, endstops, movimento e aquecimento precisam ser verificados na sua impressora.
- Múltiplos extrusores, IDEX/toolchangers e migração geral de perfis arbitrários do Klipper estão fora do escopo atual.
- A geração guiada de telas ativas ainda não dispõe de um par placa/tela qualificado; veja o [suporte a telas](DISPLAYS.md).
- Algumas alterações remotas exigem aplicação manual. O KACE cobre a instalação inicial e retomadas pendentes; não monitora edições posteriores.

<a id="documentação"></a>

## 📚 Documentação

| Para… | Leia |
| --- | --- |
| Preparar o host, instalar e executar a partir do código | [Guia de instalação (EN)](../en/INSTALLATION.md) |
| Revisar configuração, implantar, coordenar edições e recuperar | [Guia de implantação (EN)](../en/DEPLOYMENT.md) |
| Consultar limites de hardware e recursos | [Escopo (EN)](../en/SUPPORT_SCOPE.md) · [Telas](DISPLAYS.md) |
| Verificar a impressora antes de usar | [Testes de hardware (EN)](../HARDWARE_TESTING.md) |
| Arquitetura, contratos, testes e ambientes de compilação | [Guia de desenvolvimento (EN)](../DEVELOPMENT.md) |
| Versões fixadas, checksums e validação de releases | [Guia de releases (EN)](../RELEASE.md) |
| Trabalho planejado e alterações recentes | [Roadmap](ROADMAP.md) · [Changelog](../../CHANGELOG.md) |

<a id="desenvolvimento-e-contribuições"></a>

## 🛠️ Desenvolvimento e contribuições

Contribuições com relatos de bugs, melhorias de documentação e suporte de hardware revisado são bem-vindas.
Comece pelo [guia de desenvolvimento (EN)](../DEVELOPMENT.md) para conhecer o código, preparar o ambiente e executar os testes relevantes.
Ao relatar um bug, inclua revisão do KACE, ambiente do host, placa/MCU exatas e passos de reprodução, sem credenciais.

Siga o [código de conduta (EN)](../../CODE_OF_CONDUCT.md). Relate vulnerabilidades conforme a [política de segurança (EN)](../../SECURITY.md).

<a id="comunidade-e-agradecimentos"></a>

## ❤️ Comunidade e agradecimentos

**Um agradecimento especial ao projeto Klipper e à sua comunidade** pelo firmware, exemplos de configuração, documentação e conhecimento compartilhado que tornam o KACE possível.

| Projeto | Sua relação com o KACE |
| --- | --- |
| [<img src="https://www.klipper3d.org/img/klipper.svg" width="24" height="24" alt="">&nbsp;Klipper](https://www.klipper3d.org/) | Firmware e sistema de configuração para o qual o KACE trabalha; perfis revisados e código upstream sustentam a geração e compilação MCU. |
| [<img src="https://moonraker.readthedocs.io/en/latest/assets/images/favicon.png" width="24" height="24" alt="">&nbsp;Moonraker](https://moonraker.readthedocs.io/en/latest/) | API do host usada para acessar configurações, ativar alterações e verificar o estado da impressora/firmware. |
| [<img src="https://docs.mainsail.xyz/assets/logo.svg" width="24" height="24" alt="">&nbsp;Mainsail](https://docs.mainsail.xyz/) e<br>[<img src="https://docs.mainsail.xyz/assets/logo.svg" width="24" height="24" alt="">&nbsp;MainsailOS](https://docs.mainsail.xyz/mainsailos/) | Interface oferecida pelo bootstrap e base de imagem pré-configurada utilizada pelo Studio. |
| [<img src="https://raw.githubusercontent.com/fluidd-core/fluidd/7a75e4857282a24d733540ebf07cf6b1bc7717e9/public/img/icons/favicon-32x32.png" width="24" height="24" alt="">&nbsp;Fluidd](https://docs.fluidd.xyz/) | Interface alternativa instalada pelo bootstrap quando selecionada, incluindo sua configuração cliente. |
| [<img src="https://downloads.raspberrypi.com/raspios_armhf/Raspberry_Pi_OS_(32-bit).png" width="24" height="24" alt="">&nbsp;Raspberry&nbsp;Pi](https://www.raspberrypi.com/software/) | Ecossistema do host, opções de imagem Raspberry Pi OS e Imager para preparação manual. |
| [<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mainsail-crew/crowsnest/436042452f564f3d737e3b980a213f849a8a0562/.github/crowsnest-logo-darkmode.png"><img src="https://raw.githubusercontent.com/mainsail-crew/crowsnest/436042452f564f3d737e3b980a213f849a8a0562/.github/crowsnest-logo-lightmode.png" width="24" height="24" alt=""></picture>&nbsp;Crowsnest](https://docs.mainsail.xyz/crowsnest/) | Streaming opcional de câmera instalado pelo bootstrap. |

Relate bugs e sugira melhorias pelas [issues do KACE](https://github.com/3D-uy/kace/issues).

**O KACE é um projeto independente e não é oficialmente afiliado nem endossado pelo Klipper ou pelos demais projetos mencionados aqui.**

<a id="licença"></a>

## 📜 Licença

O KACE é open source sob a [GNU GPL v3](../../LICENSE).

Correções no código-fonte: redirecionamentos do Moonraker são rejeitados. Consulte os [contratos de desenvolvimento](../DEVELOPMENT.md) para operações remotas e limites de validação. O candidato para download não muda até preparar uma nova release.
