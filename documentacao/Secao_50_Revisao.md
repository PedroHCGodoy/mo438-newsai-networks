# Acrescentar após a seção 49 — revisão das pendências 1, 3 e 5

Não substitua a seção 49. O painel temporal v3 permanece como padrão aprovado. Esta etapa produz auditorias e figuras estáticas de verificação; não redesenha a interface interativa.

Célula Markdown:

```markdown
## 50. Revisão das partições, do ajuste de 2012 e das visualizações previstas

A revisão usa apenas os resultados persistidos. Reconfere a conectividade
interna das partições por referências independentes, compara os IDs com
os checkpoints da detecção e reproduz numericamente o ajuste lognormal
salvo para 2012. A causa de eventuais desconexões do GDS não é atribuída
sem reprodução no ambiente local.

Também gera o subgrafo induzido das 50 entidades por força global e
visualizações da maior componente completa, com as partições originais.
Os rótulos de relação e as identidades são preservados. O grupo CNN e
a rede conjunta de 2025 não são revisados nesta etapa.
```

Configuração:

```python
from pathlib import Path
import importlib
import revisao_pendencias
importlib.reload(revisao_pendencias)

PROJETO_REVISAO = Path.cwd()
EXECUTAR_REVISAO = False
```

Execução:

```python
resumo_revisao = revisao_pendencias.executar_revisao(
    PROJETO_REVISAO, executar=EXECUTAR_REVISAO
)
resumo_revisao
```

Execute com False para conferir o reconhecimento das entradas. Depois altere para True, reexecute a configuração e a execução. Não requer Neo4j ou APIs. As saídas anteriores desta mesma revisão são limpas após concluir e validar o novo ZIP; outras etapas ficam preservadas.

## 50.1. Reprodução local do Leiden global no GDS

A revisão já confirmou que a desconexão está na partição salva. Para investigar a causa no seu Neo4j, execute o bloco abaixo. Ele não seleciona automaticamente uma nova partição nem modifica os resultados oficiais. Requer a projeção `community` global já disponível no catálogo GDS; sua topologia e seus pesos são conferidos integralmente antes das execuções.

```python
import diagnostico_leiden_gds
importlib.reload(diagnostico_leiden_gds)

EXECUTAR_DIAGNOSTICO_LEIDEN_GDS = False
resumo_diagnostico_leiden = diagnostico_leiden_gds.diagnosticar_global(
    PROJETO_REVISAO,
    executar_gds=EXECUTAR_DIAGNOSTICO_LEIDEN_GDS,
)
resumo_diagnostico_leiden
```

Com False, não há conexão nem leitura de credenciais. Com True, usa a configuração Neo4j local do projeto para quatro execuções `stream`: mesma configuração da semente 44; sem IDs consecutivos; com até 30 níveis; com 30 níveis e tolerância menor. Não altera propriedades, banco ou catálogo de projeções. Não executa NER/RE. O ZIP retornado registra versão GDS, configurações, partições, conectividade e ARI/NMI contra a partição salva. As novas partições ficam somente nesse pacote de diagnóstico; as referências oficiais continuam preservadas.

Este diagnóstico GDS não foi executado aqui: o servidor Neo4j está no seu computador. Se a projeção não estiver mais em memória, envie a mensagem de erro antes de reexecutar etapas amplas. Ao concluir, envie o ZIP indicado em resumo_diagnostico_leiden['package']; ele é o próximo insumo para decidir a correção necessária.
