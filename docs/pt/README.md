<p align="center">
  <img src="../assets/kace_banner.png" width="1000">
</p>

<h1 align="center">🚀 KACE — Klipper Automated Configuration Ecosystem</h1>

<p align="center">
  <a href="https://github.com/3D-uy/kace/actions/workflows/ci.yml">
    <img src="https://github.com/3D-uy/kace/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI">
  </a>
  <img src="https://img.shields.io/badge/vers%C3%A3o-v0.9.0-blue?style=flat-square" alt="Versão">
  <img src="https://img.shields.io/badge/configs%20validadas-192-brightgreen?style=flat-square" alt="Configs Validadas">
  <img src="https://img.shields.io/badge/plataforma-Linux%20%7C%20Raspberry%20Pi-green?style=flat-square" alt="Plataforma">
  <img src="https://img.shields.io/github/license/3D-uy/KACE?style=flat-square" alt="Licença">
</p>

<p align="center">
🌐 <strong>Idioma</strong><br>
🇺🇸 <a href="../../README.md">English</a> | 🇪🇸 <a href="../es/README.md">Español</a> | 🇧🇷 Português
</p>

---

## ⚡ Instale o Klipper sem dor de cabeça

O KACE automatiza todo o processo de configuração do **Klipper**, desde a detecção de hardware até a compilação de firmware e geração de configuração pronta para uso.

👉 Menos erros  
👉 Menos tempo  
👉 Mais impressão

---

## 🧠 O que é o KACE?

Um **motor inteligente de configuração e firmware** que:

- 🔍 Detecta automaticamente seu hardware (MCU)
- 📦 Obtém as configurações oficiais do Klipper direto do GitHub
- ⚙️ Gera um `printer.cfg` limpo e pronto para uso
- 🔥 Compila o firmware (`klipper.bin` / `.uf2` / `.hex`)
- 🧭 Interage com você apenas quando estritamente necessário
- 🌐 Funciona em Português, Inglês e Espanhol

---

## ⚡ Instalação em uma linha

