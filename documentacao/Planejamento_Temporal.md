# Cobertura e planejamento temporal

A série principal da Folha de S.Paulo possui 32 cortes acumulados anuais,
de 1994 a 2025. Os 19 marcos de referência são preservados em
marcos_referencia.csv. Todos os anos intermediários são incluídos.

calcular_cobertura e planejar_evolucao_temporal utilizam a série anual por
padrão. MARCOS_ANUAIS identifica os 32 cortes; MARCOS_REFERENCIA identifica
a seleção de 19 cortes. É possível configurar marcos explicitamente.

marcos_planejados.csv descreve a seleção configurada. alternativa_anual.csv
é mantido por compatibilidade e contém sempre os 32 cortes; quando a série
principal é anual, as duas tabelas coincidem. Não representa um segundo
experimento. marcos_referencia.csv descreve separadamente os 19 cortes,
com duração e cobertura dos intervalos entre eles.

A cobertura distingue corpus, RE concluída com ou sem relações, respostas
parciais, suporte relacional e ocorrências retidas. Não classifica qualquer
trecho da série como principal ou secundário. Ausência de extração não
demonstra ausência de relações no noticiário. A resolução de entidades
compartilhada é retrospectiva.

O planejamento conta os IDs presentes na evidência; a construção das
tabelas de cada rede é realizada por construir_redes_temporais. Consulte
Redes_Temporais.md para os critérios de construção e interpretação.
