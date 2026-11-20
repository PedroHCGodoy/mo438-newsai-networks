# Configuração e execução da extração de relações

## Seção 22 — Entradas e parâmetros

```python
from pathlib import Path
from re_execucao import carregar_entradas, executar, exportar

PROJETO_RE = Path.cwd()
PROVEDOR_RE = 'deepinfra'  # 'deepinfra' ou 'google'.
EXECUTAR_RE = False       # False: conferência local; True: chamadas à API.
LIMITE_RE = 1
TRABALHADORES_RE = 1
TIMEOUT_RE = 360
ANOS_RE = list(range(1994, 2025))  # 1994 a 2024; para 2025: [2025].
RETENTAR_REQUISICOES = []

entradas_re = carregar_entradas(PROJETO_RE)
print(f"Entradas conferidas: {len(entradas_re['queue']):,} notícias anteriores a 2026.")
print(entradas_re['queue'].groupby('re_processing_type').size().to_string())
```

## Seção 23 — Avanço do lote

```python
resultado_lote_re = executar(
    entradas_re,
    executar_api=EXECUTAR_RE,
    limite=LIMITE_RE,
    trabalhadores=TRABALHADORES_RE,
    provider=PROVEDOR_RE,
    timeout=TIMEOUT_RE,
    anos=ANOS_RE,
    retentar_requisicoes=RETENTAR_REQUISICOES,
)
resultado_lote_re
```

`LIMITE_RE` limita novas chamadas, incluindo novas tentativas explicitamente autorizadas. O recorte anual é aplicado antes da seleção; notícias de outros anos não completam o lote.

O provedor seleciona seu modelo e sua variável de credencial:

| PROVEDOR_RE | Variável no .env | Modelo |
|---|---|---|
| `google` | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| `deepinfra` | `DEEPINFRA_API_KEY` | `google/gemini-2.5-flash` |

`KEY_NAME` é um apelido para o console. Não seleciona provedor, modelo ou credencial. Após editar o `.env`, a próxima execução lê as credenciais novamente.

As instruções fixas, a montagem do prompt, o parser e a normalização dos rótulos são comuns aos provedores. Os parâmetros de transporte seguem o contrato específico de cada serviço. A troca de serviço não implica respostas idênticas; o provedor e o modelo permanecem registrados em cada tentativa.

## Retomada e histórico

A fila aprovada, o checkpoint e os artefatos persistidos determinam a retomada. A notícia e sua versão permanecem protegidas independentemente do provedor; o identificador técnico de requisição inclui o contrato do provedor. Notícias já excluídas da fila por possuírem resultados reaproveitáveis continuam excluídas.

Uma tentativa anterior em `SUCCESS`, `SUCCESS_ZERO`, `PARTIAL`, `INVALID_RESPONSE` ou `UNCERTAIN` não é reenviada automaticamente. Erros HTTP também ficam protegidos. Uma resposta persistida de uma tentativa `RUNNING` é recuperada com o contrato original; sem resposta salva, a tentativa passa a `UNCERTAIN`, sem nova chamada.

`RETENTAR_REQUISICOES` aceita identificadores completos de requisições para autorizar nova tentativa **apenas** quando o envelope salvo confirma HTTP 400 com `API_KEY_INVALID`. Não libera timeouts, outros erros, resultados parciais nem notícias concluídas. A autorização não causa repetição dentro do mesmo lote. Quando a notícia recebe uma tentativa posterior, os identificadores anteriores deixam de autorizar novos reenvios dessa notícia, salvo se uma nova falha de chave ocorrer com o mesmo identificador no mesmo provedor. Remova as autorizações depois de resolver os casos.

As tentativas são registradas no SQLite e em `resultados/tabelas/re/tentativas_re.csv`, incluindo identificador da tentativa, notícia, versão, provedor, modelo, estado e identidade completa da requisição. Respostas ficam separadas por requisição e tentativa. Validações substituídas pelo mesmo identificador são preservadas em `historico_validacoes`. Exportação e pós-processamento selecionam uma tentativa efetiva por notícia, evitando somar relações de tentativas anteriores.

A primeira execução sobre um checkpoint no formato anterior cria uma cópia SQLite consistente em `dados/processados/re/execucao/backups/` antes de adicionar o registro de tentativas. A atualização é idempotente. Ausência de checkpoint com respostas existentes bloqueia novos envios; restaure o checkpoint antes de continuar. Não remova o checkpoint, respostas, requisições, prompts ou contrato para trocar de provedor.

## Verificações locais opcionais

Na pasta do projeto:

```python
import subprocess
import sys
subprocess.run([sys.executable, 'testar_re_provedores.py'], check=True)
subprocess.run([sys.executable, 'testar_re.py'], check=True)
subprocess.run([sys.executable, 'testar_re_posprocessamento.py'], check=True)
```

Os testes usam notícias sintéticas e transportes simulados; não leem chaves nem chamam APIs. Após reiniciar o kernel, execute as seções 22 e 23 para retomar a RE; as etapas de NER não precisam ser reexecutadas.
