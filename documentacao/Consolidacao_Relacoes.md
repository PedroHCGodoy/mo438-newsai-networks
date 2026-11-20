# Consolidação de relações entre menções

## Objetivo e unidade de análise

Esta etapa integra relações documentais em uma base rastreável e reproduzível. Cada linha representa uma relação dirigida e rotulada entre duas menções de uma notícia. Ainda não representa uma aresta agregada entre entidades resolvidas.

Os arquivos de execução permanecem preservados. O pós-processamento é local e produz uma camada derivada. A consolidação combina essa camada com importações cuja compatibilidade documental e correspondência de identificadores foram verificadas.

## Entradas

- `dados/processados/noticias_preparadas.csv`: identidade e versão das notícias, textos e metadados editoriais.
- `dados/processados/ner/consolidado/mencoes_pol.csv.gz`: ocorrências PESSOA, ORGANIZACAO e LOCAL com identidade e versão documental.
- `dados/processados/re/fila_re.csv`: escopo aprovado das extrações e reprocessamentos.
- `dados/processados/re/execucao/`: checkpoint, respostas, prompts e validações das tentativas.
- `dados/processados/re/curadoria/correcoes_ids_aprovadas.json`: decisões explícitas de reparo de identificadores, quando disponíveis.
- `dados/processados/re/importado/`: relações, documentos, correspondência de menções, cobertura NER e manifesto de uma importação validada.

O manifesto de importação registra hashes dos artefatos de origem. A correspondência usa `source_mention_id` dentro de cada notícia, com correspondência exata de superfície e categoria e uma associação bijetiva de toda a lista de entidades do prompt. Os textos foram comparados admitindo apenas a normalização de quebras de linha documentada pela auditoria. Não se infere correspondência apenas pela semelhança dos nomes.

A importação atual mantém 7.202 documentos com instruções canônicas e 1.471 com uma variante de formato das instruções, conforme a política de reaproveitamento adotada. O hash e o indicador `instruction_variant` preservam essa distinção; compatibilidade dos dados não equivale a instruções textualmente idênticas.

## Procedimento

1. Revalidar respostas persistidas contra seus prompts e contratos originais.
2. Aplicar apenas os mapas de IDs explicitamente aprovados; registrar candidatos ainda não aprovados e rejeições restantes.
3. Selecionar uma tentativa efetiva por notícia. Uma resposta atual utilizável tem prioridade sobre uma importação para a mesma notícia; uma falha de API, por si só, não substitui uma importação válida.
4. Conferir os endpoints no snapshot NER, incluindo pertencimento ao documento, versão, superfície e categoria.
5. Verificar rótulos, autorrelações, duplicidades e reconciliação da cobertura.
6. Separar relações de identidade (`ident`) das demais relações semânticas, preservando também o conjunto integral.
7. Exportar cobertura, pendências, estatísticas de uso da API e um manifesto versionado.

As leituras dos prompts preservam quebras de linha, inclusive CRLF dentro do texto. Converter implicitamente esses caracteres antes de verificar o hash poderia rejeitar um arquivo correto.

A normalização de rótulos, o parser e as instruções de inferência não são alterados pela consolidação. Não há chamadas à API.

## Saídas de cada versão

A pasta `dados/processados/re/consolidado/<assinatura>/` contém:

| Arquivo | Conteúdo |
|---|---|
| `relacoes_mencoes.csv.gz` | Todas as relações selecionadas entre menções, incluindo registros provisórios identificados. |
| `relacoes_identidade.csv.gz` | Apenas `ident`; não deve ser confundido com conexões semânticas entre atores diferentes. |
| `relacoes_semanticas.csv.gz` | Demais rótulos, ainda sem resolução de entidades ou agregação de pesos. |
| `cobertura_documental.csv` | Todas as notícias da base, com cobertura NER, estado RE, origem e quantidade de relações. |
| `cobertura_por_ano_fonte.csv` | Distribuição documental por ano, fonte, estado e origem. |
| `relacoes_por_rotulo_origem.csv` | Quantidade de relações por rótulo e origem. |
| `pendencias_inspecao.csv` | Relações com alertas diagnósticos, que não equivalem a erros confirmados. |
| `tentativas_tempo_custo.csv` | Duração, tokens e estimativa de custo disponível por resposta persistida, incluindo tentativas anteriores. |
| `tempo_custo_por_provedor.csv` | Totais de uso registrados por provedor e modelo; valores ausentes não são zero. |
| `manifesto.json` | Assinatura da versão, dependências, hashes, contagens e data de criação. |
| `LEIA_ME.txt` | Síntese e limites de interpretação. |

O ZIP de verificação contém as tabelas, os alertas e o manifesto; os três datasets completos de relações permanecem na pasta do snapshot e não são duplicados nesse ZIP.

A pasta de pós-processamento mantém também `candidatos_ids_inspecao.csv`, `rejeicoes_restantes.csv`, `correcoes_ids_aplicadas.csv`, os documentos revalidados e as auditorias. A lista de rejeições não é incorporada silenciosamente ao dataset de relações aceitas.

## Campos principais das relações

