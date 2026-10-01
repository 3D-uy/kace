# 🖥️ Configuração e suporte de displays

Revisado em 27 de setembro de 2026 contra as duas revisões oficiais do Klipper citadas abaixo.

## O que o KACE suporta atualmente

Suporte do driver no Klipper, configuração válida e compatibilidade elétrica são
três requisitos distintos. O nome de um driver ou um conector EXP não determina
o módulo exato, pinagem, alimentação, níveis de sinal ou cabeamento.

**Nenhum par físico de placa/display do catálogo atual do KACE tem evidência
suficiente do módulo e cabeamento para geração guiada de configuração ativa.**
Um resultado desconhecido bloqueia a geração mesmo com seleção manual ou risco
aceito. Classificações inseguras continuam restritivas. Rótulos legados
`supported`, `partial` ou de adaptadores nos dados não qualificam hardware.

O KACE verifica a configuração efetiva, includes e artefatos que gera, preserva
ou publica durante a instalação inicial e suas retomadas pendentes. Depois de
`DONE` (`COMPLETE` no checkpoint de firmware), alterações do usuário ficam fora
da responsabilidade do KACE: não há monitoramento, revalidação nem gerenciamento
dessas alterações. Iniciar explicitamente outra instalação é um fluxo separado.

## O que acontece com a configuração

| Rota | Comportamento atual |
|---|---|
| Sem display (`none`) | Omite blocos de display do novo hardware gerado. Não instrui a apagar arquivos manuais independentes no destino. |
| Detecção automática ou display físico selecionado com evidência desconhecida | Rejeita a geração; pinos aparentemente completos ou risco aceito não fornecem evidência de hardware. |
| Rota restritiva `unsafe` | A seleção explícita exige reconhecimento do risco. O renderizador pode produzir uma referência comentada inativa, nunca uma configuração ativa eletricamente qualificada. Uma referência insegura automática também pode ser comentada. |
| Hardware gerado salvo, macros ou seus includes | Verificados novamente antes da publicação e retomada pendente, inclusive quando não há mudanças. Rótulos salvos não contornam a verificação. |
| `[display]` ou include exclusivamente manual já existente no destino | Pode ser preservado após verificar configuração efetiva e requisitos do driver/transporte, com aviso de verificação elétrica. Isso não certifica todas as opções nem conexões físicas. |

Um include alcançado por hardware/macros gerados mantém essas restrições mesmo
quando um arquivo manual também o referencia. A preservação é condicional;
o KACE não promete manter ativa toda seção de display da origem.

## As 14 entradas físicas do catálogo

São chaves de seleção do KACE, **não catorze nomes de seção nativos do Klipper**.
As restrições de evidência acima se aplicam a todas elas.

| Chave KACE | Sintaxe oficial ou limite |
|---|---|
| `display` | `[display]` com `lcd_type` suportado e suas opções obrigatórias |
| `st7920` | `lcd_type: st7920` dentro de `[display]` |
| `emulated_st7920` | `lcd_type: emulated_st7920` dentro de `[display]` |
| `hd44780` | `lcd_type: hd44780` dentro de `[display]` |
| `hd44780_spi` | `lcd_type: hd44780_spi` dentro de `[display]` |
| `aip31068_spi` | `lcd_type: aip31068_spi` dentro de `[display]` |
| `uc1701` | `lcd_type: uc1701` dentro de `[display]` |
| `ssd1306` | `lcd_type: ssd1306` dentro de `[display]` |
| `sh1106` | `lcd_type: sh1106` dentro de `[display]` |
| `btt_tft35` | Rótulo de família, não seção ou driver nativo. O nome de um modo/revisão não qualifica o cabeamento. |
| `mks_mini12864` | Rótulo de família, não seção ou driver nativo. Sem inferência universal de SPI/FSMC. |
| `dwin_set` | Rótulo OEM legado, sem seção ou driver nativo nas revisões examinadas. |
| `tft_serial` | Rótulo OEM legado, sem seção ou driver nativo nas revisões examinadas. |
| `t5uid1` | Sem seção/driver nativo nas revisões examinadas; o KACE mantém sua política restritiva. |

