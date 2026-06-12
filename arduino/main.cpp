// * * * * * * * * * * * * * * * * * * * * * * * * *
//              DESENVOLVEDORES
// * * * * * * * * * * * * * * * * * * * * * * * * *
//
// Aquiles Frazão => Hardware (Arduino / GPIO / RTC / Atuadores)
// Gabriel Moura  => Regras de Execução / Lógica do Sistema / Backend
//
// Turma: 2ºA - Redes
//
// * * * * * * * * * * * * * * * * * * * * * * * * *
// - Arduino Uno (controlador principal)
// - RTC DS3231 (relógio de tempo real)
// - Módulo relé (acionamento de carga externa)
// - LED Sirene (vermelho)
// - LED Integral (verde)
// - LED Prova (amarelo)
// - Botão de modo
// - Botão manual
// * * * * * * * * * * * * * * * * * * * * * * * * *
// DESCRIÇÃO DOS CÓDIGOS
//
// C++ / Arduino:
// Versão final do sistema em baixo nível, executada diretamente no Arduino Uno.
// Aqui ocorre a comunicação direta com hardware físico (RTC DS3231, relé, botões e LEDs),
// utilizando manipulação de pinos digitais e controle de tempo via millis().
// Esta camada substitui a abstração do Python por controle direto da placa,
// garantindo maior desempenho e resposta em tempo real.
//
// * * * * * * * * * * * * * * * * * * * * * * * * *

#include <Wire.h>
#include <RTClib.h>

RTC_DS3231 RTC;

constexpr byte PIN_RELE = 8;
constexpr byte PIN_MODO = 2;
constexpr byte PIN_MANUAL = 3;

constexpr unsigned long TEMPO_SIRENE = 10000UL;
constexpr unsigned long DEBOUNCE = 300UL;

struct HORARIO {
  byte hora;
  byte minuto;
};

const HORARIO HORARIOS_INTEGRAL[] PROGMEM = {
  {7,30},{8,20},{9,10},{9,30},
  {10,20},{11,10},{12,0},{13,20},
  {14,10},{15,0},{16,10},{17,0}
};

const HORARIO HORARIOS_PROVA[] PROGMEM = {
  {7,0},{8,0},{9,0},
  {10,0},{11,0},{12,0}
};

constexpr byte TOTAL_INTEGRAL =
sizeof(HORARIOS_INTEGRAL) / sizeof(HORARIOS_INTEGRAL[0]);

constexpr byte TOTAL_PROVA =
sizeof(HORARIOS_PROVA) / sizeof(HORARIOS_PROVA[0]);

enum MODO : byte {
  INTEGRAL,
  PROVA
};

MODO modoAtual = INTEGRAL;

bool sireneLigada = false;

unsigned long inicioSirene = 0;
unsigned long ultimoCliqueModo = 0;
unsigned long ultimoCliqueManual = 0;
unsigned long ultimaLeituraRTC = 0;

int ultimoHorarioTocado = -1;

inline void ligarSirene() {

  if (sireneLigada)
    return;

  digitalWrite(PIN_RELE, HIGH);

  sireneLigada = true;
  inicioSirene = millis();

  Serial.println(F("SIRENE LIGADA"));
}

inline void atualizarSirene() {

  if (!sireneLigada)
    return;

  if (millis() - inicioSirene >= TEMPO_SIRENE) {

    digitalWrite(PIN_RELE, LOW);

    sireneLigada = false;

    Serial.println(F("SIRENE DESLIGADA"));
  }
}

bool horarioExiste(byte hora, byte minuto) {

  const HORARIO* tabela;
  byte total;

  if (modoAtual == INTEGRAL) {
    tabela = HORARIOS_INTEGRAL;
    total = TOTAL_INTEGRAL;
  } else {
    tabela = HORARIOS_PROVA;
    total = TOTAL_PROVA;
  }

  for (byte i = 0; i < total; i++) {

    HORARIO h;

    memcpy_P(&h, &tabela[i], sizeof(HORARIO));

    if (h.hora == hora && h.minuto == minuto)
      return true;
  }

  return false;
}

void verificarModo() {

  if (digitalRead(PIN_MODO) != LOW)
    return;

  unsigned long agora = millis();

  if (agora - ultimoCliqueModo < DEBOUNCE)
    return;

  ultimoCliqueModo = agora;

  modoAtual = (modoAtual == INTEGRAL)
              ? PROVA
              : INTEGRAL;

  Serial.println();

  if (modoAtual == PROVA)
    Serial.println(F("MODO -> DIA DE PROVA"));
  else
    Serial.println(F("MODO -> INTEGRAL"));
}

void verificarManual() {

  if (digitalRead(PIN_MANUAL) != LOW)
    return;

  unsigned long agora = millis();

  if (agora - ultimoCliqueManual < DEBOUNCE)
    return;

  ultimoCliqueManual = agora;

  Serial.println();
  Serial.println(F("ACIONAMENTO MANUAL"));

  ligarSirene();
}

void verificarHorarios() {

  unsigned long agoraMillis = millis();

  if (agoraMillis - ultimaLeituraRTC < 1000)
    return;

  ultimaLeituraRTC = agoraMillis;

  DateTime agora = RTC.now();

  byte hora = agora.hour();
  byte minuto = agora.minute();

  int codigoMinuto = hora * 60 + minuto;

  if (!horarioExiste(hora, minuto))
    return;

  if (codigoMinuto == ultimoHorarioTocado)
    return;

  ultimoHorarioTocado = codigoMinuto;

  Serial.println();
  Serial.print(F("TOQUE AUTOMATICO "));
  Serial.print(hora);
  Serial.print(':');

  if (minuto < 10)
    Serial.print('0');

  Serial.println(minuto);

  ligarSirene();
}

void setup() {

  Serial.begin(115200);

  pinMode(PIN_RELE, OUTPUT);
  digitalWrite(PIN_RELE, LOW);

  pinMode(PIN_MODO, INPUT_PULLUP);
  pinMode(PIN_MANUAL, INPUT_PULLUP);

  if (!RTC.begin()) {

    Serial.println(F("RTC DS3231 NAO ENCONTRADO"));

    while (true);
  }

  Serial.println();
  Serial.println(F("================================="));
  Serial.println(F("SISTEMA DE SIRENE ESCOLAR"));
  Serial.println(F("MODO INICIAL: INTEGRAL"));
  Serial.println(F("================================="));
}

void loop() {

  verificarModo();
  verificarManual();
  verificarHorarios();
  atualizarSirene();
}
