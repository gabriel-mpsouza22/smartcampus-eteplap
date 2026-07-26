# Smart Campus

Sistema de gestão escolar completo — agendamento de recursos, biblioteca,
sinal automático, secretaria/portaria, ocorrências disciplinares,
monitoramento IoT (água, portões, ar-condicionado) e painel administrativo,
tudo em um único sistema web rodando localmente na rede da escola.

Construído com um banco de dados próprio (SCEDS), sem depender de serviços
externos ou internet para funcionar no dia a dia.

---

## Módulos

| Módulo | O que faz | Quem acessa |
|---|---|---|
| **Sinal** | Toca os horários automaticamente (padrão/sábado/prova), permite cancelar um toque específico e avisar turmas por WhatsApp em caso de saída antecipada | Coordenadora, Admin |
| **Agendamento de Recursos** | Professores reservam laboratórios, datashows, salas e espaços, com detecção automática de conflito de horário | Professor, Secretaria, Admin |
| **Biblioteca** | Catalogação rápida de livros (inclusive em lote, com numeração automática de exemplares), empréstimos e devoluções, controle de atraso | Bibliotecária, Admin |
| **Secretaria + Portaria** | Agenda de atendimentos do dia e chat interno em tempo quase real entre os dois setores | Secretaria, Portaria, Admin |
| **IoT** | Monitoramento de nível de água (bebedouros/cisterna), controle automático de portões (abre/fecha por horário) e ar-condicionado (liga automaticamente em dias úteis), com controle manual pelo painel | Portaria, Admin |
| **Ocorrências** | Registro rápido de ocorrências disciplinares por aluno, com alerta automático de reincidência e histórico completo | Coordenadora, Admin |
| **Monitoramento** | Painel de gráficos consolidando dados de todos os módulos (reservas, empréstimos, ocorrências, IoT) | Coordenadora, Admin |
| **Administração** | Cadastro/desativação de usuários, redefinição de senha, backup do banco de dados, configurações do servidor e visualização de logs | Admin |

---

## Tecnologia

- **Backend:** Python + Flask
- **Banco de dados:** SCEDS — motor próprio baseado em arquivos JSON por
  tabela, com uma linguagem de consulta em português (`sceds/`)
- **Frontend:** HTML + CSS + JavaScript puro (sem frameworks), gráficos em
  SVG nativo
- **Autenticação:** login por senha única — o sistema identifica o perfil do
  usuário automaticamente, sem precisar digitar usuário
- **IoT:** ESP32 (água, portões, ar-condicionado) comunicando via HTTP/JSON
  com tokens de dispositivo individuais

---

## Como instalar

Veja **`LEIA-ME.md`** para o passo a passo completo. Resumo:

```
python instalar.py
```

O instalador pergunta a identidade da escola, cadastra o administrador,
configura os recursos do agendamento e os dispositivos IoT (gerando um
token de segurança único para cada um), e cria o banco de dados.

Todos os demais usuários (professor, portaria, biblioteca, secretaria,
coordenação) são cadastrados depois, já pela interface web, em
**Administração → Usuários**.

---

## Estrutura de pastas

```
SmartCampus/
├── app.py                  # servidor Flask principal
├── core/                   # autenticação, roteador de módulos, configuração
├── sceds/                  # motor do banco de dados próprio
│   └── data/                 # tabelas (.sceds) e schemas
├── modulos/                # um subpacote por módulo (backend)
│   ├── sinal/
│   ├── agendamento/
│   ├── biblioteca/
│   ├── secretaria_portaria/
│   ├── iot/
│   │   ├── hardware/         # planejamento de hardware (Arduino/ESP32)
│   │   └── firmware/         # firmware pronto para os ESP32
│   ├── ocorrencias/
│   └── monitoramento/
├── admin/                  # painel administrativo (backend)
├── templates/               # HTML de cada módulo (Jinja2)
├── static/                  # CSS e JS compartilhados
├── backup/                  # backups gerados pelo painel admin
└── logs/                    # logs do servidor
```

---

## Hardware IoT

O módulo IoT foi projetado para ESP32 com três subsistemas físicos:
sensores de nível de água (JSN-SR04T), portões automáticos (relé + reed
switch) e ar-condicionado por infravermelho. Veja
`modulos/iot/hardware/PLANEJAMENTO_HARDWARE.md` para lista de compras,
esquemas de ligação e o firmware completo.

Para testar o módulo sem o hardware físico instalado:

```
python modulos/iot/simulador_iot_completo.py
```

---

## Segurança

- Senhas são únicas em todo o sistema e armazenadas com hash (bcrypt, com
  fallback seguro caso a biblioteca não esteja disponível)
- Cada dispositivo IoT tem seu próprio token de autenticação
- O painel administrativo é o único ponto de criação/gestão de usuários
