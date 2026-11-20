# 48. Grau anterior e aquisição de novos vizinhos

Copie o bloco abaixo para uma célula Markdown do notebook:

```markdown
## 48. Grau anterior e aquisição de novos vizinhos

Investigamos se entidades já presentes com maior grau em um corte acumulado
adquirem mais vizinhos no ano seguinte. A análise considera 31 transições
anuais da Folha de S.Paulo, de 1994→1995 até 2024→2025. O estoque de 1994
não é contado como ganho; entrantes são auditados separadamente. Todos os
nós anteriores são incluídos, mesmo com ganho zero.

As associações são descritivas, com empates preservados no cálculo dos
postos. A análise distingue novos vizinhos de reforço de pares existentes,
compara faixas de grau e contextualiza tipo de entidade, idade na rede,
exposição documental e cobertura de extração. As referências uniforme e
proporcional ao grau são alocações algébricas, sem simulação de redes.
Os estudos dos casos mantêm IDs e tipos canônicos e permitem consultar as
notícias de origem. Padrões positivos são compatíveis com vantagem
cumulativa observada, sem demonstrar causalidade ou Efeito Mateus.
```

Primeira célula de código — configuração:

```python
from pathlib import Path
import importlib
import temporal_vantagem
importlib.reload(temporal_vantagem)

PROJETO_VANTAGEM = Path.cwd()
EXECUTAR_VANTAGEM = False
ASSINATURA_PROTAGONISMO_VANTAGEM = (
    'eabe8076fc0c5c7cb10bb5e0c50fa90e5478e74a3522fe8d1e89ba30f7c24491'
)
```

Segunda célula de código — análise:

```python
resumo_vantagem = temporal_vantagem.analisar_vantagem_cumulativa(
    PROJETO_VANTAGEM,
    executar=EXECUTAR_VANTAGEM,
    assinatura_protagonismo_esperada=ASSINATURA_PROTAGONISMO_VANTAGEM,
)
resumo_vantagem
```

Comece com False para conferir as entradas. Para calcular, altere para True,
execute novamente a célula de configuração e depois a célula de análise.
Não há chamadas à API, conexão com Neo4j ou alterações na rede.
