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
//
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

const byte PIN_RELE = 8;
const byte PIN_MODO = 2;
const byte PIN_MANUAL = 3;

const unsigned long TEMPO_SIRENE = 10000;

struct HORARIO {
  byte HORA;
  byte MINUTO;
};

HORARIO HORARIOS_INTEGRAL[] = {
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
sizeof(HORARIOS_INTEGRAL) / sizeof(HORARIOS_INTEGRAL[0]);

HORARIO HORARIOS_PROVA[] = {
  {7, 0},
  {8, 0},
  {9, 0},
  {10, 0},
  {11, 0},
  {12, 0}
};

const int TOTAL_PROVA =
sizeof(HORARIOS_PROVA) / sizeof(HORARIOS_PROVA[0]);

enum MODO {
  INTEGRAL,
  PROVA
};

MODO MODO_ATUAL = INTEGRAL;

bool SIRENE_LIGADA = false;
unsigned long INICIO_SIRENE = 0;

int ULTIMO_MINUTO_TOCADO = -1;

unsigned long ULTIMO_CLIQUE_MODO = 0;
unsigned long ULTIMO_CLIQUE_MANUAL = 0;

void ligarSirene() {

  if (!SIRENE_LIGADA) {

    digitalWrite(PIN_RELE, HIGH);

    SIRENE_LIGADA = true;
    INICIO_SIRENE = millis();

    Serial.println("SIRENE LIGADA");
  }
}

void atualizarSirene() {

  if (SIRENE_LIGADA &&
      millis() - INICIO_SIRENE >= TEMPO_SIRENE) {

    digitalWrite(PIN_RELE, LOW);

    SIRENE_LIGADA = false;

    Serial.println("SIRENE DESLIGADA");
  }
}

bool horarioExiste(byte HORA, byte MINUTO) {

  if (MODO_ATUAL == INTEGRAL) {

    for (int INDICE = 0; INDICE < TOTAL_INTEGRAL; INDICE++) {

      if (HORARIOS_INTEGRAL[INDICE].HORA == HORA &&
          HORARIOS_INTEGRAL[INDICE].MINUTO == MINUTO) {

        return true;
      }
    }

  } else {

    for (int INDICE = 0; INDICE < TOTAL_PROVA; INDICE++) {

      if (HORARIOS_PROVA[INDICE].HORA == HORA &&
          HORARIOS_PROVA[INDICE].MINUTO == MINUTO) {

        return true;
      }
    }
  }

  return false;
}

void verificarModo() {

  if (digitalRead(PIN_MODO) == LOW) {

    if (millis() - ULTIMO_CLIQUE_MODO > 300) {

      ULTIMO_CLIQUE_MODO = millis();

      if (MODO_ATUAL == INTEGRAL) {

        MODO_ATUAL = PROVA;

        Serial.println();
        Serial.println("MODO ALTERADO -> DIA DE PROVA");

      } else {

        MODO_ATUAL = INTEGRAL;

        Serial.println();
        Serial.println("MODO ALTERADO -> INTEGRAL");
      }
    }
  }
}

void verificarManual() {

  if (digitalRead(PIN_MANUAL) == LOW) {

    if (millis() - ULTIMO_CLIQUE_MANUAL > 300) {

      ULTIMO_CLIQUE_MANUAL = millis();

      Serial.println();
      Serial.println("ACIONAMENTO MANUAL");

      ligarSirene();
    }
  }
}

void verificarHorarios() {

  DateTime AGORA = RTC.now();

  byte HORA = AGORA.hour();
  byte MINUTO = AGORA.minute();

  if (horarioExiste(HORA, MINUTO)) {

    if (ULTIMO_MINUTO_TOCADO != MINUTO) {

      ULTIMO_MINUTO_TOCADO = MINUTO;

      Serial.println();
      Serial.print("TOQUE AUTOMATICO ");
      Serial.print(HORA);
      Serial.print(":");

      if (MINUTO < 10)
        Serial.print("0");

      Serial.println(MINUTO);

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

  if (!RTC.begin()) {

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
