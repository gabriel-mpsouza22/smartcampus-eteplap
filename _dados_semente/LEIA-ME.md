# _dados_semente/

Cópia "virgem" dos arquivos de configuração e schema que o `build_exe.py`
usa para montar o `.exe`. **O build nunca lê os arquivos equivalentes da
pasta de trabalho normal** (`core/config.json`, `core/turmas.json`,
`modulos/.../*.json`, `sceds/data/*.schema.json`) — só lê os daqui.

## Por que isso existe

Rodar `python app.py` ou o wizard de instalação localmente (pra testar
ou demonstrar o sistema) **modifica esses arquivos de verdade**, na
pasta de trabalho normal — é assim que a instalação de um cliente real
funcionaria também. O problema é que, sem essa separação, qualquer
sobra de teste (nome de instituição antiga, turmas de teste, admin de
demonstração, `caminho_base` apontando pra pasta errada) ia direto pro
próximo `.exe` gerado — foi exatamente isso que causou o erro 500 no
cadastro de alunos e a instituição errada aparecendo no wizard.

Com essa pasta, você pode testar e demonstrar à vontade na pasta de
trabalho normal — ela pode ficar "suja" sem problema nenhum — porque
o build sempre parte de um estado limpo e conhecido, guardado aqui.

## Quando atualizar esta pasta (só de propósito, manualmente)

Só quando você quiser mudar o que um cliente NOVO recebe por padrão —
por exemplo, adicionar uma coluna nova a um schema, ou mudar a lista
padrão de turmas. Nesse caso:

1. Faça a mudança normalmente na pasta de trabalho (`core/turmas.json`
   etc.) e teste com `python app.py` até funcionar do jeito que você
   quer.
2. Copie o arquivo já corrigido para cá, substituindo a versão antiga.
3. Rode `python build_exe.py` — o próximo `.exe` já sai com a mudança.

## O que NÃO fica aqui

Os arquivos `.sceds` (dados de alunos, ocorrências, etc.) não ficam
aqui — eles são gerados vazios, direto em `build_exe.py`
(`_montar_tabelas_sceds_vazias`), sem nenhum dado de exemplo. Só os
`.schema.json` (estrutura das tabelas, sem dado pessoal) ficam aqui.