Em um `[display]` mantido manualmente, `lcd_type` é obrigatório. Exemplos de campos
adicionais obrigatórios são `cs_pin`, `sclk_pin`, `sid_pin` para ST7920;
`rs_pin`, `e_pin`, `d4_pin` até `d7_pin` para HD44780; `latch_pin` para
HD44780_SPI/AIP31068_SPI; e `cs_pin`, `a0_pin` para UC1701. Emulated ST7920
exige `en_pin` e as três opções de pinos SPI por software. SSD1306/SH1106 podem
usar I2C ou SPI; selecionar SPI exige `cs_pin` e `dc_pin`. Barramentos por software
precisam de todos os seus pinos. Os defaults de barramento e os pinos MCU válidos
dependem do hardware selecionado. Estas listas **não são configurações prontas
para ativar**. Consulte a referência oficial para os requisitos completos e opções.

## Identidade OEM e módulos auxiliares

Os nomes oficiais exatos `printer-creality-ender3-2018.cfg` e
`printer-creality-ender3pro-2020.cfg` identificam a orientação genérica Ender 3;
`printer-creality-ender3-v2-2020.cfg` identifica V2 separadamente. Os aliases
históricos explícitos estão em `data/displays.yaml`. Neo, S1, Max, arquivos
renomeados e variantes futuras não herdam um display por coincidência parcial.
Reconhecer um perfil não identifica nem certifica a tela conectada e não instala
firmware comunitário.

Seções de software do Klipper como `[display_status]`, `[display_data ...]`,
`[display_template ...]` e `[menu ...]` são distintas dos displays físicos.
O rótulo legado `lcd_menu` do KACE não é uma seção nativa para copiar na
configuração. Esses recursos de software têm seus próprios requisitos.

Os módulos nativos `[neopixel ...]`, `[dotstar ...]`, `[adxl345 ...]` e
`[sx1509 ...]` não deixam de ser suportados pelo Klipper porque o manipulador
avançado genérico do KACE os emite como comentários. Esse manipulador preserva
referências, não instalações completas validadas. Os contratos existentes de
dependências de hardware por placa permanecem separados. **`[pca9685]` não é uma
seção autônoma válida: não descomente.** PCA9685 é interno ao Replicape; o KACE
não o converte em `[replicape]`.

## Diagnosticar um problema de display

Leia o erro real do Klipper e identifique placa, revisão da tela, conexão e
configuração efetiva. Uma tela preta sozinha não demonstra conflito de protocolo,
memória danificada, reset do MCU ou desligamento do Linux. Não use orientações
genéricas de família OEM como receita de cabeamento ou gravação de firmware.
Mainsail/Fluidd são interfaces web separadas, normalmente conectadas por Moonraker;
usá-las não comprova a segurança elétrica de uma tela conectada. O provisionamento
do Studio e a conectividade SSH também são separados do suporte ao driver LCD.

## Referências oficiais e limites

- [Referência de configuração fixada pelo KACE](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/docs/Config_Reference.md#display-support).
- [Registro de drivers LCD da revisão fixada](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/klippy/extras/display/display.py).
- [Referência da revisão posterior arquivada](https://github.com/Klipper3d/klipper/blob/ce7002bedf37e938bb483572949f3703ac6476cb/docs/Config_Reference.md#display-support).
- [Site oficial de referência](https://www.klipper3d.org/Config_Reference.html#display-support), que pode mudar depois dessas revisões.
- [Escopo do KACE](../en/SUPPORT_SCOPE.md) e [guia de testes](../DEVELOPMENT.md), em inglês.

A revisão posterior arquivada não é apresentada como o HEAD atual do upstream.
Estas verificações não qualificam um display físico nem constituem um teste E2E de hardware.
