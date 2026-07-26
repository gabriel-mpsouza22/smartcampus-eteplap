

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>




const char* WIFI_SSID     = "NOME_DA_REDE_WIFI";
const char* WIFI_PASSWORD = "SENHA_DO_WIFI";
const char* SERVIDOR_URL  = "http://192.168.0.108";
const char* DEVICE_TOKEN  = "e273012c0a9eab854aac76ce"; 




const int RELE_PRINCIPAL   = 26;
const int RELE_SECUNDARIO  = 27;
const int REED_PRINCIPAL   = 32;   
const int REED_SECUNDARIO  = 33;

const unsigned long DURACAO_PULSO_MS   = 500;
const unsigned long TEMPO_CURSO_MS     = 8000;
const unsigned long INTERVALO_POLL_MS  = 5000;

String ultimoComandoExecutadoPrincipal  = "";
String ultimoComandoExecutadoSecundario = "";



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

String lerEstadoFisico(int pinoReed) {
  return digitalRead(pinoReed) == LOW ? "fechado" : "aberto";
}

String consultarComando(const char* portaoId) {
  HTTPClient http;
  String url = String(SERVIDOR_URL) + "/iot/portao/" + portaoId + "/comando";
  http.begin(url);
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  int codigo = http.GET();
  String resultado = "";

  if (codigo == 200) {
    StaticJsonDocument<256> doc;
    deserializeJson(doc, http.getString());
    resultado = doc["estado_desejado"].as<String>();
  } else {
    Serial.printf("[ERRO] Consultar comando de %s: HTTP %d\n", portaoId, codigo);
  }

  http.end();
  return resultado;
}

void reportarStatus(const char* portaoId, const String& estado) {
  HTTPClient http;
  String url = String(SERVIDOR_URL) + "/iot/portao/" + portaoId + "/status";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  StaticJsonDocument<128> doc;
  doc["estado"] = estado;
  String corpo;
  serializeJson(doc, corpo);

  int codigo = http.POST(corpo);
  if (codigo == 200) {
    Serial.printf("[OK] %s reportado como '%s'\n", portaoId, estado.c_str());
  } else {
    Serial.printf("[ERRO] Reportar status de %s: HTTP %d\n", portaoId, codigo);
  }
  http.end();
}

void acionarRele(int pinoRele) {
  digitalWrite(pinoRele, HIGH);
  delay(DURACAO_PULSO_MS);
  digitalWrite(pinoRele, LOW);
}

void processarPortao(const char* portaoId, int pinoRele, int pinoReed,
                      String &ultimoComandoExecutado) {
  String desejado = consultarComando(portaoId);
  if (desejado == "") return;

  String atual = lerEstadoFisico(pinoReed);

  if (desejado == atual) {
    if (ultimoComandoExecutado != atual) {
      reportarStatus(portaoId, atual);
      ultimoComandoExecutado = atual;
    }
    return;
  }

  Serial.printf("%s: desejado='%s' atual='%s' -> acionando rele\n",
                portaoId, desejado.c_str(), atual.c_str());
  acionarRele(pinoRele);

  delay(TEMPO_CURSO_MS);

  String novoEstado = lerEstadoFisico(pinoReed);
  reportarStatus(portaoId, novoEstado);
  ultimoComandoExecutado = novoEstado;
}

void setup() {
  Serial.begin(115200);

  pinMode(RELE_PRINCIPAL, OUTPUT);
  pinMode(RELE_SECUNDARIO, OUTPUT);
  digitalWrite(RELE_PRINCIPAL, LOW);
  digitalWrite(RELE_SECUNDARIO, LOW);

  pinMode(REED_PRINCIPAL, INPUT_PULLUP);
  pinMode(REED_SECUNDARIO, INPUT_PULLUP);

  conectarWifi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi caiu, tentando reconectar...");
    conectarWifi();
  }

  processarPortao("principal", RELE_PRINCIPAL, REED_PRINCIPAL,
                   ultimoComandoExecutadoPrincipal);
  processarPortao("secundario", RELE_SECUNDARIO, REED_SECUNDARIO,
                   ultimoComandoExecutadoSecundario);

  delay(INTERVALO_POLL_MS);
}
