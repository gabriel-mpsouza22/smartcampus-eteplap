# Smart Campus ETEPLAP — Planejamento de Hardware IoT

Este documento detalha o hardware, a fiação e o firmware necessários para os 3
subsistemas físicos do módulo IoT: **nível de água**, **portões automáticos** e
**ar-condicionado por infravermelho**. Todos os dispositivos conversam com o
mesmo servidor Flask já em produção (`/iot/...`), usando os tokens definidos em
`modulos/iot/dispositivos.json`.

---

## Visão geral da arquitetura

```
┌─────────────────┐     Wi-Fi      ┌──────────────────────┐
│  ESP32 (água)   │───────────────▶│                      │
│  bebedouro 1    │  POST /agua    │                      │
├─────────────────┤                │                      │
│  ESP32 (água)   │───────────────▶│   Servidor Flask     │
│  bebedouro 2    │  POST /agua    │   (app.py)           │
├─────────────────┤                │                      │
│  ESP32 (água)   │───────────────▶│   Roda em um PC       │
│  cisterna       │  POST /agua    │   sempre ligado na    │
├─────────────────┤                │   rede da escola      │
│  ESP32 (portões)│◀──GET /comando │                      │
│  2 relés + reeds│───POST /status▶│                      │
├─────────────────┤                │                      │
│  ESP32 (A/C)    │◀──GET /comando │                      │
│  10x LED IR     │───POST /status▶│                      │
└─────────────────┘                └──────────────────────┘
```

Cada dispositivo é um ESP32 independente, conectado ao Wi-Fi da escola,
falando HTTP puro com o servidor. Não há comunicação direta entre ESP32s.

---

## 1. Módulo de Nível de Água

### Hardware necessário (por unidade — são 3 unidades idênticas)

