# * * * * * * * * * * * * * * * * * * * * * * * * * 
#              DESENVOLVEDORES
# * * * * * * * * * * * * * * * * * * * * * * * * * 
#
# Aquiles Frazão => Hardware
# Gabriel Moura  => Regras e Exceções BACKEND
#
# Turma: 2ºA - Redes
#
# * * * * * * * * * * * * * * * * * * * * * * * * * 
#
# DESCRIÇÃO DOS CÓDIGOS
#
# Python:
# Este código foi escrito em Python por ser uma linguagem de alto nível,
# mais simples e produtiva para desenvolvimento.
# Ele será processado pelo CPython, que o transforma em bytecode para execução.
# * * * * * * * * * * * * * * * * * * * * * * * * * 

import time
from dataclasses import dataclass

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

class GPIO:
    LOW = 0
    HIGH = 1

    def __init__(self):
        self.pins = {}

    def pinMode(self, pin, mode):
        self.pins[pin] = GPIO.HIGH

    def digitalWrite(self, pin, value):
        self.pins[pin] = value

    def digitalRead(self, pin):
        return GPIO.HIGH

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
gpio = GPIO()

modoAtual = Modo.INTEGRAL
sireneLigada = False
inicioSirene = 0
ultimoMinutoTocado = -1
ultimoCliqueModo = 0
ultimoCliqueManual = 0

def ligarSirene():
    global sireneLigada, inicioSirene
    if not sireneLigada:
        gpio.digitalWrite(PIN_RELE, GPIO.HIGH)
        sireneLigada = True
        inicioSirene = time.time()
        print("SIRENE LIGADA")

def atualizarSirene():
    global sireneLigada
    if sireneLigada and (time.time() - inicioSirene >= TEMPO_SIRENE):
        gpio.digitalWrite(PIN_RELE, GPIO.LOW)
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
    if gpio.digitalRead(PIN_MODO) == GPIO.LOW:
        if time.time() - ultimoCliqueModo > 0.3:
            ultimoCliqueModo = time.time()
            if modoAtual == Modo.INTEGRAL:
                modoAtual = Modo.PROVA
                print("\nMODO ALTERADO -> DIA DE PROVA")
            else:
                modoAtual = Modo.INTEGRAL
                print("\nMODO ALTERADO -> INTEGRAL")

def verificarManual():
    global ultimoCliqueManual
    if gpio.digitalRead(PIN_MANUAL) == GPIO.LOW:
        if time.time() - ultimoCliqueManual > 0.3:
            ultimoCliqueManual = time.time()
            print("\nACIONAMENTO MANUAL")
            ligarSirene()

def verificarHorarios():
    global ultimoMinutoTocado
    agora = rtc.now()
    hora = agora.hour()
    minuto = agora.minute()
    if horarioExiste(hora, minuto):
        if ultimoMinutoTocado != minuto:
            ultimoMinutoTocado = minuto
            print(f"\nTOQUE AUTOMATICO {hora}:{minuto:02d}")
            ligarSirene()

print("=================================")
print("SISTEMA DE SIRENE ESCOLAR (PY)")
print("Modo Inicial: INTEGRAL")
print("=================================\n")

while True:
    verificarModo()
    verificarManual()
    verificarHorarios()
    atualizarSirene()
    time.sleep(0.1)
