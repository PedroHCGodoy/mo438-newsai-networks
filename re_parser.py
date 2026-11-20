"""Leitura e recuperação auditável das respostas de extração de relações."""

import json, re

from typing import Any, Dict, List, Optional, Tuple

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

def _strip_json_code_fences(s: str) -> str:
    """
    Remove fences markdown externas do tipo ```json ... ```.

    Se não houver fences, apenas aplica strip().
    """
    m = _JSON_FENCE_RE.search(s or '')
    return m.group(1).strip() if m else (s or '').strip()

def _try_json_load(s: str):
    """
    Tenta desserializar JSON sem propagar exceção.
    """
    try:
        return json.loads(s)
    except Exception:
        return None

def _extract_first_json_array(s: str) -> Optional[str]:
    """
    Extrai o primeiro array JSON balanceado [ ... ] do texto.

    Estratégia:
    - localiza o primeiro '[';
    - percorre o texto controlando profundidade;
    - respeita strings JSON e escapes.

    Retorna None se não encontrar um array completo.
    """
    start = s.find('[')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None

def _extract_first_json_object(s: str) -> Optional[str]:
    """
    Extrai o primeiro objeto JSON balanceado { ... } do texto.

    Retorna None se não encontrar um objeto completo.
    """
    start = s.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None

def _normalize_prediction_item_entities_only(item: Any) -> Tuple[Optional[Dict[str, str]], str]:
    """
    Normaliza 1 item de predição para o schema mínimo esperado no protocolo
    entities-only.

    Campos aceitos:
    - head_id
    - tail_id
    - label

    Retorna None quando o item não atende ao schema mínimo.
    """
    if not isinstance(item, dict):
        return (None, 'item_not_dict')
    head_id = str(item.get('head_id', '')).strip()
    tail_id = str(item.get('tail_id', '')).strip()
    label = str(item.get('label', '')).strip()
    if not head_id and 'head' in item:
        return (None, 'used_head_instead_of_head_id')
    if not tail_id and 'tail' in item:
        return (None, 'used_tail_instead_of_tail_id')
    if not label and 'relation' in item:
        return (None, 'used_relation_instead_of_label')
    if not head_id:
        return (None, 'missing_head_id')
    if not tail_id:
        return (None, 'missing_tail_id')
    if not label:
        return (None, 'missing_label')
    return ({'head_id': head_id, 'tail_id': tail_id, 'label': label}, 'ok')

def _parse_predictions_from_data_entities_only(data: Any) -> Tuple[bool, List[Dict[str, str]], Dict[str, int]]:
    """
    Converte um payload Python já desserializado em lista de predições.

    Formatos aceitos:
    1) lista direta:
       [
         {"head_id":"E1","tail_id":"E2","label":"ident"},
         ...
       ]

    2) objeto com chave "predictions":
       {
         "docid":"aa56088",
         "predictions":[...]
       }

    3) objeto com chave "relations":
       {
         "docid":"aa56088",
         "relations":[...]
       }

    A função:
    - normaliza itens;
    - remove duplicatas por (head_id, tail_id, label);
    - conta inválidos e duplicados.
    """
    if isinstance(data, list):
        preds = data
        payload_ok = True
    elif isinstance(data, dict) and isinstance(data.get('predictions'), list):
        preds = data['predictions']
        payload_ok = True
    elif isinstance(data, dict) and isinstance(data.get('relations'), list):
        preds = data['relations']
        payload_ok = True
    else:
        return (False, [], {'items_valid': 0, 'items_invalid': 0, 'items_duplicate': 0})
    out = []
    seen = set()
    items_invalid = 0
    items_duplicate = 0
    invalid_reasons = {}
    for it in preds:
        norm, norm_reason = _normalize_prediction_item_entities_only(it)
        if norm is None:
            items_invalid += 1
            invalid_reasons[norm_reason] = invalid_reasons.get(norm_reason, 0) + 1
            continue
        key = (norm['head_id'], norm['tail_id'], norm['label'])
        if key in seen:
            items_duplicate += 1
            continue
        seen.add(key)
        out.append(norm)
    return (payload_ok, out, {'items_valid': len(out), 'items_invalid': items_invalid, 'items_duplicate': items_duplicate, 'invalid_reasons': invalid_reasons})

