

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>




const char* WIFI_SSID     = "NOME_DA_REDE_WIFI";
const char* WIFI_PASSWORD = "SENHA_DO_WIFI";
const char* SERVIDOR_URL  = "http://192.168.0.108";  




const char* SENSOR_ID    = "bebedouro_1";              
const char* DEVICE_TOKEN = "81cfea5c01910fd5a49e1cc8"; 


const float DISTANCIA_CHEIO_CM = 10.0;   
const float DISTANCIA_VAZIO_CM = 80.0;   




const int PINO_TRIG = 5;
const int PINO_ECHO = 18;

const unsigned long INTERVALO_ENVIO_MS = 60000;  



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

float medirDistanciaCm() {
  digitalWrite(PINO_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PINO_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PINO_TRIG, LOW);

  unsigned long duracao = pulseIn(PINO_ECHO, HIGH, 30000UL);
  if (duracao == 0) return -1;

  float distancia = (duracao * 0.0343) / 2.0;
  return distancia;
}

float calcularNivelPercentual(float distanciaCm) {
  float nivel = (DISTANCIA_VAZIO_CM - distanciaCm) /
                (DISTANCIA_VAZIO_CM - DISTANCIA_CHEIO_CM) * 100.0;
  if (nivel < 0)   nivel = 0;
  if (nivel > 100) nivel = 100;
  return nivel;
}

void enviarLeitura(float nivelPercentual) {
  HTTPClient http;
  String url = String(SERVIDOR_URL) + "/iot/agua/" + SENSOR_ID;

  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  StaticJsonDocument<128> doc;
  doc["nivel"] = nivelPercentual;
  String corpo;
  serializeJson(doc, corpo);

  int codigoResposta = http.POST(corpo);

  if (codigoResposta == 201) {
    Serial.printf("[OK] Nivel enviado: %.1f%%\n", nivelPercentual);
  } else {
    Serial.printf("[ERRO] Servidor respondeu %d: %s\n",
                  codigoResposta, http.getString().c_str());
  }

  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_TRIG, OUTPUT);
  pinMode(PINO_ECHO, INPUT);

  conectarWifi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi caiu, tentando reconectar...");
    conectarWifi();
  }

  float distancia = medirDistanciaCm();

  if (distancia < 0) {
    Serial.println("[AVISO] Sem leitura válida do sensor (fora de alcance ou erro).");
  } else {
    float nivel = calcularNivelPercentual(distancia);
    Serial.printf("Distancia: %.1fcm  ->  Nivel: %.1f%%\n", distancia, nivel);
    enviarLeitura(nivel);
  }

  delay(INTERVALO_ENVIO_MS);
}
