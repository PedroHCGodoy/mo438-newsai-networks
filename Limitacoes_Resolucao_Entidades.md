# Limitações da resolução de entidades

A resolução de entidades utiliza formas textuais, normalização, aliases e representações vetoriais contextuais para associar menções a identidades consolidadas. As ressalvas abaixo se aplicam ao aproveitamento das associações de entrada e à implementação de referência adotada para essa etapa. Não constituem uma avaliação quantitativa da acurácia do método.

## Identidade e contexto

Uma forma textual pode designar entidades diferentes. A atribuição de um único grupo a todas as ocorrências de um nome pode reunir homônimos, pessoas com nomes semelhantes ou instituições de jurisdições diferentes. As representações contextuais agregadas por forma não garantem a desambiguação de cada ocorrência.

Similaridade de cosseno elevada indica proximidade entre representações, mas não comprova identidade. Pessoas distintas podem compartilhar sobrenomes e temas; instituições distintas podem desempenhar funções semelhantes. Siglas, sufixos familiares, referências a unidades numeradas e expressões genéricas exigem cuidado adicional.

Foram identificados exemplos pontuais de associações inadequadas nos resultados de entrada, incluindo referências a pessoas distintas no mesmo grupo e atribuição de formas institucionais genéricas a uma jurisdição específica. A frequência total desses problemas no corpus e sua influência sobre as redes ainda não foram quantificadas. Essas ocorrências não autorizam concluir que todos os agrupamentos estejam incorretos, nem que associações com origem conferida sejam semanticamente válidas.

## Recuperação de candidatos e restrições

A busca top-k limita os candidatos considerados. Além disso, o procedimento de deduplicação de pares da implementação de referência pode omitir pares encontrados apenas em uma direção da vizinhança. Essa possibilidade foi demonstrada em um contraexemplo controlado; seu impacto na execução examinada não foi medido.

O procedimento de união examinado aplica decisões de fusão, mas não garante a aplicação de decisões manuais KEEP_SEPARATE como restrições às uniões diretas ou transitivas. Não foi demonstrado que uma decisão manual específica tenha sido violada na execução examinada. A limitação descreve uma garantia ausente no código, e não uma contagem observada de violações.

## Interpretação das análises de redes

Fusões indevidas podem reunir vizinhanças, aumentar graus e forças ou criar conexões artificiais entre comunidades. Associações equivalentes não reconhecidas podem fragmentar uma entidade em vários nós. A direção e a magnitude dos efeitos sobre métricas e comparações dependem das ocorrências envolvidas; não foram estimadas nesta etapa.

A conferência de IDs, versões, superfícies, posições e proveniência verifica a continuidade técnica dos registros. Ela não substitui a avaliação da identidade das entidades. As menções originais e a origem das decisões devem permanecer disponíveis para auditoria.

## Trabalhos futuros

São previstos a avaliação sobre uma amostra anotada, a desambiguação contextual de ocorrências ambíguas, a revisão da recuperação de pares, a aplicação de restrições de separação durante a formação de componentes e análises de sensibilidade das redes à resolução de entidades. Essas melhorias ainda não integram o método de referência descrito aqui.
