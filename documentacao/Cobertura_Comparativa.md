# Cobertura documental e comparabilidade

## Pergunta analítica

Quais fontes e períodos possuem suporte documental suficiente para comparar redes sem confundir lacunas de processamento com diferenças estruturais?

## Entradas

A edição ativa e validada da rede, carregada por `redes_construcao.carregar_rede`, fornece `noticias.csv.gz` e `arestas_noticias.csv.gz`. Os hashes, a assinatura esperada da rede, as identidades e versões documentais são verificados. Não há consultas a bancos de grafos ou provedores externos.

## Definições

| Campo | Significado |
|---|---|
| `corpus_news` | Notícias selecionadas na edição da rede, inclusive sem RE disponível |
| `re_completed_strict` | Notícias com estado `SUCCESS` ou `SUCCESS_ZERO` |
| `re_partial` | Notícias com estado `PARTIAL`, apresentadas separadamente |
| `too_few_mentions` | Notícias classificadas como `TOO_FEW_MENTIONS` |
| `re_other_states` | Demais estados; seu detalhamento consta na tabela de estados |
| `support_news` | Notícias com pelo menos uma ocorrência retida na rede sem identidade, fontes do corpus ou autolaços |
| `completed_without_retained_relations` | Notícias com RE concluída estritamente que não sustentam arestas finais |
| `retained_occurrences` | Soma das ocorrências retidas, não quantidade de fatos independentes |
| `strict_completion_share` | RE concluída estritamente dividida pelas notícias do corpus naquele recorte |
| `support_share` | Notícias de suporte divididas pelas notícias do corpus naquele recorte |

Os quatro grupos de estados recompõem o corpus. Suporte é outra dimensão e pode ocorrer em notícias `PARTIAL`; não deve ser somado às contagens de estados. Uma notícia pode sustentar várias arestas, mas conta uma única vez em `support_news`. As ocorrências são somadas a partir da contagem por aresta e notícia; o total deve recompor os pesos da rede.

## Limites de interpretação

- Uma notícia sem arestas finais não é necessariamente uma extração com falha: pode não conter relações semânticas elegíveis após exclusões.
- Anos sem notícias em alguma fonte são apresentados com contagem zero e proporções ausentes. Isso caracteriza o corpus, sem inferência sobre a produção total do veículo.
- As datas mínimas e máximas são observadas. Não comprovam cobertura integral do calendário; para um recorte por dia ou mês é necessário considerar também a precisão documental das datas.
- A presença de suporte nas três fontes é somente condição inicial. Quantidades, datas, seleção e cobertura da RE precisam ser avaliadas antes de escolher o período.
- Dividir métricas estruturais por mil notícias não controla, por si só, os efeitos do tamanho, da composição ou do mecanismo de seleção.
- Comparações futuras usarão os mesmos grupos de entidades e recalcularão pesos por fonte a partir das evidências documentais; não devem reutilizar pesos globais filtrando apenas um atributo de fonte.

## Reprodução

O módulo `redes_cobertura.gerar_cobertura` lê arquivos persistidos, sem depender de variáveis de etapas anteriores no kernel. `executar=False` confere a edição sem gravar saídas. `executar=True` gera tabelas, manifesto, apontador e ZIP. Uma assinatura diferente da esperada impede uso acidental de outra edição. Uma rede ampliada exige regenerar este diagnóstico e revisar os recortes e etapas dependentes.

As saídas científicas anteriores são preservadas. O módulo não incorpora automaticamente atualizações de outra pasta ou edição.
