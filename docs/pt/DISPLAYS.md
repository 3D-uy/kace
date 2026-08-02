# 🖥️ Guia de Compatibilidade de Displays

> **Filosofia do KACE:** detectar → classificar → informar → recomendar.
> O KACE nunca modifica nem desabilita automaticamente a configuração do seu display.

---

## Por que isso é importante?

O Klipper é um firmware **orientado à web**. Suas interfaces principais são [Mainsail](https://docs.mainsail.xyz/) e [Fluidd](https://docs.fluidd.xyz/) — painéis de controle baseados em navegador que oferecem controle total da impressora em qualquer telefone, tablet ou PC.

Muitas impressoras OEM vêm com telas touchscreen projetadas **especificamente para o firmware Marlin**. Essas telas usam protocolos proprietários, pontes seriais específicas do fabricante ou firmware de display personalizado que assume o conjunto de comandos do Marlin. Quando o Klipper substitui o Marlin, esses displays geralmente param de funcionar — não porque o Klipper está com defeito, mas porque a tela nunca foi projetada para ele.

> **Isso não é um bug do KACE.** É uma limitação de compatibilidade de displays OEM.

---

## Definição dos Status de Compatibilidade

| Status | Significado |
|--------|-------------|
| 🟢 **SUPORTADO** | Funciona nativamente no Klipper — sem preocupações |
| 🟡 **PARCIAL** | Funciona com limitações; funcionalidade de menu reduzida ou ausente |
| 🔴 **NÃO SUPORTADO** | Incompatível; pode causar tela preta, loop de boot ou conflitos seriais |
| ⬜ **NÃO TESTADO** | Sem dados de compatibilidade disponíveis; resultado desconhecido |

---

## Referência de Tipos de Display

### 🟢 Displays Suportados

Suportados nativamente pelo Klipper, sem configuração adicional:

| Tipo de Display | Exemplos | Notas |
|---|---|---|
| **LCD 12864 Padrão** | LCD original Ender 3, RepRapDiscount Smart LCD | Totalmente suportado |
| **mini12864** | BTT mini12864, display do kit SKR 1.4 | Totalmente suportado |
| **ST7920** | Controlador RepRapDiscount Smart LCD | Totalmente suportado |
| **UC1701** | Variantes mini12864 | Totalmente suportado |
| **HD44780** | LCD de caracteres 20×4 | Totalmente suportado |
| **SSD1306 OLED** | Vários módulos OLED pequenos | Totalmente suportado |

---

### 🟡 Suporte Parcial

Esses displays podem funcionar em um nível básico, mas provavelmente terão menus ausentes, funcionalidade reduzida ou problemas menores:

| Tipo de Display | Impressoras Comuns | Limitação Conhecida |
|---|---|---|
| **TFT Serial (tft_serial)** | Artillery Sidewinder, Artillery Genius, Artillery Hornet, Ender 6, CR-10 Smart | Menus seriais geralmente não funcionam sob Klipper |
| **DWIN / DGUS (dwin_set)** | Várias | Requer firmware de display comunitário compatível — sensível à versão |

**Abordagem recomendada para suporte parcial:** use a interface web (Mainsail/Fluidd) como interface principal. O display pode mostrar status básico, mas não é confiável para navegação em menus.

---

### 🔴 Displays Não Suportados

Esses displays não são compatíveis com o Klipper sem modificações significativas da comunidade:

| Tipo / Seção | Impressoras Comuns | Problema |
|---|---|---|
| **t5uid1 (protocolo DGUS)** | Creality CR-6 SE | Firmware OEM proprietário da Creality — Klipper não tem suporte integrado |
| **Neopixel / WS2812** | Várias | Fora do escopo de configuração atual do KACE |
| **Dotstar / APA102** | Várias | Fora do escopo de configuração atual do KACE |
| **Expansor GPIO SX1509** | Algumas placas MKS | Não suportado pelo motor de configuração do KACE |

---

## Compatibilidade de Impressoras OEM

### Creality CR-6 SE

**Status:** 🔴 NÃO SUPORTADO

A CR-6 SE usa uma tela touchscreen DGUS proprietária da Creality com firmware OEM projetado exclusivamente para o Marlin. O Klipper não tem suporte integrado para o protocolo `t5uid1` / DGUS.

**Sintomas comuns quando o display permanece conectado:**
- Tela preta ao iniciar
- Loop de boot / Klipper não inicia
- Conflitos de comunicação serial

**Ação recomendada:** Desconecte fisicamente o cabo do display da placa principal.

**Recurso da comunidade:** A comunidade open-source desenvolveu firmware de display DGUS personalizado para a CR-6 SE. Pesquise: *"CR-6 SE Klipper DGUS community firmware"*.

---

### Artillery Sidewinder X1 / X2

**Status:** 🟡 PARCIAL

Usa uma tela TFT serial projetada para o protocolo TFT do Marlin. Sob o Klipper:
- O display pode mostrar o status básico da impressora
- Os menus de navegação geralmente não funcionarão
- Alguns usuários não relatam problemas; outros relatam conflitos seriais

**Ação recomendada:** Use Mainsail ou Fluidd como interface principal. Mantenha o display conectado se desejar, mas não dependa dele para controle.

---

### Artillery Genius

**Status:** 🟡 PARCIAL

Mesma situação TFT serial do Sidewinder. Interface web recomendada para controle completo.

---

### Artillery Hornet

**Status:** 🟡 PARCIAL

Mesma situação TFT serial. Interface web recomendada.

---

## Sintomas Comuns e Causas

| Sintoma | Causa Provável |
|---------|---------------|
| Tela preta depois que o Klipper inicia | Firmware de display incompatível (ex.: t5uid1 na CR-6 SE) |
| Display mostra "No Printer Attached" | TFT serial não recebe respostas no formato Marlin |
| Klipper não consegue conectar ao MCU | Display está ocupando ou conflitando com a porta serial |
| Menu congelado ou sem resposta | Ponte serial TFT não recebe as respostas G-code esperadas do Marlin |
| Loop de boot / ciclo de reinicialização do Klipper | Firmware do display está reiniciando o MCU via linha DTR/reset |
| Menus parciais mas com entradas ausentes | Firmware TFT só trata parcialmente o formato de saída do Klipper |

---

## Abordagem Recomendada para Iniciantes

1. **Desconecte a tela touchscreen OEM** (especialmente para CR-6 SE, impressoras Artillery)
2. **Instale Mainsail ou Fluidd** no seu Raspberry Pi
3. **Acesse sua impressora de qualquer dispositivo** na sua rede local
4. Aproveite uma interface melhor do que a tela OEM

Mainsail e Fluidd oferecem:
- Status em tempo real da impressora e gráficos de temperatura
- Gerenciamento e upload de arquivos Gcode
- Histórico e estatísticas de impressão
- Integração de câmera web
- Edição completa de macros e configuração
- UI responsiva compatível com dispositivos móveis

---

## Para Usuários Avançados

Se quiser experimentar a compatibilidade com displays OEM:

- **Displays DGUS/DWIN:** Procure firmware de display Klipper da comunidade para o seu modelo específico. A versão do firmware deve corresponder exatamente ao seu hardware de display.
- **Displays TFT serial:** Alguns membros da comunidade tiveram sucesso parcial configurando o `[respond]` do Klipper e usando encaminhamento G-code personalizado. Isso é experimental.
- **Neopixel/RGB:** O Klipper suporta neopixel nativamente através da seção `[neopixel]` — o KACE simplesmente não o configura automaticamente. Você pode adicioná-lo manualmente após a geração.

O KACE nunca removerá nem desabilitará suas seções de configuração de display. Você é livre para experimentar.

---

## Veja Também

- [Configuração de Display do Klipper](https://www.klipper3d.org/Config_Reference.html#display) — referência oficial
- [Documentação do Mainsail](https://docs.mainsail.xyz/)
- [Documentação do Fluidd](https://docs.fluidd.xyz/)
- [Guia de Testes do KACE](../en/TESTING.md) *(em inglês)*
- [Resumo da arquitetura do KACE](../../README.md#architecture)
