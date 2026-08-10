<p align="center">
  <img src="../assets/kace_banner.png" width="1000" alt="Banner do KACE">
</p>

<h1 align="center">KACE</h1>

<p align="center">
  <strong>Klipper Automated Configuration Ecosystem</strong><br>
  O companheiro interativo para transformar escolhas da impressora em artefatos revisáveis do Klipper.
</p>

<p align="center">
  <a href="https://github.com/3D-uy/KACE/actions/workflows/ci.yml"><img src="https://github.com/3D-uy/KACE/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <img src="https://img.shields.io/badge/status-pre--1.0-yellow" alt="Status do projeto: pré-1.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11 ou mais recente">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-green" alt="Linux e Raspberry Pi">
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="Licença GPL-3.0"></a>
</p>

<p align="center">
  <a href="../../README.md">English</a> · <a href="../es/README.md">Español</a> · <strong>Português</strong>
</p>

> [!WARNING]
> O KACE está em desenvolvimento ativo pré-1.0. A branch `main` pode mudar sem garantias de compatibilidade retroativa até que exista um processo de versões estáveis.

## Índice

- [O que é o KACE?](#o-que-é-o-kace)
- [Início rápido](#início-rápido)
- [Como o ecossistema flui](#como-o-ecossistema-flui)
- [Por que KACE?](#por-que-kace)
- [Recursos](#recursos)
- [Status atual](#status-atual)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Fluxo completo](#fluxo-completo)
- [Arquitetura](#arquitetura)
- [Tecnologias](#tecnologias)
- [Testes e validação](#testes-e-validação)
- [Docker](#docker)
- [CI/CD](#cicd)
- [Compatibilidade e limites](#compatibilidade-e-limites)
- [Roadmap](#roadmap)
- [Contribuição](#contribuição)
- [Licença](#licença)

---

## O que é o KACE?

KACE é a CLI interativa executada no lado Raspberry Pi do ecossistema KACE. Ela guia a pessoa usuária pelas escolhas de hardware da impressora, deriva uma configuração do Klipper, pode compilar o firmware correspondente do MCU e implanta os artefatos gerados por caminhos locais ou remotos compatíveis.

> [!WARNING]
> KACE não substitui o Klipper nem elimina o comissionamento da impressora. A pessoa responsável pela máquina ainda deve verificar fiação, atribuições de pinos, limites de movimento, aquecedores, sensores, homing e o primeiro movimento controlado.

## Início rápido

| Ponto de partida | Caminho recomendado |
| --- | --- |
| Novo host de impressora Raspberry Pi | Use o [KACE Studio](https://github.com/3D-uy/KACE-studio) para gravar a imagem, configurar a primeira inicialização, descobrir a Pi, conectar via SSH e iniciar o fluxo de bootstrap fixado. |
| Host Linux Debian-family existente | Execute o comando de instalação abaixo e depois inicie `kace`. |
| Checkout do código-fonte ou configuração de contribuição | Clone o repositório, instale as dependências bloqueadas e execute `python kace.py`. |

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> [!WARNING]
> Este comando de conveniência transmite conteúdo remoto da branch mutável `main` diretamente para o Bash. Para uma instalação auditável, baixe `install.sh` de um commit ou tag imutável, verifique seu SHA-256 por meio de um valor confiável separado, inspecione-o e então execute-o.

## Como o ecossistema flui

```text
KACE Studio (Windows)
        │ imagem, ajustes de primeira inicialização, descoberta e SSH
        ▼
Host de impressora Raspberry Pi
        │ bootstrap.sh fixado provisiona o host
        ▼
KACE (CLI interativa Linux)
        │ configuração e artefatos de firmware opcionais
        ▼
Klipper + comissionamento da impressora
```

| Etapa | Responsabilidade |
| --- | --- |
| 🪟 [KACE Studio](https://github.com/3D-uy/KACE-studio) | Grava uma imagem Raspberry Pi, injeta arquivos de rede, primeira inicialização e bootstrap do KACE; após a inicialização descobre a Pi, conecta via SSH e inicia o `bootstrap.sh` injetado. |
| 🍓 Bootstrap | Provisiona Klipper, Moonraker, a interface web selecionada, suporte opcional ao Crowsnest e KACE. O Studio fixa o bootstrap por commit Git imutável e SHA-256 no CI. O bootstrap fixa URL do instalador KACE, revisão e SHA-256 como um contrato. |
| 🧩 KACE | Guia as escolhas da impressora, gera configuração e artefatos de firmware específicos e oferece caminhos de implantação compatíveis. |
| 🔧 Klipper e a pessoa operadora | Executam o Klipper e concluem a sequência oficial de verificação elétrica, mecânica, térmica, homing e movimento. |

Marcadores legíveis por máquina de etapas e erros em `scripts/bootstrap.sh` são consumidos pela UI do Studio e devem permanecer sincronizados.

## Por que KACE?

| Caminho manual | Caminho assistido pelo KACE |
| --- | --- |
| Coletar detalhes de placa, movimento, endstops, aquecedores, sensores, sonda, display e software em etapas separadas. | Reunir essas escolhas em um único fluxo guiado de CLI. |
| Montar manualmente os artefatos de configuração e firmware. | Resolver perfis mantidos de placa e MCU e então gerar configuração, macros e artefatos opcionais de firmware. |
| Escolher transferência e recuperação de forma ad hoc. | Usar caminhos compatíveis de mídia local/removível, SSH/SFTP, Moonraker ou implantação USB de firmware protegida, com backup, validação e rollback quando implementados. |
| Validar fisicamente a impressora após cada alteração. | Validar fisicamente a impressora após cada alteração; o KACE torna os artefatos e o fluxo mais repetíveis, mas não substitui o comissionamento. |

## Recursos

| Área | O que o KACE fornece |
| --- | --- |
| 🧭 Configuração guiada | CLI interativa em inglês, espanhol e português. |
| 🧠 Perfis | Resolução de perfis de placa e MCU a partir de dados YAML mantidos. |
| 🖨️ Movimento e sondas | Geração de configuração para fluxos Cartesian e CoreXY implementados; sem sonda, BLTouch, CR Touch, indutiva e sonda personalizada. |
| 🖥️ Displays | Verificações de compatibilidade e configuração de display gerada quando suportada. |
| 📄 Artefatos gerados | Geração de configuração e macros do Klipper a partir de templates do projeto, armazenadas em `~/kace/` no host da impressora. |
| ⚙️ Firmware | Derivação e compilação opcionais do firmware Klipper para MCU; estratégias exatas por placa para AVRDUDE, cartão SD e preparação UF2 validadas, com placas desconhecidas limitadas a somente preparar. |
| 📦 Implantação | Caminhos de implantação de configuração por mídia local/removível, SSH/SFTP e Moonraker; suporte a backup, validação e rollback em torno da implantação. |

Espera-se que escolhas sem suporte ou contraditórias falhem de forma segura, em vez de produzir uma configuração sabidamente inválida.

## Status atual

KACE está em desenvolvimento ativo pré-1.0. Seus geradores de configuração, testes snapshot, verificações de cobertura de placas, matrizes de Klipper fixado e compilações de firmware em contêiner executam no CI. Essas verificações automatizadas não substituem a validação física em cada controladora, sonda, display ou impressora suportada.

A versão autoritativa do projeto é armazenada em `VERSION`.

> [!NOTE]
> Testes automatizados não testam fisicamente cada controladora, impressora, sonda, display, arranjo de fiação ou sequência de comissionamento.

## Requisitos

| Público | Requisitos |
| --- | --- |
| Pessoas usuárias | Um host de impressora Linux da família Debian, normalmente um Raspberry Pi; Python 3.11 ou mais recente; Git e pacotes padrão do sistema instalados por `install.sh`; acesso à rede para instalação e operações que buscam dados upstream do Klipper; acesso apropriado ao destino de implantação escolhido. |
| Pessoas contribuidoras | Python 3.11, Git e Docker para a matriz de validação com Klipper fixado e compilações de firmware em contêiner. |

## Instalação

### Provisionar um novo host de impressora com KACE Studio

Para um novo Raspberry Pi, use o [KACE Studio](https://github.com/3D-uy/KACE-studio). O Studio cuida da gravação da imagem, configuração da primeira inicialização, descoberta, acesso SSH e fluxo bootstrap fixado do KACE.

### Instalar diretamente em um host Linux existente

O comando de conveniência instala a partir da branch mutável `main`:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

Isso transmite conteúdo de rede diretamente para o Bash. Para uma instalação auditável, baixe `install.sh` de um commit ou tag imutável, verifique seu SHA-256 por meio de um valor confiável separado, inspecione-o e então execute-o. `install.sh` respeita `KACE_SOURCE_REF`, de modo que um integrador pode instalar o conteúdo do repositório da mesma revisão imutável que o instalador.

### Executar a partir de um checkout do código-fonte

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

Execute `python kace.py --help` para ver as opções de CLI disponíveis.

<details>
<summary>Lembrete de segurança da instalação</summary>

`main` é mutável. Fixar o instalador e a revisão do código-fonte, verificar um SHA-256 confiável separado e inspecionar o script é o caminho auditável quando esse nível de controle é necessário.

</details>

## Fluxo completo

1. Provisione ou prepare o host Linux da impressora.
2. Inicie o KACE com `kace` após a instalação, ou `python kace.py` a partir de um checkout.
3. Selecione o idioma e descreva as escolhas de impressora, controladora, sistema de movimento, endstops, cama, aquecedores, sensores, sonda, display e software.
4. Deixe o KACE resolver o perfil da placa e gerar a configuração do Klipper em `~/kace/`.
5. Compile o firmware do MCU quando exigido pelo fluxo da placa selecionada.
6. Revise os artefatos gerados e implante-os usando o destino local ou remoto escolhido.
7. Grave o MCU somente conforme o procedimento documentado pelo fabricante da controladora.
8. Inicie o Klipper e conclua sua sequência oficial de verificação antes de energizar aquecedores ou comandar movimento irrestrito.

Para um caminho integrado de firmware, o KACE exibe o progresso transacional da instalação diretamente em um terminal interativo e mantém `Ctrl+C` disponível para um cancelamento seguro. Saída redirecionada, pipes, CI e terminais sem recursos dinâmicos recebem linhas simples de progresso ASCII. Os mesmos eventos canônicos de fluxo são emitidos como linhas JSON `KACE_WORKFLOW_EVENT` para o KACE Studio; nenhuma visualização de terminal controla ou reconstrói a máquina de estados da instalação.

A identidade do MCU após a gravação só é aceita automaticamente quando uma avaliação pontuada inclui a porta USB física capturada ou a topologia `by-path` e o VID/PID de aplicação esperado pelo perfil, sem evidência conflitante. Um serial estável aumenta a confiança, mas nunca substitui uma porta diferente ou um VID/PID incorreto. Candidatos ambíguos exigem confirmação física explícita e a decisão fica registrada no evento do workflow.

> [!TIP]
> Revise os artefatos gerados antes da implantação e trate a primeira energização, homing, aquecedores, sensores e verificações de movimento como etapas de segurança controladas pela pessoa operadora.

## Arquitetura

| Área | Responsabilidade |
| --- | --- |
| `kace.py` | Ponto de entrada da CLI, análise de argumentos e orquestração de alto nível. |
| `core/wizard/` | Fluxo interativo e escolhas normalizadas da pessoa usuária. |
| `core/scraper.py`, `core/hardware_detector.py` | Obtenção de configuração upstream e descoberta de hardware. |
| `core/generator.py`, `core/templates.py` | Geração de configuração e macros do Klipper. |
| `firmware/` | Derivação/compilação de firmware mais artefatos tipados e estratégias exatas de implantação por placa. |
| `data/firmware_deployments.yaml` | IDs exatos de placa, nomes nativos/finais, offsets de bootloader, instruções de entrada, identidade USB esperada, método físico e contrato de verificação posterior. |
| `core/deployer.py`, `core/moonraker.py`, `core/moonraker_deployer.py` | Caminhos de implantação, instalação transacional, transferência remota, backup e rollback. |
| `core/terminal_progress.py` | Visualizações TTY nativas e orientadas a linhas dos eventos canônicos de instalação. |
| `data/`, `templates/`, `config/` | Contratos de placa, traduções, templates de conteúdo gerado e dados de configuração. |
| `scripts/bootstrap.sh` | Contrato de integração usado pelo KACE Studio para provisionar um host de impressora. |
| `tests/` | Validação unitária, regressão, snapshot, esquema, sweep e matriz de Klipper fixado. |

Os artefatos gerados da impressora permanecem separados da árvore de código-fonte em `~/kace/`.

## Tecnologias

- Python, Questionary, PyYAML e Jinja2.
- Paramiko para o caminho opcional de implantação SSH/SFTP.
- Bash para instalação e provisionamento do host.
- Docker para análise reproduzível do Klipper e validação da compilação de MCU.
- GitHub Actions para CI.

## Testes e validação

Instale as dependências de execução bloqueadas e então execute a validação mais restrita necessária para a alteração:

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
```

A matriz completa por pares destina-se ao uso manual ou pré-lançamento:

```bash
python tests/matrix/run_matrix.py --profile full
```

A matriz gera configurações pelo fluxo real do KACE, valida casos aceitos com um commit fixo do Klipper dentro do Docker, distingue rejeições seguras esperadas de falhas e grava relatórios Markdown e JSON. O sweep mais amplo de configuração upstream está disponível com:

```bash
python tests/run_tests.py --full-klipper-sweep --verbose
```

Os modos de atualização de snapshot são operações de manutenção e não devem ser usados apenas para fazer um teste que falhou passar. Consulte [Testes](TESTING.md) para a organização e expectativas de testes.

## Docker

O KACE é instalado diretamente no host da impressora; não é distribuído como contêiner de execução. A imagem Docker do repositório existe para desenvolvimento e validação reproduzíveis:

```bash
docker build -f docker/ci/Dockerfile -t kace-dev .
docker run --rm -it -v "$PWD:/workspace" kace-dev
```

O executor da matriz também usa Docker para executar o carregador real de configuração da revisão fixada do Klipper. Nenhum dispositivo físico é acessado por esses trabalhos de validação.

## CI/CD

O GitHub Actions verifica atualmente:

- Sintaxe Python.
- Testes unitários e de regressão snapshot.
- Esquema e regras de precedência de `boards.yaml`.
- Uma matriz reduzida de KACE para Klipper em pull requests e pushes.
- O sweep completo de configuração upstream em pushes para `main`.
- Uma matriz completa por pares quando acionada manualmente.
- Compilações de firmware em contêiner para alvos representativos LPC1769, STM32, RP2040 e AVR.

O CI valida código-fonte e artefatos gerados. Não publica uma versão, não exercita impressoras reais nem grava controladoras físicas.

## Compatibilidade e limites

- Alvo de execução: hosts Linux da família Debian com Python 3.11 ou mais recente.
- Cobertura de geração automatizada: fluxos Cartesian e CoreXY implementados e todos os contratos de placa exigidos pela matriz.
- Cobertura automatizada de sondas: nenhuma, BLTouch, CR Touch, indutiva e personalizada; combinações dockable não suportadas são classificadas como rejeições seguras.
- O KACE Studio realiza o fluxo de provisionamento do lado Windows; o KACE é executado no host Linux da impressora.
- Klipper upstream, definições de placa e interfaces web de terceiros podem mudar de forma independente. A matriz fixada detecta incompatibilidades de parser, mas não pode provar segurança elétrica ou mecânica.

## Roadmap

Antes da versão 1.0, o projeto deve priorizar versões reproduzíveis, sincronização de contratos entre ambos os repositórios, qualificação de hardware documentada, evidência de instalação de ponta a ponta e encerramento de riscos conhecidos de segurança e compatibilidade. Após a versão 1.0, o trabalho deve se concentrar em cobertura de placas medida, estabilidade de migração e diagnósticos voltados a contribuidores. Automação mais ampla ou famílias adicionais de hardware pertencem a um roadmap posterior somente depois de terem testes e mantenedores.

Consulte [CHANGELOG.md](../../CHANGELOG.md) para alterações registradas. Itens do roadmap são intenções, não recursos já entregues.

## Contribuição

Leia o [guia de contribuição](CONTRIBUTING.md), a [política de segurança](../../SECURITY.md) e o [código de conduta](../../CODE_OF_CONDUCT.md) antes de abrir uma alteração. Mantenha as alterações restritas, adicione a menor cobertura de regressão relevante e não atualize snapshots sem revisar a diferença gerada.

Issues e pull requests são gerenciados no [repositório KACE](https://github.com/3D-uy/KACE).

## Licença

KACE é distribuído sob a [GNU General Public License v3.0](../../LICENSE).