def _recover_complete_objects_from_truncated_json_array_entities_only(s: str) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """
    Recupera objetos completos de um array JSON truncado.

    Cenário-alvo:
    o LLM devolve um array válido, mas a saída foi interrompida
    antes do fechamento do array ou do último objeto.

    Estratégia:
    - localiza o primeiro '[';
    - percorre o texto controlando strings, escapes e profundidade de chaves;
    - sempre que um objeto JSON completo fechar em nível de array, tentar
      parseá-lo isoladamente;
    - ignora o fragmento final incompleto.
    """
    s = _strip_json_code_fences(s)
    arr_start = s.find('[')
    if arr_start == -1:
        return ([], {'items_valid': 0, 'items_invalid': 0, 'items_duplicate': 0})
    objs: List[Dict[str, str]] = []
    in_string = False
    escape = False
    brace_depth = 0
    obj_start = None
    items_invalid = 0
    for i in range(arr_start, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '{':
            if brace_depth == 0:
                obj_start = i
            brace_depth += 1
            continue
        if ch == '}':
            if brace_depth > 0:
                brace_depth -= 1
                if brace_depth == 0 and obj_start is not None:
                    candidate = s[obj_start:i + 1]
                    parsed = _try_json_load(candidate)
                    norm, norm_reason = _normalize_prediction_item_entities_only(parsed)
                    if norm is not None:
                        objs.append(norm)
                    else:
                        items_invalid += 1
                    obj_start = None
            continue
    out: List[Dict[str, str]] = []
    seen = set()
    items_duplicate = 0
    for x in objs:
        key = (x['head_id'], x['tail_id'], x['label'])
        if key in seen:
            items_duplicate += 1
            continue
        seen.add(key)
        out.append(x)
    return (out, {'items_valid': len(out), 'items_invalid': items_invalid, 'items_duplicate': items_duplicate})

def parse_llm_doclevel_relations_json(raw_text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parser auditável para a resposta do LLM.

    Ordem das tentativas:
    1. parse direto do texto sem fences;
    2. extração de array JSON completo do texto;
    3. extração de objeto JSON completo do texto;
    4. recuperação parcial de objetos válidos em array truncado;
    5. falha total com diagnóstico.

    Metadados retornados:
    - parse_ok
    - parse_mode
    - partial_recovered
    - parse_failure_reason
    - items_valid
    - items_invalid
    - items_duplicate
    - raw_len
    - raw_has_code_fence
    - raw_starts_with_array
    - raw_ends_with_closing_bracket
    """
    raw_text = raw_text or ''
    raw_clean = raw_text.strip()
    raw_has_code_fence = '```' in raw_text
    raw_starts_with_array = raw_clean.startswith('[')
    raw_ends_with_closing_bracket = raw_clean.endswith(']')
    base_meta = {'parse_ok': False, 'parse_mode': 'failed', 'partial_recovered': False, 'parse_failure_reason': 'unknown_failure', 'items_valid': 0, 'items_invalid': 0, 'items_duplicate': 0, 'raw_len': len(raw_text), 'raw_has_code_fence': raw_has_code_fence, 'raw_starts_with_array': raw_starts_with_array, 'raw_ends_with_closing_bracket': raw_ends_with_closing_bracket}
    s = _strip_json_code_fences(raw_text)
    data = _try_json_load(s)
    payload_ok, preds, stats = _parse_predictions_from_data_entities_only(data)
    if payload_ok:
        meta = dict(base_meta)
        meta.update({'parse_ok': True, 'parse_mode': 'direct_json', 'partial_recovered': False, 'parse_failure_reason': None, 'items_valid': stats['items_valid'], 'items_invalid': stats['items_invalid'], 'items_duplicate': stats['items_duplicate'], 'invalid_reasons': stats.get('invalid_reasons', {})})
        return (preds, meta)
    arr_txt = _extract_first_json_array(s)
    if arr_txt is not None:
        data = _try_json_load(arr_txt)
        payload_ok, preds, stats = _parse_predictions_from_data_entities_only(data)
        if payload_ok:
            meta = dict(base_meta)
            meta.update({'parse_ok': True, 'parse_mode': 'extracted_array', 'partial_recovered': False, 'parse_failure_reason': None, 'items_valid': stats['items_valid'], 'items_invalid': stats['items_invalid'], 'items_duplicate': stats['items_duplicate']})
            return (preds, meta)
    obj_txt = _extract_first_json_object(s)
    if obj_txt is not None:
        data = _try_json_load(obj_txt)
        payload_ok, preds, stats = _parse_predictions_from_data_entities_only(data)
        if payload_ok:
            meta = dict(base_meta)
            meta.update({'parse_ok': True, 'parse_mode': 'extracted_object', 'partial_recovered': False, 'parse_failure_reason': None, 'items_valid': stats['items_valid'], 'items_invalid': stats['items_invalid'], 'items_duplicate': stats['items_duplicate']})
            return (preds, meta)
    preds, stats = _recover_complete_objects_from_truncated_json_array_entities_only(s)
    if preds:
        meta = dict(base_meta)
        meta.update({'parse_ok': True, 'parse_mode': 'partial_truncated_array_recovery', 'partial_recovered': True, 'parse_failure_reason': None, 'items_valid': stats['items_valid'], 'items_invalid': stats['items_invalid'], 'items_duplicate': stats['items_duplicate']})
        return (preds, meta)
    if not raw_clean:
        failure_reason = 'empty_response'
    elif raw_starts_with_array and (not raw_ends_with_closing_bracket):
        failure_reason = 'truncated_json_array'
    elif raw_clean.startswith('{') and ('predictions' not in raw_clean and 'relations' not in raw_clean):
        failure_reason = 'json_object_without_predictions_or_relations'
    elif raw_has_code_fence:
        failure_reason = 'json_inside_fence_not_parseable'
    else:
        failure_reason = 'unparseable_response'
    meta = dict(base_meta)
    meta['parse_failure_reason'] = failure_reason
    return ([], meta)
