# Extração de relações em notícias anteriores a 2026

## Instalação

1. Salve e feche o notebook atual. Extraia o conteúdo deste ZIP diretamente na pasta `PROJECT`, onde estão `Pipeline_Noticias_IA.ipynb` e `ner_dados.py`. Não crie outra pasta intermediária.
2. Os módulos e o instalador são novos. `fila_re.csv` e `manifesto_planejamento_re.json` são cópias idênticas do planejamento aprovado. Se esses dois arquivos já existirem, pode manter os existentes. Não substitua arquivos diferentes sem conferir a versão. Este pacote não contém `.env`, checkpoint ou dados NER.
3. Em um notebook temporário aberto na pasta `PROJECT`, execute:

```python
from pathlib import Path
from instalar_secao_re import instalar
instalar(Path.cwd())
```

O instalador cria uma cópia de segurança em `backups/` e adiciona as seções 22–24 ao notebook principal, preservando todas as células existentes. Uma segunda execução não duplica a seção. Feche a aba antiga sem salvá-la e reabra o notebook principal. O notebook temporário pode ser descartado.

## Primeiro envio

1. Execute a célula de configuração da seção 22. Mantenha `EXECUTAR_RE=False`, `LIMITE_RE=1` e `TRABALHADORES_RE=1`.
2. Execute a seção 23 para conferir a prévia, sem API. Não é necessário executar as seções anteriores.
3. Na configuração, selecione o provedor que deseja utilizar. O padrão é Google direto, com `GEMINI_API_KEY` do mesmo `.env` usado pelo NER. Para DeepInfra, use `PROVEDOR_RE='deepinfra'` e `DEEPINFRA_API_KEY`. O programa não escolhe o provedor com base nas chaves disponíveis. O contrato não pode ser alterado no mesmo checkpoint.
4. Altere **somente** `EXECUTAR_RE=True` na configuração e execute novamente as seções 22 e 23. O limite de uma chamada é intencional para confirmar a conexão real e o contrato antes de ampliar. O primeiro documento é da Folha, de 1994. A ordem subsequente é ano, data, fonte e identificador.
5. Execute a seção 24 e envie o ZIP `Resumo_RE_...zip` indicado no console. Não envie o `.env`.

O `KEY_NAME` é exibido como apelido, nunca como credencial. A ausência de erro na conferência local não confirma acesso à API. A confirmação real aparece em `ENVIO`, `RETORNO — HTTP 200` e `VALIDAÇÃO` por identificador de requisição.

## Continuidade e lotes

Depois de conferir a primeira resposta, um lote de 20 notícias com 2 trabalhadores permite avaliar desempenho e quota antes de ampliar. Limite e concorrência são independentes: o primeiro é o máximo de chamadas novas no lote, o segundo é o número simultâneo. O executor aceita até 10 trabalhadores. Não abra duas execuções sobre a mesma pasta.

As notícias concluídas ou já tentadas são puladas automaticamente. As respostas persistidas de requisições interrompidas são revalidadas sem chamada. Não existe reenvio automático de falhas ou resultados parciais nesta versão: eles devem ser inspecionados antes de autorizar nova tentativa. Uma notícia com erro de resposta não impede as seguintes. HTTP 400/401/402/403/404/429 interrompem novos envios; três falhas consecutivas de HTTP/transporte também pausam. Requisições já enviadas ainda podem terminar.

A conferência local mostra o início da fila aprovada; o progresso efetivo está na tabela `resultados/tabelas/re/progresso_re.csv`. A execução real seleciona apenas pedidos ainda não tentados. `api_calls` contabiliza as tentativas de envio pelo programa, incluindo falhas de transporte, e não equivale à cobrança confirmada pelo provedor.

Se o Jupyter ou computador for encerrado abruptamente e permanecer `dados/processados/re/execucao/execucao.lock`, primeiro confirme que **nenhuma execução está ativa**. Só então exclua essa pasta de bloqueio e execute novamente. Não exclua `checkpoint.sqlite3`, `respostas`, `validacoes` ou `requisicoes`. Um pedido sem resposta salva fica `UNCERTAIN`, pois o programa não pode garantir se o provedor o processou.

## Dados e saídas

A fila contém **9.126 notícias**: 8.362 primeiras extrações e 764 reprocessamentos. As 8.673 notícias selecionadas para reaproveitamento ficam fora das chamadas. Notícias de 2026 não entram nesta execução. Os arquivos existentes de relações não são alterados; a integração das relações reaproveitadas com as novas ocorrerá na consolidação posterior.

