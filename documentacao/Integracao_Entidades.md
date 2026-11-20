# Associações de entidades e integração com relações documentais

## Objetivo

Aplicar uma versão documentada de resolução de entidades às menções NER e aos endpoints das relações extraídas. A etapa integra os resultados da formação dos grupos; não recalcula embeddings, não executa um novo algoritmo de agrupamento e não usa relações `ident` para fundir grupos automaticamente.

A unidade de evidência continua sendo a relação entre menções de uma notícia. A adição dos IDs de entidade não converte essa evidência em uma aresta agregada e não determina seu peso.

## Entradas e rastreabilidade

- Uma versão ativa e validada da consolidação RE, obtida por `carregar_consolidado_re`.
- O snapshot NER `dados/processados/ner/consolidado/mencoes_pol.csv.gz`.
- A tabela completa `associacoes_mencoes.csv.gz`, o `registro_entidades.csv` e seu `manifesto.json`, registrados em `dados/processados/entidades/entradas/<assinatura>/`.

O registro inicial aceita uma pasta ou um ZIP contendo esses três arquivos. As tabelas são conferidas contra os hashes do manifesto e copiadas para uma versão preservada dentro do projeto. O apontador `entradas/atual.json` seleciona a fonte. Nenhum ID, nome ou marca de revisão é modificado durante o registro.

O manifesto original pode referenciar outros produtos da etapa de resolução. Esta integração transporta e verifica somente os dois datasets necessários e o manifesto, sem declarar que os demais arquivos foram copiados.

## Verificações

1. Unicidade dos IDs de menção e grupo; preenchimento dos IDs de entidade.
2. Correspondência exata entre resolução e snapshot NER para todas as menções elegíveis: notícia, versão, hash de entrada, categoria e superfície.
3. Coerência entre nome e categoria do grupo e os valores associados à menção.
4. Conferência dos endpoints de todas as relações contra o mapa por `mention_id`.
5. Preservação dos identificadores originais de relação, notícia e menção; igualdade das contagens de entrada e saída.
6. Preservação das marcas de qualidade e inspeção e da assinatura das duas etapas de origem.

Uma menção nova sem associação interrompe a integração; não recebe silenciosamente um grupo novo. A atualização da RE sobre menções já associadas pode ser integrada sem repetir a formação dos grupos. Mudanças no NER exigem atualizar a resolução correspondente.

## Saídas

Cada execução validada cria ou reutiliza uma pasta em `dados/processados/entidades/resolucao/<assinatura>/`.

| Arquivo | Conteúdo |
|---|---|
| `mencoes_resolvidas.csv.gz` | Cópia exata da tabela completa de associações, incluindo método, proveniência, qualidade e revisão. |
| `entidades.csv.gz` | Registro dos grupos utilizados, com contagens de menções e notícias, menções para revisão e presença em relações. |
| `relacoes_resolvidas.csv.gz` | Todas as relações de entrada com seus campos preservados e os grupos dos endpoints acrescentados. |
| `diagnosticos_resolucao.csv.gz` | Registros com sinais de divergência ou com endpoints marcados para revisão. |
| `diagnosticos_por_tipo.csv` | Contagens dos quatro papéis documentais descritos abaixo. |
| `grupos_por_categoria.csv` | Grupos, menções e menções para revisão por tipo NER. |
| `metodos_associacao.csv` | Contagens por estado da associação documental. |
| `manifesto.json` | Assinaturas, dependências, hashes das saídas, duração e contagens. |
| `LEIA_ME.txt` | Resumo e limites de interpretação. |

Os arquivos grandes permanecem no snapshot. O ZIP de resumo contém o manifesto, as tabelas menores e os diagnósticos, sem duplicar o conjunto completo de relações ou associações. Não inclui credenciais ou textos integrais das notícias.

## Campos acrescentados às relações

Para cada endpoint, são acrescentados `head_entity_id`/`tail_entity_id`, `head_entity_name`/`tail_entity_name`, a marca de revisão e os estados de resolução e qualidade. Os campos originais `head_id` e `tail_id` continuam identificando as menções.

