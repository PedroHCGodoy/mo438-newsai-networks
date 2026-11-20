"""Adiciona a seção de RE ao notebook, preservando as células existentes."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import shutil
import uuid


def instalar(projeto=None):
    root = Path(projeto or Path.cwd()).resolve()
    path = root/'Pipeline_Noticias_IA.ipynb'
    notebook = json.loads(path.read_text(encoding='utf-8'))
    tag = 'extracao-relacoes-documental-v1'
    if any(tag in cell.get('metadata',{}).get('tags',[]) for cell in notebook['cells']):
        print('A seção de RE já está instalada. Nenhuma alteração realizada.')
        return path
    cells = json.loads((root/'secao_re.json').read_text(encoding='utf-8'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    backup = root/'backups'/('Pipeline_Noticias_IA_'+stamp+'.ipynb')
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,backup)
    for cell in cells:
        cell.setdefault('metadata',{}).setdefault('tags',[]).append(tag)
    notebook['cells'].extend(cells)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    print('Seção de RE adicionada. Backup:',backup)
    print('Feche o notebook sem salvar a aba antiga e abra-o novamente para carregar as novas células.')
    return path
