## 25. Revalidação e auditoria das relações

Respostas persistidas são revalidadas localmente. Correções de referências a menções são aplicadas apenas quando constam em um registro de curadoria aprovado e correspondem ao documento e ao prompt registrados. Os arquivos de execução permanecem preservados.

A conclusão técnica é registrada separadamente da avaliação semântica. Alertas de tipos e direção geram uma tabela de inspeção e não provocam exclusão automática. Relações sem alerta continuam sem aprovação semântica formal. Novas sugestões de identificadores permanecem para revisão.

A etapa não utiliza credenciais nem realiza chamadas à API. Execute-a após encerrar os lotes de extração. Os resultados derivados incluem proveniência, histórico das correções e verificações por hash.

```python
from pathlib import Path
from re_posprocessamento import processar_re

resumo_pos_re = processar_re(Path.cwd())
resumo_pos_re
```
