# Seleção de anos na extração de relações

Esta atualização acrescenta `anos` à função `executar`. O recorte controla somente a seleção de chamadas novas no lote. A fila integral, os identificadores, o contrato, os parâmetros de geração, o prompt e o checkpoint são preservados. A normalização dos rótulos permanece na versão 1.1.0.

## Instalação

1. Aguarde o encerramento de qualquer lote ativo e salve o notebook.
2. Faça uma cópia de segurança do `re_execucao.py` atual, por exemplo em `backups/re_execucao_antes_filtro.py`.
3. Copie `re_execucao.py` e `testar_re.py` deste ZIP para a pasta `PROJECT`, aceitando a substituição desses dois arquivos.
4. Reinicie o kernel. Não é necessário reinstalar as seções do notebook. Não substitua os manifestos, a fila, o `.env`, o parser ou os arquivos de execução. A correção local do hash da base preparada permanece válida.

## Configuração: primeiro 1994–2024

Na célula da seção 22, acrescente:

```python
ANOS_RE = list(range(1994, 2025))
```

Para o próximo lote, configure inicialmente:

```python
EXECUTAR_RE = False
LIMITE_RE = 20
TRABALHADORES_RE = 2
```

Substitua a célula da seção 23 por:

```python
resultado_lote_re = executar(
    entradas_re,
    executar_api=EXECUTAR_RE,
    limite=LIMITE_RE,
    trabalhadores=TRABALHADORES_RE,
    provider=PROVEDOR_RE,
    timeout=TIMEOUT_RE,
    anos=ANOS_RE,
)
resultado_lote_re
```

Execute a seção 22 e depois a 23 com `False` para conferir o recorte. Depois altere para `EXECUTAR_RE=True` na seção 22, execute essa célula e a seção 23 para iniciar até 20 chamadas novas com dois trabalhadores.

As seções 22–24 são independentes das células de execução NER. Não execute o notebook inteiro para retomar a RE.

## Depois, somente 2025

Quando terminar os lotes de 1994–2024 e revisar os estados não concluídos, altere a configuração para:

```python
ANOS_RE = [2025]
```

Execute novamente as seções 22 e 23. O mesmo checkpoint será utilizado. O filtro não altera a identidade das requisições nem reenvia notícias já tentadas. Rejeições, respostas parciais ou estados incertos permanecem para inspeção; o esgotamento das notícias inéditas não significa que todas as notícias do recorte tiveram sucesso.

Outros exemplos:

```python
ANOS_RE = [2023, 2024]  # Apenas esses anos.
ANOS_RE = None          # Todos os anos da fila aprovada, sempre anteriores a 2026.
```

Ao esgotar o recorte selecionado, o executor retorna sem iniciar outros anos, mesmo que o limite do lote ainda não tenha sido atingido. As tabelas de progresso continuam mostrando a fila integral, incluindo os anos adiados. O resumo do lote registra `selected_years`.

## Verificações

Em uma célula, execute opcionalmente:

```python
%run testar_re.py
```

Os testes usam dados e transportes simulados, sem rede e sem ler o `.env`. Verificam o filtro em execução paralela, a parada ao fim do recorte, a mudança de anos com o mesmo checkpoint, a preservação do progresso integral e o bloqueio de 2026.