| Item | Especificação | Qtd | Observação |
|---|---|---|---|
| Microcontrolador | ESP32 DevKit V1 (WROOM-32) | 1 | Já vem com Wi-Fi |
| Sensor | JSN-SR04T (ultrassônico à prova d'água) | 1 | Módulo com sonda separada da placa |
| Resistor | 1 kΩ | 1 | Divisor de tensão do ECHO |
| Resistor | 2 kΩ | 1 | Divisor de tensão do ECHO |
| Fonte | Fonte 5V/1A (USB ou adaptador) | 1 | Alimenta ESP32 e sensor |
| Caixa | Caixa plástica IP65 | 1 | Proteção contra umidade (cisterna fica exposta) |
| Cabo | Cabo blindado 3 vias, 2–5m | 1 | Liga a sonda ao módulo eletrônico |

**Por que JSN-SR04T e não o HC-SR04 comum?** O HC-SR04 tem a eletrônica e o
transdutor na mesma placa, o que não aguenta a umidade de dentro de uma
cisterna. O JSN-SR04T separa a sonda (que fica pendurada acima da água) da
eletrônica (que fica seca, dentro da caixa IP65).

### Por que ESP32 e não Arduino Uno?
O ESP32 já tem Wi-Fi embutido. Um Arduino Uno precisaria de um módulo Wi-Fi
adicional (ESP8266 como coprocessador ou shield Ethernet), o que encarece e
complica.

### Esquema de ligação

```
JSN-SR04T                         ESP32
─────────                         ─────
VCC  ───────────────────────────▶ 5V (pino VIN)
GND  ───────────────────────────▶ GND
TRIG ◀─────────────────────────── GPIO 5   (saída digital, 3.3V é suficiente)
ECHO ──────┬────────────────────▶ GPIO 18  (via divisor de tensão abaixo)
           │
         [1kΩ]
           │
           ├──────────────────────── nó do divisor (vai pro GPIO 18)
           │
         [2kΩ]
           │
          GND
```

**Por que o divisor de tensão no ECHO?** O JSN-SR04T responde no pino ECHO
com nível de 5V, mas o ESP32 só tolera até 3.3V nas entradas. Com R1=1kΩ e
R2=2kΩ, a tensão que chega no GPIO é `5V × (2k / (1k+2k)) ≈ 3.33V` — seguro.

### Posicionamento físico

- **Bebedouros**: sonda instalada no topo do reservatório interno, apontando
  para baixo, medindo a distância até a superfície da água.
- **Cisterna**: sonda instalada na tampa de inspeção, com cabo até a
  eletrônica que fica num ponto seco e protegido nas proximidades.

### Calibração necessária (por sensor)

Cada sensor precisa saber duas distâncias, medidas uma vez na instalação:
- `DISTANCIA_CHEIO` — distância da sonda até a água quando o reservatório
  está 100% cheio (em cm).
- `DISTANCIA_VAZIO` — distância da sonda até o fundo quando está vazio (em
  cm).

```
nivel_percentual = (DISTANCIA_VAZIO - distancia_medida) / (DISTANCIA_VAZIO - DISTANCIA_CHEIO) * 100
```

### Frequência de envio
A cada 60 segundos.

---

## 2. Módulo de Portões Automáticos

### Hardware necessário (1 controlador para os 2 portões)

| Item | Especificação | Qtd | Observação |
|---|---|---|---|
| Microcontrolador | ESP32 DevKit V1 | 1 | |
| Módulo relé | Relé duplo 5V, opto-isolado | 1 (2 canais) | Um canal por portão |
| Sensor de posição | Sensor magnético reed switch (NF) | 2 | Um por portão |
| Ímã | Ímã de neodímio pequeno | 2 | Fixado na folha móvel do portão |
| Fonte | Fonte 5V/2A | 1 | |
| Caixa | Caixa plástica para quadro elétrico | 1 | |

### Como o relé aciona o portão sem modificar a motorização existente
O relé do ESP32 é ligado **em paralelo** com o botão físico/entrada de
controle remoto já existente no motor. Quando o ESP32 aciona o relé por
~500ms, é como se alguém tivesse apertado o botão manualmente.

> ⚠️ Se o motor usa lógica de "pulso único alterna o estado" em vez de
> "um botão abre, outro fecha", adapte o firmware para 1 relé por portão,
> verificando o estado atual pelo reed switch antes de decidir se precisa
> pulsar.

### Esquema de ligação

```
ESP32                              Módulo Relé (2 canais)
─────                              ──────────────────────
GPIO 26  ─────────────────────────▶ IN1  (Portão Principal)
GPIO 27  ─────────────────────────▶ IN2  (Portão Secundário)
5V       ─────────────────────────▶ VCC
GND      ─────────────────────────▶ GND

                                    Relé 1 (COM/NO) ──▶ em paralelo com o
                                                         botão físico do
                                                         Portão Principal
                                    Relé 2 (COM/NO) ──▶ idem, Secundário

ESP32                              Reed Switches
─────                              ─────────────
GPIO 32  ◀───────────────────────── Reed switch Portão Principal (─▶ GND)
GPIO 33  ◀───────────────────────── Reed switch Portão Secundário (─▶ GND)
```

Reed switches usam `INPUT_PULLUP` interno do ESP32, sem resistor externo.

### Lógica de funcionamento
1. A cada 5 segundos, consulta `GET /iot/portao/<id>/comando`.
2. Compara com o que o reed switch está lendo agora.
3. Se diferente, aciona o relé por 500ms.
4. Aguarda o tempo de curso e reporta via `POST /iot/portao/<id>/status`.

---

## 3. Módulo de Ar-condicionado (Infravermelho) — Marca Agratto

### Hardware necessário (1 controlador para as 10 salas)

| Item | Especificação | Qtd | Observação |
|---|---|---|---|
| Microcontrolador | ESP32 DevKit V1 | 1 | |
| LED infravermelho | LED IR 940nm, alto brilho | 10 | Um por sala |
| Transistor | 2N2222 ou BC547 | 10 | Amplifica corrente pro LED |
| Resistor base | 1 kΩ | 10 | |
| Resistor coletor | 100 Ω | 10 | |
| Fonte | Fonte 5V/2A | 1 | |
| Cabo | Par trançado, conforme distância | 10 tramos | Do ESP32 até cada sala |
| Receptor IR (temporário) | TSOP38kHz | 1 | Só para a etapa de captura de código |

### Por que 10 LEDs e não 1?
Infravermelho é luz — não atravessa paredes. "1 controlador para 10 ACs"
significa 1 cérebro (ESP32) centralizado, com um emissor físico dentro de
cada sala, apontado para o aparelho correspondente.

### Códigos IR — marca Agratto

A biblioteca `IRremoteESP8266` **não tem suporte nativo à marca Agratto**
(verificado na documentação da biblioteca — ela não está entre as marcas com
protocolo decodificado). A solução usada aqui é a abordagem universal de
**código bruto (raw)**:

1. Um ESP32 com receptor TSOP38kHz "escuta" o controle Agratto real e grava
   a sequência exata de pulsos.
2. Essa sequência é copiada para o firmware definitivo e reproduzida com
   `sendRaw()`.

Veja `firmware/capturar_codigo_ir.ino` — roda uma única vez, na instalação.

> ⚠️ Isso assume que os 10 ares-condicionados são do mesmo modelo Agratto.
> Se houver modelos diferentes, repita a captura para cada modelo.

### Esquema de ligação (repetido para cada sala)

```
ESP32                    Transistor (2N2222)         LED IR
─────                    ───────────────────         ──────
GPIO x  ──[1kΩ]────────▶ Base
                         Coletor ──────[100Ω]───────▶ Ânodo do LED IR
                         Emissor ──────────────────▶ GND
5V ─────────────────────────────────────────────────▶ Coletor (via 100Ω)
```

GPIOs sugeridos: `4, 13, 14, 16, 17, 21, 22, 23, 25, 19`.

### Lógica de funcionamento
1. A cada 5 segundos, consulta `GET /iot/ac/comando`.
2. Se mudou desde a última execução, dispara o raw code nos 10 LEDs.
3. Reporta via `POST /iot/ac/status`.

> ⚠️ Infravermelho não confirma recebimento — o `estado_atual` reportado é
> sempre igual ao `estado_desejado` assumido como executado com sucesso.

---

## Lista de compras consolidada (resumo)

| Item | Quantidade total |
|---|---|
| ESP32 DevKit V1 | 5 (3 água + 1 portões + 1 A/C) |
| JSN-SR04T | 3 |
| Módulo relé 2 canais | 1 |
| Reed switch + ímã | 2 pares |
| LED IR 940nm | 10 |
| Transistor 2N2222/BC547 | 10 |
| Resistores diversos (1kΩ, 2kΩ, 100Ω) | ~35 unidades |
| Fontes 5V | 5 |
| Caixas IP65/quadro elétrico | 5 |
| Receptor IR TSOP38kHz (temporário, só captura) | 1 |

---

## Arquivos de firmware (Arduino/C++)

Veja a pasta `firmware/`:
- `sensor_agua.ino` — usar em cada uma das 3 unidades de água.
- `controlador_portoes.ino` — 1 unidade, controla os 2 portões.
- `capturar_codigo_ir.ino` — rodar **uma vez**, antes de tudo, para gravar
  os sinais reais do controle Agratto.
- `controlador_ac.ino` — 1 unidade, controla os 10 LEDs IR, usando os
  códigos capturados no passo anterior.

## Simulador de testes

`simulador_iot_completo.py` (na raiz do módulo IoT) simula os 5 dispositivos
simultaneamente, falando com o servidor real através da mesma API que o
hardware usaria — incluindo os atrasos realistas de portão e a variação
gradual do nível de água.
