#include <Wire.h>
#include <RTClib.h>

  // - Arduino Uno (controlador principal)
  // - RTC DS3231 (relógio de tempo real)
  // - Módulo relé (acionamento de carga externa)
  // - LED Sirene (vermelho)
  // - LED Integral (verde)
  // - LED Prova (amarelo)
  // - Botão de modo
  // - Botão manual

RTC_DS3231 rtc;

const byte PIN_RELE = 8;
const byte PIN_MODO = 2;
const byte PIN_MANUAL = 3;

const unsigned long TEMPO_SIRENE = 10000;

struct Horario {
  byte hora;
  byte minuto;
};

Horario integral[] = {
  {7, 30},
  {8, 20},
  {9, 10},
  {9, 30},
  {10, 20},
  {11, 10},
  {12, 0},
  {13, 20},
  {14, 10},
  {15, 0},
  {16, 10},
  {17, 0}
};

const int TOTAL_INTEGRAL =
sizeof(integral) / sizeof(integral[0]);

Horario prova[] = {
  {7, 0},
  {8, 0},
  {9, 0},
  {10, 0},
  {11, 0},
  {12, 0}
};

const int TOTAL_PROVA =
sizeof(prova) / sizeof(prova[0]);

enum Modo {
  INTEGRAL,
  PROVA
};

Modo modoAtual = INTEGRAL;

bool sireneLigada = false;
unsigned long inicioSirene = 0;

int ultimoMinutoTocado = -1;

unsigned long ultimoCliqueModo = 0;
unsigned long ultimoCliqueManual = 0;

void ligarSirene() {

  if (!sireneLigada) {

    digitalWrite(PIN_RELE, HIGH);

    sireneLigada = true;
    inicioSirene = millis();

    Serial.println("SIRENE LIGADA");
  }
}

void atualizarSirene() {

  if (sireneLigada &&
      millis() - inicioSirene >= TEMPO_SIRENE) {

    digitalWrite(PIN_RELE, LOW);

    sireneLigada = false;

    Serial.println("SIRENE DESLIGADA");
  }
}

bool horarioExiste(byte hora, byte minuto) {

  if (modoAtual == INTEGRAL) {

    for (int i = 0; i < TOTAL_INTEGRAL; i++) {

      if (integral[i].hora == hora &&
          integral[i].minuto == minuto) {

        return true;
      }
    }

  } else {

    for (int i = 0; i < TOTAL_PROVA; i++) {

      if (prova[i].hora == hora &&
          prova[i].minuto == minuto) {

        return true;
      }
    }
  }

  return false;
}

void verificarModo() {

  if (digitalRead(PIN_MODO) == LOW) {

    if (millis() - ultimoCliqueModo > 300) {

      ultimoCliqueModo = millis();

      if (modoAtual == INTEGRAL) {

        modoAtual = PROVA;

        Serial.println();
        Serial.println("MODO ALTERADO -> DIA DE PROVA");

      } else {

        modoAtual = INTEGRAL;

        Serial.println();
        Serial.println("MODO ALTERADO -> INTEGRAL");
      }
    }
  }
}

void verificarManual() {

  if (digitalRead(PIN_MANUAL) == LOW) {

    if (millis() - ultimoCliqueManual > 300) {

      ultimoCliqueManual = millis();

      Serial.println();
      Serial.println("ACIONAMENTO MANUAL");

      ligarSirene();
    }
  }
}

void verificarHorarios() {

  DateTime agora = rtc.now();

  byte hora = agora.hour();
  byte minuto = agora.minute();

  if (horarioExiste(hora, minuto)) {

    if (ultimoMinutoTocado != minuto) {

      ultimoMinutoTocado = minuto;

      Serial.println();
      Serial.print("TOQUE AUTOMATICO ");
      Serial.print(hora);
      Serial.print(":");

      if (minuto < 10)
        Serial.print("0");

      Serial.println(minuto);

      ligarSirene();
    }
  }
}

void setup() {

  Serial.begin(115200);

  pinMode(PIN_RELE, OUTPUT);
  digitalWrite(PIN_RELE, LOW);

  pinMode(PIN_MODO, INPUT_PULLUP);
  pinMode(PIN_MANUAL, INPUT_PULLUP);

  if (!rtc.begin()) {

    Serial.println("RTC DS3231 NAO ENCONTRADO");

    while (true);
  }

  Serial.println();
  Serial.println("=================================");
  Serial.println("SISTEMA DE SIRENE ESCOLAR");
  Serial.println("Modo Inicial: INTEGRAL");
  Serial.println("=================================");
}

void loop() {

  verificarModo();

  verificarManual();

  verificarHorarios();

  atualizarSirene();

  delay(100);
}
