

#include <IRrecv.h>
#include <IRutils.h>

const uint16_t PINO_RECEPTOR = 15;
const uint16_t TAMANHO_BUFFER = 1024;
const uint8_t  TIMEOUT_MS = 50;

IRrecv receptor(PINO_RECEPTOR, TAMANHO_BUFFER, TIMEOUT_MS, true);
decode_results resultado;

void setup() {
  Serial.begin(115200);
  delay(500);
  receptor.enableIRIn();

  Serial.println();
  Serial.println("=== Captura de código IR — Smart Campus ETEPLAP ===");
  Serial.println("Aponte o controle Agratto para o receptor e aperte um botão...");
  Serial.println();
}

void loop() {
  if (receptor.decode(&resultado)) {
    Serial.println("──────────────────────────────────────────");
    Serial.println("Sinal capturado! Protocolo detectado pela biblioteca:");
    Serial.println(resultToHumanReadableBasic(&resultado));

    Serial.println();
    Serial.println("Copie o bloco abaixo para dentro de controlador_ac.ino:");
    Serial.println();

    Serial.print("const uint16_t codigoCapturado[");
    Serial.print(resultado.rawlen - 1);
    Serial.println("] = {");
    for (uint16_t i = 1; i < resultado.rawlen; i++) {
      Serial.print(resultado.rawbuf[i] * kRawTick);
      if (i < resultado.rawlen - 1) Serial.print(", ");
      if ((i % 10) == 0) Serial.println();
    }
    Serial.println();
    Serial.println("};");
    Serial.println("──────────────────────────────────────────");
    Serial.println();
    Serial.println("Aguardando o próximo botão...");

    receptor.resume();
  }
}
