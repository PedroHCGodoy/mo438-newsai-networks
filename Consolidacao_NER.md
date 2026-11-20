# Anotações NER: cobertura e consistência

## Fontes e disponibilidade

A base preparada contém 23.657 notícias. Este snapshot combina anotações importadas com uma exportação de inferências utilizada para complementar sua cobertura. As duas origens são registradas separadamente; a importação não é apresentada como execução integral do notebook.

| Origem ou situação | Notícias | Menções: dez categorias | Menções: pessoa/organização/local |
|---|---:|---:|---:|
| Anotações importadas tecnicamente compatíveis | 17.298 | 973.658 | 557.355 |
| Novas respostas completas | 520 | 25.962 | 14.398 |
| Novas respostas parciais | 153 | 13.988 | 7.263 |
| Tentativa sem resultado aproveitável | 8 | 0 | 0 |
| Sem processamento incorporado (2026) | 5.678 | 0 | 0 |
| Total | 23.657 | 1.013.608 | 579.016 |

Até 2025, há 17.979 notícias: 17.818 com anotações disponíveis, 153 parciais e oito sem resultado aproveitável. Nenhuma notícia desse período ficou sem tentativa ou anotação importada. Há menções aproveitáveis em 17.971 notícias. As 5.678 notícias de 2026 permanecem sem processamento incorporado.

As novas inferências correspondem a 681 requisições distintas e 682 tentativas. As 24 respostas interrompidas estão entre as 153 parciais, não são uma categoria adicional. Há 490 pendências de alinhamento: 399 sobreposições, 90 superfícies ausentes e um rótulo não previsto. Elas permanecem na auditoria; não foram convertidas em menções aceitas.

Os oito casos sem resultado compreendem cinco INVALID_RESPONSE, dois UNCERTAIN e um BLOCKED. Os documentos são identificáveis em `dados/processados/ner/consolidado/documentos_para_revisao.csv`. Esse arquivo também inclui as 153 notícias parciais. A tabela completa de cobertura mantém as notícias de 2026.

## Categorias

| Categoria | Menções |
|---|---:|
| ABSTRACCAO | 50.837 |
| ACONTECIMENTO | 23.278 |
| COISA | 92.133 |
| LOCAL | 141.127 |
| OBRA | 61.207 |
| ORGANIZACAO | 274.542 |
| OUTRO | 8.008 |
| PESSOA | 163.347 |
| TEMPO | 126.365 |
| VALOR | 72.764 |

## Verificações realizadas

A consolidação verificou as 1.013.608 menções contra as identidades e versões das notícias, o hash do texto de entrada, as dez categorias admitidas, os intervalos [start, end), as superfícies literais e a unicidade dos identificadores. O subconjunto PESSOA/ORGANIZACAO/LOCAL foi derivado da tabela integral e conferido por documento. Os campos originais de superfície, rótulo, posição, modelo e origem foram preservados.

O módulo rejeita conflitos entre fontes, dados textuais incompatíveis e destinos já existentes. Os arquivos são disponibilizados juntos com um manifesto de hashes. O carregador compara a base por conteúdo lógico, evitando falhas decorrentes apenas de quebras de linha, BOM ou outra serialização equivalente do CSV.

Foram aprovados 152 testes offline do executor e dez testes do módulo de dados. A configuração integral foi verificada sobre o corpus completo com chamadas desativadas, e o snapshot foi carregado em um namespace novo. Nenhuma chamada à API foi feita na consolidação ou nessas verificações. O checkpoint utilizado na complementação não foi alterado.

## Interpretação e limitações

Disponibilidade e alinhamento literal são condições técnicas, não medidas de precisão, revocação ou completude semântica. A completude original das anotações importadas não é inferida pela presença de menções. O manifesto identifica os arquivos de entrada; autoria ou finalidade histórica não documentadas permanecem desconhecidas.

As menções parciais são aproveitáveis, mas seus documentos exigem identificação explícita em análises posteriores. Uma futura análise deve declarar sua inclusão e avaliar a sensibilidade à cobertura incompleta. Dados que não possuem menções não devem ser interpretados como notícias sem entidades.

Textos com ruídos de coleta e datas suspeitas foram mantidos, sem exclusão ou correção automática nesta consolidação. A cobertura temporal utiliza as datas registradas e continua sujeita às limitações da coleta. Notícias longas com respostas truncadas e os oito casos sem resultado permanecem registrados para inspeção posterior.

Estas verificações concluem a consolidação técnica NER desta seleção de dados. Não constituem resultados de extração de relações, resolução de entidades, comunidades ou comparação estrutural de redes.