`within_entity` indica igualdade dos IDs de grupo operacionais, não uma identidade real validada manualmente. `relation_role` distingue:

| Valor | Interpretação |
|---|---|
| `IDENTITY_WITHIN_GROUP` | Relação `ident` entre menções já associadas ao mesmo grupo. |
| `IDENTITY_BETWEEN_GROUPS` | Relação `ident` entre menções associadas a grupos diferentes. |
| `SEMANTIC_WITHIN_GROUP` | Outro rótulo de relação com ambos os endpoints no mesmo grupo. |
| `SEMANTIC_BETWEEN_GROUPS` | Outro rótulo de relação entre grupos diferentes. |

`entity_review_required` indica que pelo menos uma menção do registro está marcada para inspeção. `resolution_flags` preserva os sinais de identidade entre grupos diferentes, relação semântica dentro de grupo e revisão dos endpoints. Os alertas semânticos e as marcas de provisoriedade da etapa RE permanecem em suas colunas originais.

Não são executadas exclusões, fusões, inversões, expansões transitivas ou agregação de pesos. Esses tratamentos pertencem à etapa seguinte e precisam de uma política explícita.

## Limitações científicas

Cobertura completa de IDs não equivale a precisão semântica completa. Um grupo representa uma associação operacional estabelecida pelo método adotado. Permanecem possíveis homônimos indevidamente agrupados, variantes ainda separadas e erros de classificação NER ou de RE.

A abordagem adotada preserva as decisões anteriores, incluindo associações documentais, normalização de formas, associações semânticas, grupos operacionais novos e revisões manuais registradas. Não se acrescenta nesta etapa uma verificação contextual sistemática por município, estado, parentesco ou trajetória individual, nem se modifica a política anterior de agrupamento. Essas melhorias ficam como possibilidades para outra versão, conforme a decisão metodológica de preservar o método atual.

`IDENTITY_BETWEEN_GROUPS` não é automaticamente um erro nem uma autorização de fusão. Pode refletir granularidade diferente entre os procedimentos, grupos ainda separados ou uma relação equivocada. São registros de evidência entre menções, não pares únicos entre grupos. Exemplos de pares de nomes observados nos diagnósticos incluem Fed–Federal Reserve e Pequim–China; cada caso exige contexto para decisão.

`SEMANTIC_WITHIN_GROUP` também exige inspeção: pode decorrer da associação de entidades, do rótulo ou da direção extraída. Os registros continuam disponíveis e não viram automaticamente autoarestas do grafo principal.

O registro completo de grupos não define sozinho o universo dos nós da rede. Há grupos com menções em notícias cuja RE ainda não foi concluída. A falta atual de arestas não comprova isolamento real. Antes da análise estrutural, deve-se definir o recorte documental, a cobertura e o tratamento de nós sem relações, para que comparações e medidas de desigualdade sejam interpretáveis.

## Atualização e consumo nas próximas etapas

A nova seção 27 pode ser repetida após novas consolidações. Com entradas e código idênticos, ela confere e reutiliza a versão existente. Novas entradas criam outra assinatura e preservam as saídas anteriores. O processamento das relações ocorre em blocos para limitar o consumo de memória.

As próximas etapas devem carregar explicitamente:

```python
from pathlib import Path
from entidades_integracao import carregar_entidades_integradas

PASTA_ENTIDADES, MANIFESTO_ENTIDADES = carregar_entidades_integradas(Path.cwd())
VERSAO_ENTIDADES = MANIFESTO_ENTIDADES['snapshot_sha256']
```

A leitura bloqueia snapshots quando há uma nova consolidação RE, outra fonte de associações ou mudanças nas entradas NER. Cada etapa posterior deverá registrar essa assinatura e suas próprias configurações.

Fluxo incremental: novo lote RE → pós-processamento 25 → consolidação 26 → integração 27 → atualização das redes e análises dependentes. A geração de grupos só precisa ser retomada se surgirem menções sem associação ou uma nova política de resolução for aprovada.
