# Distribuição de graus e concentração complementar

## Perguntas distintas

O Gini resume a desigualdade dos graus de todos os nós. A análise de lei
de potência pergunta se uma região da distribuição, acima de um limiar,
pode ser descrita por uma forma específica. Não são medidas substitutas.
Seguindo a prioridade metodológica adotada, a forma da cauda e a comparação
de modelos são analisadas primeiro; o Gini e as participações superiores
complementam a descrição da concentração.

## Representação e ajuste

Utiliza-se o grau de vizinhos distintos da projeção simples não dirigida,
já calculado e verificado. Não se confundem força, número de menções e
grau. Os dados são os valores individuais, e não os pontos da CCDF ou
frequências de um histograma. Não se faz regressão de reta em log-log.

O modelo discreto é P(K=k | K≥xmin)=k^(-α)/ζ(α,xmin). O expoente é
estimado por máxima verossimilhança e xmin por minimização da distância KS,
usando powerlaw 1.5, discrete=True e estimate_discrete=False. Cada corte tem seu próprio xmin; comparar α
entre cortes não equivale a comparar sempre o mesmo intervalo de graus.

Exportam-se xmin, α, sigma iid, KS, número e fração de nós na cauda e
diagnósticos numéricos. Caudas com menos de 50 nós são sinalizadas como
pequenas; esse valor é uma convenção operacional, não garantia estatística.

## Alternativas e interpretação

A lei de potência é comparada a lognormal, exponencial e lei de potência
com corte exponencial sobre a mesma cauda definida pelo xmin da primeira.
As alternativas utilizam as implementações discretas e aproximações da
biblioteca. A ausência de aproximação na estimação da lei de potência
não torna exatas todas as alternativas.

A razão de log-verossimilhança R é não normalizada. R positivo favorece
a lei de potência relativamente à alternativa e R negativo favorece a
alternativa. O sinal sozinho não mede quão distinguíveis são os modelos.
O p-valor exportado é diagnóstico sob independência. A comparação com
corte exponencial é aninhada e requer cautela adicional na calibração.
Avisos de otimização, parâmetros problemáticos e valores não finitos
são registrados; resultados sinalizados exigem revisão, não interpretação
automática. Preferência relativa não demonstra adequação absoluta.
As 96 comparações são exploratórias, sem ajuste de multiplicidade.
Os cortes acumulados compartilham entidades e notícias e não são
32 replicações independentes de uma distribuição.
Mensagens que apenas informam o uso de uma comparação aninhada são
preservadas em library_messages, sem serem classificadas como falha numérica.

## Bootstrap de referência em 2025

O corte acumulado final é escolhido previamente para um diagnóstico
semiparamétrico. Em cada réplica, amostram-se valores do corpo empírico
abaixo de xmin e valores da cauda de lei de potência ajustada. O número
de valores de cauda é binomial com a fração observada. xmin e α são
reestimados sobre a réplica completa. Não se compara KS com uma tabela
que supõe parâmetros conhecidos de antemão.

O p diagnóstico é (1 + réplicas com KS≥KS observado)/(B+1). Com 199
réplicas, sua resolução e incerteza Monte Carlo são limitadas; o erro
padrão é informado. É possível aumentar B na configuração. As réplicas
já salvas, com mesmo código, insumo, ambiente e semente, são reutilizadas.
Uma réplica com falha deixa o diagnóstico incompleto e sem p, em vez
de ser descartada silenciosamente.

O corpo empírico e a cauda são uma referência univariada iid. Não se
simulam grafos; não se preservam dependência entre graus ou o limite
k≤N−1. A simulação pode gerar valores superiores ao máximo possível
no grafo original. Portanto, os p-valores e sigma são diagnósticos dessa
aproximação, e não garantias inferenciais para a rede. Uma análise com
modelos nulos de redes exigiria desenho metodológico próprio.

Não rejeitar a referência não prova lei de potência. Um ajuste restrito
à cauda não caracteriza automaticamente toda a rede como livre de escala.
Mesmo uma lei de potência bem descrita não demonstra conexão preferencial
ou Efeito Mateus: esses mecanismos serão investigados em etapa separada.

## Persistência e figuras

As réplicas são salvas em resultados/temporal/caudas/bootstrap. Os resultados
finais versionados contêm ajustes dos 32 cortes, 96 comparações, concentração,
distribuições, curva ajustada de 2025, réplicas e resumo do bootstrap, avisos
e catálogo de figuras. Os formatos são SVG, PNG e PDF. Nenhuma figura tem
o propósito de substituir a comparação quantitativa.

Os gráficos de CCDF e de concentração preservam as abordagens anteriores.
Gini usa toda a distribuição. Participações superiores usam ceil(N×fração)
e a soma dos graus como denominador, sem equivaler a arestas distintas.
O ajuste dos modelos permanece a análise principal nesta etapa.

## Referências

Clauset, A.; Shalizi, C. R.; Newman, M. E. J. Power-law distributions in
empirical data. SIAM Review, 51(4), 661–703, 2009.
https://doi.org/10.1137/070710111

Alstott, J.; Bullmore, E.; Plenz, D. powerlaw: A Python Package for Analysis
of Heavy-Tailed Distributions. PLoS ONE, 9(1), e85777, 2014.
https://doi.org/10.1371/journal.pone.0085777

Documentação e implementação: https://github.com/powerlaw-devs/powerlaw
e https://aaronclauset.github.io/powerlaws/.
