# Smart Campus — Pacote de Instalação

## Como instalar

1. Extraia este ZIP inteiro em uma pasta qualquer do computador Windows que
   vai rodar o servidor (precisa ficar sempre ligado e na rede da escola).

2. Confirme que a pasta `instalar.py` e a pasta `SmartCampus` ficaram lado a
   lado, exatamente assim:

   ```
   (pasta onde você extraiu)/
     ├── instalar.py
     └── SmartCampus/
         ├── app.py
         ├── core/
         ├── sceds/
         ├── modulos/
         ├── templates/
         ├── static/
         └── admin/
   ```

3. Abra o Prompt de Comando **como Administrador** nessa pasta e rode:

   ```
   python instalar.py
   ```

4. Responda as perguntas do instalador:
   - Pasta de instalação (padrão: `C:\SmartCampus`)
   - Nome da escola, sigla e bairro/cidade
   - Porta do servidor (padrão: 80)
   - Se quer instalar as dependências Python automaticamente
   - Nome e senha do administrador (ou deixe em branco para gerar uma senha)
   - Os recursos que podem ser reservados no módulo de Agendamento
     (laboratórios, datashows, salas, quadra etc. — pode cadastrar quantos
     quiser, inclusive vários exemplares do mesmo item de uma vez)
   - Os dispositivos IoT (sensores de água, portões, ar-condicionado) —
     o instalador gera um token de segurança único para cada um
   - Se quer que o sistema inicie sozinho com o Windows

5. Ao final, o instalador mostra (e salva em `logs/instalacao.txt`) a senha
   do administrador. **Anote essa senha agora** — ela não pode ser
   recuperada depois, só redefinida.

6. Inicie o servidor:

   ```
   cd C:\SmartCampus
   python app.py
   ```

7. Em qualquer computador da rede da escola, abra o navegador em
   `http://[IP-deste-computador]` e faça login com a senha do administrador.

## Depois de instalado

Todos os outros usuários (professores, portaria, biblioteca, secretaria,
coordenação) são cadastrados **pela própria página web**, em
**Administração → Usuários**, depois que o administrador faz login. O
instalador não pergunta sobre eles.

## Dispositivos físicos (Arduino/ESP32)

Veja `SmartCampus/modulos/iot/hardware/PLANEJAMENTO_HARDWARE.md` para a
lista de compras, esquemas de ligação e o firmware pronto para os ESP32
(água, portões e ar-condicionado). Os tokens gerados pelo instalador ficam
em `SmartCampus/modulos/iot/dispositivos.json` — copie cada um para o
firmware correspondente.

Para testar o módulo IoT sem ter o hardware físico ainda, use:
```
python SmartCampus/modulos/iot/simulador_iot_completo.py
```

## Observação sobre o código

Os arquivos deste pacote estão sem comentários de código (removidos
intencionalmente para reduzir o tamanho do pacote final). O funcionamento é
idêntico — nada foi alterado além dos comentários.
