# * * * * * * * * * * * * * * * * * * * * * * * * * 
#              DESENVOLVEDORES
# * * * * * * * * * * * * * * * * * * * * * * * * * 
#
# Aquiles Frazão => Hardware
# Gabriel Moura  => Bytecode
#
# Turma: 2ºA - Redes
#
# * * * * * * * * * * * * * * * * * * * * * * * * * 
#
# DESCRIÇÃO DOS CÓDIGOS
#
# Este arquivo representa a versão em CPython do sistema, gerada a partir do código Python original.
# Aqui ocorre a adaptação para execução na máquina virtual do Python (bytecode + runtime),
# incluindo abstração de hardware via GPIO e RTC simulados ou reais.
# Pequenas otimizações e ajustes de baixo nível foram aplicados manualmente no fluxo,
# mantendo compatibilidade com execução em Raspberry Pi ou ambiente simulado.
# Essa camada serve como ponte entre a linguagem de alto nível (Python)
# e a implementação mais próxima do hardware.
# * * * * * * * * * * * * * * * * * * * * * * * * * 

import time
from dataclasses import dataclass

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO_AVAILABLE = True
except:
    GPIO_AVAILABLE = False

class RTC_DS3231:
    def now(self):
        t = time.localtime()
        return DateTime(t.tm_hour, t.tm_min)

class DateTime:
    def __init__(self, hour, minute):
        self._hour = hour
        self._minute = minute

    def hour(self):
        return self._hour

    def minute(self):
        return self._minute

if GPIO_AVAILABLE:
    LOW = GPIO.LOW
    HIGH = GPIO.HIGH
else:
    LOW = 0
    HIGH = 1

class GPIOWrapper:
    def __init__(self):
        self.state = {}

    def pinMode(self, pin, mode):
        if GPIO_AVAILABLE:
            GPIO.setup(pin, GPIO.IN if mode == "IN" else GPIO.OUT)
        self.state[pin] = HIGH

    def digitalWrite(self, pin, value):
        if GPIO_AVAILABLE:
            GPIO.output(pin, value)
        self.state[pin] = value

    def digitalRead(self, pin):
        if GPIO_AVAILABLE:
            return GPIO.input(pin)
        return HIGH

PIN_RELE = 8
PIN_MODO = 2
PIN_MANUAL = 3

TEMPO_SIRENE = 10

@dataclass
class Horario:
    hora: int
    minuto: int

integral = [
    Horario(7, 30),
    Horario(8, 20),
    Horario(9, 10),
    Horario(9, 30),
    Horario(10, 20),
    Horario(11, 10),
    Horario(12, 0),
    Horario(13, 20),
    Horario(14, 10),
    Horario(15, 0),
    Horario(16, 10),
    Horario(17, 0),
]

prova = [
    Horario(7, 0),
    Horario(8, 0),
    Horario(9, 0),
    Horario(10, 0),
    Horario(11, 0),
    Horario(12, 0),
]

class Modo:
    INTEGRAL = 0
    PROVA = 1

rtc = RTC_DS3231()
gpio = GPIOWrapper()

modoAtual = Modo.INTEGRAL
sireneLigada = False
inicioSirene = 0
ultimoMinutoTocado = -1
ultimoCliqueModo = 0
ultimoCliqueManual = 0

def ligarSirene():
    global sireneLigada, inicioSirene
    if not sireneLigada:
        gpio.digitalWrite(PIN_RELE, HIGH)
        sireneLigada = True
        inicioSirene = time.time()
        print("SIRENE LIGADA")

def atualizarSirene():
    global sireneLigada
    if sireneLigada and (time.time() - inicioSirene >= TEMPO_SIRENE):
        gpio.digitalWrite(PIN_RELE, LOW)
        sireneLigada = False
        print("SIRENE DESLIGADA")

def horarioExiste(hora, minuto):
    lista = integral if modoAtual == Modo.INTEGRAL else prova
    for h in lista:
        if h.hora == hora and h.minuto == minuto:
            return True
    return False

def verificarModo():
    global modoAtual, ultimoCliqueModo
    if gpio.digitalRead(PIN_MODO) == LOW:
        if time.time() - ultimoCliqueModo > 0.3:
            ultimoCliqueModo = time.time()
            if modoAtual == Modo.INTEGRAL:
                modoAtual = Modo.PROVA
                print("MODO ALTERADO -> DIA DE PROVA")
            else:
                modoAtual = Modo.INTEGRAL
                print("MODO ALTERADO -> INTEGRAL")

def verificarManual():
    global ultimoCliqueManual
    if gpio.digitalRead(PIN_MANUAL) == LOW:
        if time.time() - ultimoCliqueManual > 0.3:
            ultimoCliqueManual = time.time()
            print("ACIONAMENTO MANUAL")
            ligarSirene()

def verificarHorarios():
    global ultimoMinutoTocado
    agora = rtc.now()
    hora = agora.hour()
    minuto = agora.minute()
    if horarioExiste(hora, minuto):
        if ultimoMinutoTocado != minuto:
            ultimoMinutoTocado = minuto
            print(f"TOQUE AUTOMATICO {hora}:{minuto:02d}")
            ligarSirene()

print("SISTEMA DE SIRENE ESCOLAR (CPYTHON)")
print("Modo Inicial: INTEGRAL")

while True:
    verificarModo()
    verificarManual()
    verificarHorarios()
    atualizarSirene()
    time.sleep(0.1)