| Campo | Interpretação |
|---|---|
| `relation_id` | Hash estável de notícia, versão, endpoints e rótulo; independente da posição da linha e do provedor. |
| `news_id`, `news_version_id` | Identidade documental e versão do conteúdo. |
| `head_id`, `tail_id` | IDs das menções de origem e destino. |
| `label` | Rótulo normalizado da relação. |
| `head_surface`, `tail_surface` | Superfícies das menções, para inspeção. |
| `head_type`, `tail_type` | Categorias NER das menções. |
| `origin` | `IMPORT` ou `EXECUTION`; ambas permanecem rastreáveis. |
| `provider`, `model` | Provedor e modelo registrados na extração. |
| `request_id`, `attempt_id` | Identidade da tentativa atual; vazios quando a origem importada usa outra convenção de registro. |
| `source_document_id` | Identificador documental na coleção importada. |
| `instruction_sha256`, `instruction_variant` | Contrato de instruções e indicação da variante documentada. |
| `execution_state` | Estado técnico da resposta selecionada. |
| `ner_availability` | Cobertura NER documental, distinta da conclusão da chamada RE. |
| `technical_provisional` | Indica resposta RE parcial ou cobertura NER parcial. |
| `semantic_status`, `semantic_flags` | Situação da inspeção e alertas diagnósticos. `NOT_REVIEWED` não significa validado semanticamente. |

## Estados documentais e limitações

`SUCCESS` representa uma resposta tecnicamente aceita. `SUCCESS_ZERO` representa uma resposta válida sem relações; não comprova ausência real de relações no texto. `PARTIAL` mantém resultados utilizáveis com pendências. `HTTP_ERROR` e `UNCERTAIN` não autorizam reenvio automático. `PENDING` indica notícia da fila ainda não tentada. `NOT_READY_NER` indica indisponibilidade ou ausência do processamento NER necessário. `TOO_FEW_MENTIONS` indica menos de duas menções elegíveis.

As verificações automáticas não estimam precisão ou revocação semântica. Os alertas de tipos e direção são instrumentos de triagem. As relações provisórias permanecem disponíveis e identificadas, permitindo definir explicitamente os recortes das análises.

O custo é a estimativa devolvida pelo provedor, quando presente. Ausência dessa informação não significa chamada gratuita. As importações não possuem necessariamente histórico completo de custos. A soma das durações das chamadas mede tempo acumulado de requisições e não o tempo decorrido do lote paralelo. O relatório considera respostas persistidas; tentativas incertas sem envelope exigem inspeção no checkpoint.

A consolidação é um snapshot de cobertura parcial enquanto houver notícias pendentes. O recorte atual não inclui extrações de 2026. Ao mudar a base, o NER ou o escopo de execução, a compatibilidade documental e o planejamento devem ser atualizados antes de consolidar novos dados.

## Atualização incremental e dependências posteriores

A rotina nunca acrescenta linhas por simples anexação aos CSVs consolidados. Ela reconstrói a visão derivada a partir das entradas verificadas, selecionando um resultado por notícia. Repetir a operação com as mesmas entradas e código reutiliza a mesma pasta e confere suas saídas.

Quando houver novas tentativas ou novas decisões aprovadas, uma nova assinatura gera outra pasta. A versão anterior continua disponível. `consolidado/atual.json` indica a versão ativa e só é atualizado após a validação das saídas.

As próximas etapas devem iniciar com:

```python
from pathlib import Path
from re_consolidacao import carregar_consolidado_re

PASTA_RELACOES, MANIFESTO_RELACOES = carregar_consolidado_re(Path.cwd())
VERSAO_RELACOES = MANIFESTO_RELACOES['snapshot_sha256']
```

A leitura bloqueia resultados desatualizados se o checkpoint ou as entradas mudarem. Para uma análise histórica intencional, `permitir_desatualizado=True` permite consultar a versão ativa anterior, registrando a escolha e a assinatura no resultado. Cada etapa posterior deverá registrar essa assinatura, a versão da resolução de entidades e suas próprias configurações. Novas relações exigem atualizar a resolução aplicável, a agregação de evidências, as redes e as métricas dependentes; não exigem repetir inferências já disponíveis.

Fluxo de retorno: concluir um novo lote na seção 23, revalidar na 25, consolidar na 26 e executar novamente as etapas posteriores necessárias. A exportação da seção 24 é opcional porque o executor já exporta ao encerrar o lote. Novas pendências permanecem explícitas.

## Decisões científicas a discutir antes das próximas análises

- Aplicação da resolução de entidades e contabilização dos pesos sem inflar evidências repetidas dentro de uma notícia.
- Tratamento das identidades e das relações inversas ou transitivas em camadas derivadas rastreáveis.
- Recortes completos e de sensibilidade considerando cobertura NER/RE parcial.
- Ampliação dos 19 marcos históricos para os anos efetivamente disponíveis até 2025, após comparar cobertura, volume e fontes.
- Análise da distribuição de graus e da cauda, com Gini complementar, conforme orientação ainda sujeita à confirmação metodológica. Não pressupor lei de potência ou vantagem cumulativa.
- Preservação do escopo de rede global, comparação entre fontes, comunidades e evolução temporal.

## Reprodução da preparação da importação

`ferramentas/preparar_importacao_re.py` recebe `--projeto`, `--fontes` e `--destino`. A pasta de fontes precisa conter `Auditoria_Compatibilidade_RE.zip` e os arquivos de relações e prompts nomeados no manifesto de proveniência dessa auditoria. Essa ferramenta foi incluída para reproduzir a importação documentada desta coleção; não é um importador arbitrário de qualquer esquema RE.

O destino deve ser uma pasta nova. A ferramenta confere os hashes das fontes, a compatibilidade do texto, o escopo de entidades, o remapeamento bijetivo, as contagens das exportações e a taxonomia. Somente uma preparação concluída, com manifesto e saídas verificáveis, pode ser selecionada como entrada `importado`. Não é necessário executá-la para usar esta entrega: os arquivos já preparados estão incluídos.