```bash
bash <(curl -s https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> Instala todas as dependências, clona o repositório (shallow + sparse) e configura o comando global `kace` automaticamente.

---

## 📋 Requisitos

✔ Raspberry Pi com Mainsail OS / FluiddPI (Klipper + Moonraker pré-instalados)  
✔ Acesso SSH à sua Pi

❌ Você **não precisa mais**:

- Compilar firmware manualmente
- Criar arquivos `printer.cfg` à mão

---

## 🎬 Documentação

| Guia | Link |
|------|------|
| Guia de Testes | [`docs/en/TESTING.md`](../en/TESTING.md) |
| Contribuição | [`docs/en/CONTRIBUTING.md`](../en/CONTRIBUTING.md) |
| Release Engineering | [`docs/RELEASE.md`](../RELEASE.md) |
| Compatibilidade de Displays 🖥️ | [`docs/pt/DISPLAYS.md`](DISPLAYS.md) |
| Configuração Pi Imager 🇧🇷 | [`docs/pt/pi_imager.md`](pi_imager.md) |
| Instalação Klipper 🇧🇷 | [`docs/pt/Klipper_install.md`](Klipper_install.md) |
| **Resultados do Sweep Completo 📊** | [`SWEEP_RESULTS.md`](../../SWEEP_RESULTS.md) |
| English 🇺🇸 | [`README.md`](../../README.md) |
| Español 🇪🇸 | [`docs/es/README.md`](../es/README.md) |

---

## 🟢 Status de Validação

O KACE foi validado contra a **biblioteca completa de configurações oficiais do Klipper** usando seu framework de regressão automatizado.

**Último sweep completo — 192 configs testadas contra [Klipper master](https://github.com/Klipper3d/klipper/tree/master/config):**

| Resultado | Quantidade | Significado |
|-----------|------------|-------------|
| ✅ **PASS** | **172** | Parse + geração de config concluídos com sucesso |
| 🔵 **UNSUPPORTED** | **20** | Config usa seções fora do escopo atual do KACE (neopixel, adxl345) |
| 🟠 **SAFE\_ABORT** | **0** | — |
| 🔴 **FAILURE** | **0** | **Zero crashes** |

- **Zero exceções Python** em todas as 192 configs oficiais
- **Zero falhas de template** — todas as configs parséaveis geram corretamente
- **Zero regressões do parser** — output determinístico em cada execução
- **10 avisos de geração** — todas impressoras delta onde o próprio Klipper inclui pinos `TODO` por design

As configs não suportadas contêm funcionalidades fora do escopo atual do KACE:
controladores RGB/neopixel, expansores GPIO SX1509 ou acelerômetros ADXL345.
O KACE **reporta esses casos de forma elegante** ao invés de falhar.

📄 **[Ver os resultados completos do sweep → SWEEP_RESULTS.md](../../SWEEP_RESULTS.md)**  
Inclui o detalhamento por config de todas as 192 placas, impressoras e displays.

> Execute o sweep você mesmo: `python3 tests/run_tests.py --full-klipper-sweep`

---

## 🧪 Testes Automatizados

O KACE inclui um framework de testes de nível produção construído sobre a biblioteca padrão do Python — **sem dependências externas de teste**.

| O quê | Como |
|-------|------|
| Testes unitários | Lógica de derivação, carregamento YAML, injeção BLTouch, deployer offline |
| Regressão por snapshot | Arquivos `.cfg` golden travados por placa — falha em qualquer diferença de caractere |
| Integridade YAML | Validação de schema + verificação de precedência de padrões em cada execução |
| Sweep completo de configs | 192+ configs oficiais do Klipper parseadas e classificadas em cada push para `main` |
| Pipeline CI | GitHub Actions — 5 estágios, cancelamento de concorrência, bloqueio de merge |

```
Status atual: 59/59 testes passando ✅
```

```bash
python3 tests/run_tests.py                       # suite completa
python3 tests/run_tests.py --yaml-check          # apenas integridade YAML
python3 tests/run_tests.py --full-klipper-sweep  # sweep de 192 configs
```

Veja [`docs/en/TESTING.md`](../en/TESTING.md) para o guia completo de testes.

---

## 🏗️ Destaques da Arquitetura

- **Banco de dados de hardware em YAML** — adicione uma nova placa com apenas uma edição de YAML, sem alterações em Python
- **Derivação modular de firmware** — MCU → parâmetros Kconfig via correspondência de padrões ordenados
- **Recuperação automática com fallback** — cada carregamento de dados tem um fallback embutido; falhas de YAML nunca afetam a produção
- **Instalador sparse + shallow** — download mínimo em hardware Raspberry Pi
- **Dependências opcionais diferidas** — suporte SSH instalado no primeiro uso, não durante a instalação inicial
- **Geração de config determinística** — renderização Jinja2 protegida por snapshots e reproduzível
- **Classificação de sweep em 4 códigos** — `PASS / SAFE_ABORT / UNSUPPORTED / FAILURE` para diagnósticos claros

Veja [`docs/en/ARCHITECTURE.md`](../en/ARCHITECTURE.md) para a referência completa.

---

## 🛠️ Principais Funcionalidades

| Funcionalidade | Descrição |
| --- | --- |
| 🔍 **Auto-detecção de MCU** | Identifica sua placa conectada via USB/serial |
| 🧠 **Motor Inteligente** | Deriva a config de firmware sem `make menuconfig` manual |
| ⚙️ **Config Generator** | Gera um `printer.cfg` limpo a partir de dados oficiais do Klipper |
| 🔥 **Firmware Builder** | Compila `klipper.bin` / `.uf2` / `.hex` automaticamente |
| 🧪 **Pré-validação** | Detecta pinos TODO e erros antes de chegarem à sua impressora |
| 🌐 **GitHub Scraper** | Sempre usa configurações oficiais e atualizadas do Klipper |
| 💻 **CLI Interativa** | Wizard guiado em PT / EN / ES com interface ANSI colorida |
| 📡 **Dashboard do Sistema** | Detecta Klipper, Moonraker, Mainsail, Fluidd, Crowsnest na inicialização |

---

## 🧭 Como funciona

```
1. 🔍 Detectar MCU via USB/serial
2. 📦 Obter config oficial do Klipper para sua placa
3. 🧠 Derivar parâmetros de firmware (família MCU → Kconfig)
4. 💬 Perguntar apenas o que não pode ser assumido com segurança
5. ⚙️ Gerar printer.cfg (Jinja2, validado, sem pinos TODO)
6. 🔥 Compilar firmware automaticamente
7. 📁 Implantar em ~/kace/ (ou USB / SSH)
```

---

## 📦 Resultado Final

```
~/kace/
├── printer.cfg          # Configuração do Klipper pronta para uso
└── klipper.bin          # Firmware compilado (ou .uf2 / .hex)
```

---

## 🚀 Próximos Passos

1. Gravar firmware na sua placa (cartão SD / USB)
2. Enviar `printer.cfg` para o Klipper / Moonraker
3. Reiniciar:

```bash
sudo reboot
```

---

## 🙌 Contribuição e Feedback

O KACE evolui com a comunidade:

* 🐛 [Reportar bugs](https://github.com/3D-uy/kace/issues)
* 💡 Sugerir melhorias
* 🤝 [Contribuir — leia o guia](../en/CONTRIBUTING.md)

---

## ⚠️ Aviso Legal

O KACE é uma ferramenta open-source projetada para simplificar a configuração do Klipper.

Ao usar este software, você reconhece que o faz **por sua própria conta e risco**.  
O autor não se responsabiliza por **danos ao hardware, configurações incorretas ou comportamentos inesperados** decorrentes da configuração gerada.

👉 Sempre revise o `printer.cfg` gerado antes de imprimir.  
👉 Verifique o firmware antes de gravar.

---

## 🗑️ Desinstalar

```bash
sudo rm -f /usr/local/bin/kace   # ou: rm -f ~/.local/bin/kace
rm -rf ~/kace
```

---

## 📜 Licença

O KACE está licenciado sob GPL-3.0 🛠️

Para uso comercial, distribuição em produtos pagos ou re-branding, entre em contato com o autor.  
O nome "KACE" e a marca não podem ser usados em produtos comerciais sem permissão.

---

<p align="center">

⭐ Se gostou do projeto, deixe uma estrela  
🚀 Feito para simplificar o Klipper

</p>
