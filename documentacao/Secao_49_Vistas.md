# 49. Exploração visual das redes acumuladas

Cole o bloco seguinte em uma célula Markdown:

```markdown
## 49. Exploração visual das redes acumuladas

O painel explora os 32 cortes anuais acumulados da Folha de S.Paulo,
de 1994 a 2025. Os destaques são selecionados automaticamente por grau
na rede completa do ano escolhido, incluindo empates na 15ª posição.
O grau conta vizinhos distintos; o critério e os valores aparecem na tela.

A busca cobre todas as entidades da série por nome ou ID. A entidade
selecionada abre uma vista de sua vizinhança; o texto e o ID são mantidos
ao trocar de ano, com indicação de ausência antes de sua entrada na rede.
Borda vermelha e halo identificam a busca. As cores de preenchimento representam
tipos; tamanho representa grau em escala logarítmica, sem proporção direta.
Os nomes estão visíveis e a física ativada por padrão, com opções de
controle. Nenhuma interação modifica a rede ou seus indicadores.

A cobertura das extrações e as notícias de suporte são acessíveis para
contextualizar a leitura. Em 2021 não há RE concluída nesta edição.
Ausência de crescimento observado não significa ausência de relações
no noticiário. Os subgrafos exibidos são seleções visuais limitadas.
```

Primeira célula de código — configuração:

```python
from pathlib import Path
import importlib
import temporal_visualizacoes
importlib.reload(temporal_visualizacoes)

PROJETO_VISTAS_TEMPORAIS = Path.cwd()
EXECUTAR_VISTAS_TEMPORAIS = False
MAX_NOS_VISTA_TEMPORAL = 100
MAX_PARES_VISTA_TEMPORAL = 250
ASSINATURA_SERIE_VISTAS = (
    'c0880039218fbbcc0175a7670472ccc760a9efff0e7d5f64208eaddbde977426'
)
ASSINATURA_PROTAGONISMO_VISTAS = (
    'eabe8076fc0c5c7cb10bb5e0c50fa90e5478e74a3522fe8d1e89ba30f7c24491'
)
```

Segunda célula de código — geração:

```python
resumo_vistas_temporais = temporal_visualizacoes.gerar_visualizacoes_temporais(
    PROJETO_VISTAS_TEMPORAIS,
    executar=EXECUTAR_VISTAS_TEMPORAIS,
    max_nos=MAX_NOS_VISTA_TEMPORAL,
    max_pares=MAX_PARES_VISTA_TEMPORAL,
    assinatura_temporal_esperada=ASSINATURA_SERIE_VISTAS,
    assinatura_protagonismo_esperada=ASSINATURA_PROTAGONISMO_VISTAS,
)
resumo_vistas_temporais
```

Execute primeiro com False para conferir as entradas. Depois altere para True,
execute a configuração novamente e execute a geração. Abra o arquivo HTML
indicado no console. As redes e análises anteriores permanecem preservadas.
