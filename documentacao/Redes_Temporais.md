# Redes temporais acumuladas

## Pergunta analítica

Como se transforma a rede de entidades e relações semânticas da Folha de
S.Paulo à medida que incorporamos as notícias publicadas entre 1994 e 2025?
A série possui 32 cortes anuais. Todos integram a análise temporal; os 19
marcos de referência são uma seleção para comparações e apresentações.

## Construção

Para o corte t, selecionam-se os documentos da Folha entre 1994 e t,
inclusive. Cada aresta dirigida e tipada recebe a soma das ocorrências
retidas nesses documentos. Seus extremos formam o universo de nós.
Identificadores globais de grupos e arestas são preservados.

As projeções simples e ponderadas não dirigidas seguem a mesma definição
adotada na análise global e na comparação de fontes. A simples considera
um vínculo unitário por par de entidades. A ponderada soma os pesos dos
diferentes rótulos e direções. O suporte documental de cada par é a união
das notícias, evitando dupla contagem de documentos.

Os atributos de menção e de suporte relacional são distintos. Uma entidade
presente na rede pode ter menções em notícias do período ainda sem RE.
Essas menções entram em mention_count; relation_news_count utiliza apenas
notícias com participação nas relações retidas. Títulos, links, fontes,
categorias e versões documentais permanecem nos arquivos de proveniência.

As categorias editoriais podem ser recuperadas e agregadas a partir dos
vínculos documentais. Não se reduz uma entidade a uma categoria única.
Nenhum documento ou relação posterior ao corte compõe seus pesos.
A resolução de entidades é compartilhada e retrospectiva: nomes canônicos
podem incorporar informação da edição completa, sem simular um sistema
prospectivo de resolução de entidades.

## Validação e persistência

Cada corte é confrontado com contagens independentes da cobertura anual.
Todas as transições verificam inclusão dos nós e arestas anteriores,
preservação dos atributos canônicos, não redução dos pesos e não redução
da quantidade de notícias distintas por aresta. A conferência documental
também verifica as versões das notícias e a participação dos nós.

Uma pasta por ano contém oito CSVs comprimidos e um manifesto de hashes.
O índice da série só é atualizado após a conclusão dos 32 cortes.
A execução sequencial evita manter as 32 redes em memória ao mesmo tempo.
Cortes já gravados são validados e reutilizados na retomada. Um bloqueio
impede duas construções simultâneas na mesma série. Após interrupção
abrupta, confirme que o processo anterior encerrou antes de arquivar o
arquivo construcao.lock; não o remova durante uma execução ativa.

Uma nova edição da rede de origem gera outra assinatura temporal. Não se
misturam automaticamente extrações novas com os resultados desta edição.
As etapas posteriores deverão carregar a série pelo índice e registrar
sua assinatura, permitindo refazer apenas as análises dependentes.

## Interpretação

Uma rede acumulada retém entidades e conexões anteriores. Aumento de seu
tamanho, por si só, não demonstra diversificação do noticiário nem vantagem
cumulativa. A próxima análise deverá distinguir aparecimento de novas
entidades, novas conexões entre entidades conhecidas e reforço de vínculos.
Volume documental e cobertura de extração contextualizam cada mudança.

Um ano sem relações novas pode ter notícias sem extração concluída. Não
se preenchem essas lacunas com zeros de atividade jornalística. As redes
continuam acumuladas e válidas como representação da evidência disponível.
Nenhum período é previamente separado como principal ou secundário.

A investigação da distribuição de graus examinará a cauda e comparará
modelos antes de concluir sobre lei de potência. O coeficiente de Gini
será complementar. Essa investigação e as métricas estruturais, rankings,
comunidades e figuras não são executadas durante a construção dos cortes.

## Visualizações interativas

Os HTMLs existentes usam forceAtlas2Based com gravidade -55, gravidade
central 0.01, comprimento de mola 120, constante de mola 0.05 e
amortecimento 0.4. A física começa pausada para preservar o enquadramento;
o botão Ativar física permite movimentação interativa. Mudar o layout não
altera a rede científica ou as partições de comunidades.

Para comparações temporais, movimento e posicionamento exigem cuidado:
deslocamento de um nó na tela não demonstra mudança de importância.
As figuras comparativas deverão usar uma regra de seleção e um layout
documentados, preferencialmente com posições compartilhadas quando úteis.
O HTML exploratório pode oferecer física ativa; a exportação estática deve
permanecer reproduzível. A geração de novos HTMLs será uma etapa própria.