Entradas requeridas, já presentes no projeto:

- `dados/processados/noticias_preparadas.csv`;
- `dados/processados/ner/consolidado/{documentos_ner.csv,mencoes_pol.csv.gz,manifesto.json}`;
- `dados/processados/re/{fila_re.csv,manifesto_planejamento_re.json}`;
- `prompts/re_instrucoes.txt`.

A integridade das entradas é conferida por hash. Divergências exigem revisão do planejamento; não remova a verificação. O prompt fixo é o `TEST_D12_T13_L04_R15`, SHA-256 `34f37d5ec453ab94c22048a9b7f064aeac92aaed78d060059ca4bba5bf99a2bc`. O corpo variável contém texto e menções atuais. IDs de menção substituem referências documentais antigas; IDs de entidades resolvidas não são enviados.

A chave da requisição incorpora contrato, provedor, texto, versão documental e lista efetiva de entidades. O parser mantém a estratégia de lista JSON, fences, conteúdo envolvente, objetos `predictions`/`relations` e recuperação de objetos completos de listas truncadas. A recuperação parcial preserva triplas diferentes para o mesmo par; nunca transforma truncamento em conclusão integral. Rótulos e extremos são validados contra a taxonomia e as menções enviadas.

Google: `gemini-2.5-flash`, temperatura 0, seed 42 e saída JSON. DeepInfra: `google/gemini-2.5-flash`, temperatura 0, conforme o contrato operacional correspondente. Provedores e novas execuções podem produzir saídas diferentes, mesmo com instruções idênticas.

Saídas:

- `dados/processados/re/execucao/`: checkpoint, contrato, entradas por requisição, prompts, respostas e validações;
- `resultados/tabelas/re/progresso_re.csv`: situação de cada notícia;
- `resultados/tabelas/re/progresso_re_por_ano.csv`: cobertura anual;
- `resultados/tabelas/re/relacoes_extraidas.csv.gz`: relações no nível das menções, com indicação de respostas provisórias e cobertura NER;
- `resultados/re/Resumo_RE_...zip`: pacote para verificação.

`SUCCESS_ZERO` é uma conclusão válida com lista vazia; não prova ausência de relações no texto. `PARTIAL` e `INVALID_RESPONSE` requerem inspeção. Uma saída de RE válida a partir de NER parcial continua tendo a limitação de cobertura das entidades. Esta etapa não aplica inferências transitivas nem agrega pesos, e não altera a resolução de entidades.

A estimativa empírica do planejamento é **US$ 201,23** para a fila completa, usando US$ 7,10 por 322 notícias. Não constitui orçamento garantido: comprimento dos textos, respostas e condições de cobrança variam.

## Verificações locais

Dependências: `pandas` e `python-dotenv`, já utilizadas pelo projeto. Nenhum SDK adicional é necessário. Em uma célula:

```python
%run testar_re.py
```

Os testes não leem o `.env` e não usam rede. A validação desta entrega incluiu a montagem integral das 9.126 entradas, mas não chamadas reais nem avaliação semântica de novas relações. As relações deverão ser auditadas após o piloto.

Referências dos contratos HTTP: https://ai.google.dev/api/generate-content e https://github.com/deepinfra/docs/blob/main/quickstart.mdx .

## Normalização dos rótulos de relações

A função `normalize_re_label` aplica o procedimento textual original: minúsculas, remoção de acentos, troca de espaços e hífens por sublinhado, limpeza de caracteres, compactação de sublinhados e os dois aliases operacionais existentes. A normalização precede a validação contra os 15 rótulos e a deduplicação das triplas. Não converte rótulos semanticamente desconhecidos em relações válidas. As alterações de grafia são registradas na auditoria, preservando a resposta completa.

Esta classificação é independente das macrocategorias editoriais das notícias, armazenadas em `category_grouped`. A atualização não altera o prompt, a fila nem os parâmetros da API. Respostas truncadas continuam parciais.

Se ainda não instalou este pacote, siga a instalação normal. Se já havia copiado o pacote anterior, substitua os arquivos de código de mesmo nome pelos desta versão, mantendo o `.env`, os dados e os checkpoints. Reinicie o kernel antes de carregar os módulos atualizados; o instalador não precisa duplicar as seções existentes. Não reenvie chamadas anteriores para aplicar normalização. Caso já existam respostas reais validadas pela versão anterior, elas devem ser revalidadas localmente antes de consolidar os resultados.
