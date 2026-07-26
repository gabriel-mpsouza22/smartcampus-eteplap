

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <IRsend.h>




const char* WIFI_SSID     = "NOME_DA_REDE_WIFI";
const char* WIFI_PASSWORD = "SENHA_DO_WIFI";
const char* SERVIDOR_URL  = "http://192.168.0.108";
const char* DEVICE_TOKEN  = "614c2e402dd8303bbe41e91d"; 






const uint16_t codigoLigar[] = {
  3350, 1650, 500, 400, 500, 400, 500, 1250, 500, 400,
  500, 1250, 500, 400, 500, 1250, 500, 400, 500, 400,
  500, 1250, 500, 400, 500, 1250, 500, 1250, 500, 400,
  500, 1250, 500, 400, 500, 400, 500, 1250, 500, 400,
  500, 42000
};
const uint16_t TAMANHO_CODIGO_LIGAR = sizeof(codigoLigar) / sizeof(codigoLigar[0]);

const uint16_t codigoDesligar[] = {
  3350, 1650, 500, 400, 500, 1250, 500, 400, 500, 400,
  500, 1250, 500, 1250, 500, 400, 500, 400, 500, 1250,
  500, 400, 500, 400, 500, 1250, 500, 400, 500, 1250,
  500, 400, 500, 1250, 500, 400, 500, 400, 500, 400,
  500, 42000
};
const uint16_t TAMANHO_CODIGO_DESLIGAR = sizeof(codigoDesligar) / sizeof(codigoDesligar[0]);

const uint16_t FREQUENCIA_KHZ = 38;




const int PINOS_LED_IR[10] = {4, 13, 14, 16, 17, 21, 22, 23, 25, 19};
const int TOTAL_SALAS = 10;

const unsigned long INTERVALO_POLL_MS = 5000;

String ultimoComandoExecutado = "desligado";



void conectarWifi() {
  Serial.print("Conectando ao Wi-Fi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Conectado! IP: ");
  Serial.println(WiFi.localIP());
}

String consultarComandoAC() {
  HTTPClient http;
  String url = String(SERVIDOR_URL) + "/iot/ac/comando";
  http.begin(url);
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  int codigo = http.GET();
  String resultado = "";

  if (codigo == 200) {
    StaticJsonDocument<256> doc;
    deserializeJson(doc, http.getString());
    resultado = doc["estado_desejado"].as<String>();
  } else {
    Serial.printf("[ERRO] Consultar comando do A/C: HTTP %d\n", codigo);
  }

  http.end();
  return resultado;
}

void reportarStatusAC(const String& estado) {
  HTTPClient http;
  String url = String(SERVIDOR_URL) + "/iot/ac/status";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  StaticJsonDocument<128> doc;
  doc["estado"] = estado;
  String corpo;
  serializeJson(doc, corpo);

  int codigo = http.POST(corpo);
  if (codigo == 200) {
    Serial.printf("[OK] A/C reportado como '%s'\n", estado.c_str());
  } else {
    Serial.printf("[ERRO] Reportar status do A/C: HTTP %d\n", codigo);
  }
  http.end();
}

void enviarComandoParaTodasAsSalas(bool ligar) {
  for (int i = 0; i < TOTAL_SALAS; i++) {
    IRsend emissor(PINOS_LED_IR[i]);
    emissor.begin();

    if (ligar) {
      emissor.sendRaw(codigoLigar, TAMANHO_CODIGO_LIGAR, FREQUENCIA_KHZ);
    } else {
      emissor.sendRaw(codigoDesligar, TAMANHO_CODIGO_DESLIGAR, FREQUENCIA_KHZ);
    }

    Serial.printf("  Sala %d (GPIO %d): IR enviado (%s)\n",
                  i + 1, PINOS_LED_IR[i], ligar ? "ligar" : "desligar");
    delay(80);
  }
}

void setup() {
  Serial.begin(115200);
  conectarWifi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi caiu, tentando reconectar...");
    conectarWifi();
  }

  String desejado = consultarComandoAC();

  if (desejado != "" && desejado != ultimoComandoExecutado) {
    Serial.printf("Novo comando do A/C: '%s' (anterior: '%s')\n",
                  desejado.c_str(), ultimoComandoExecutado.c_str());

    bool ligar = (desejado == "ligado");
    enviarComandoParaTodasAsSalas(ligar);

    ultimoComandoExecutado = desejado;
    reportarStatusAC(desejado);
  }

  delay(INTERVALO_POLL_MS);
}
