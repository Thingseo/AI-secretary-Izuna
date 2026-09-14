"""Bundled MCP filesystem service, restricted to one explicitly selected directory.

No shell, deletion, overwrites, links or binary-content extraction. UTF-8 text only.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

TEXT = {'.txt', '.md', '.csv', '.json', '.log', '.py', '.html', '.css', '.xml', '.yaml', '.yml'}

class FolderTools:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.snapshots = {}
        self.check(self.root)
        if not self.root.is_dir(): raise ValueError('폴더가 아닙니다.')

    def check(self, path):
        for part in [path, *path.parents]:
            if part.exists() or part.is_symlink():
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('링크·정션 접근은 허용하지 않습니다.')
                if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                    raise ValueError('하드링크 접근은 허용하지 않습니다.')

    def path(self, name):
        if not isinstance(name, str) or not name or len(name) > 220: raise ValueError('상대 경로를 입력하세요.')
        name = name.replace('\\', '/')
        parts = name.split('/')
        for part in parts:
            if part in ('', '.', '..') or part.startswith('.') or part.endswith((' ', '.')) or re.search(r'[:<>"|?*\x00-\x1f]', part):
                raise ValueError('허용되지 않은 경로입니다.')
            if part.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]}:
                raise ValueError('예약된 파일 이름입니다.')
        path = self.root.joinpath(*parts)
        self.check(path)
        if not path.resolve().is_relative_to(self.root.resolve()): raise ValueError('선택한 폴더 밖입니다.')
        return path

    def digest(self, path):
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024: raise ValueError('일반 파일·20MB 이하만 이동할 수 있습니다.')
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def listing(self, directory=''):
        folder = self.path(directory) if directory else self.root
        self.check(folder)
        result=[]
        for p in sorted(folder.iterdir()):
            if len(result) >= 150: raise ValueError('폴더당 150개 이하로 나눠 주세요.')
            if p.name.startswith('.'): continue
            name = p.relative_to(self.root).as_posix()
            try:
                self.path(name)
                if p.is_file(): self.snapshots[name] = self.digest(p)
                elif not p.is_dir(): continue
                result.append(dict(path=name, kind='folder' if p.is_dir() else 'file', bytes=p.stat().st_size if p.is_file() else None))
            except (ValueError, OSError): result.append(dict(path=name, kind='blocked'))
        return result

    def read(self, name):
        p=self.path(name)
        if p.suffix.lower() not in TEXT or p.stat().st_size > 64000: raise ValueError('64KB 이하 UTF-8 텍스트만 읽을 수 있습니다. 사진·PDF·Office 내용은 지원하지 않습니다.')
        value=p.read_text(encoding='utf-8-sig')
        if '\x00' in value: raise ValueError('바이너리 파일입니다.')
        self.snapshots[name] = self.digest(p)
        return value

    def prepare(self, moves, writes):
        if not isinstance(moves,list) or not isinstance(writes,list) or not 1 <= len(moves)+len(writes) <= 50:
            raise ValueError('변경은 1~50개만 가능합니다.')
        sources=[]; destinations=[]; prepared=[]
        for move in moves:
            source=self.path(move['source']); dest=self.path(move['destination'])
            if move['source'] not in self.snapshots or self.digest(source) != self.snapshots[move['source']]:
                raise ValueError('파일이 바뀌었거나 목록을 조회하지 않았습니다. 다시 확인하세요.')
            sources.append(source); destinations.append(dest); prepared.append(('move',source,dest))
        for write in writes:
            dest=self.path(write['path']); content=write['content']
            if dest.suffix.lower() not in {'.txt','.md'} or not isinstance(content,str) or len(content.encode('utf-8'))>64000:
                raise ValueError('새 텍스트·마크다운 파일은 64KB 이하만 가능합니다.')
            destinations.append(dest); prepared.append(('write',content,dest))
        if len(set(sources)) != len(sources) or len(set(destinations)) != len(destinations): raise ValueError('중복 경로입니다.')
        for dest in destinations:
            if dest.exists(): raise ValueError('기존 파일을 덮어쓰지 않습니다: '+dest.name)
            if any(p in destinations or p in sources for p in dest.parents): raise ValueError('파일과 폴더 경로가 충돌합니다.')
        return prepared

    def apply(self, moves, writes):
        prepared=self.prepare(moves,writes)
        completed=[]; created=[]
        try:
            for kind, source, dest in prepared:
                self.check(dest)
                missing=[]; parent=dest.parent
                while not parent.exists(): missing.append(parent); parent=parent.parent
                for parent in reversed(missing): parent.mkdir(); created.append(parent)
                if kind=='move':
                    self.check(source)
                    if self.digest(source) != self.snapshots[source.relative_to(self.root).as_posix()]: raise ValueError('실행 중 원본이 변경됐습니다.')
                    # Exclusive creation prevents a collision from overwriting a file.
                    os.link(source, dest, follow_symlinks=False)
                    completed.append((kind,source,dest))
                    source.unlink()
                else:
                    with dest.open('x',encoding='utf-8') as out:
                        completed.append((kind,None,dest)); out.write(source)
            return dict(completed=[str(d.relative_to(self.root)) for _,_,d in completed])
        except Exception:
            for kind, source, dest in reversed(completed):
                if kind=='move' and not source.exists():
                    os.link(dest, source, follow_symlinks=False)
                dest.unlink(missing_ok=True)
            for folder in reversed(created): folder.rmdir()
            raise

TOOLS=[
    dict(name='list_directory',description='선택 폴더의 상대 경로 목록',inputSchema={'type':'object','properties':{'directory':{'type':'string'}}}),
    dict(name='read_text',description='UTF-8 텍스트 읽기. 이미지·PDF·Office는 읽을 수 없음',inputSchema={'type':'object','properties':{'path':{'type':'string'}},'required':['path']}),
    dict(name='apply_plan',description='사용자가 승인한 파일 이동과 새 텍스트 작성 계획 실행',inputSchema={'type':'object','properties':{'moves':{'type':'array'},'writes':{'type':'array'}},'required':['moves','writes']})]

def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    service=FolderTools(sys.argv[1])
    for line in sys.stdin:
        try:
            req=json.loads(line)
            if 'id' not in req: continue
            method=req.get('method'); args=req.get('params',{})
            if method=='initialize': result=dict(protocolVersion='2025-06-18',capabilities={'tools':{}},serverInfo={'name':'Izuna folder tools','version':'1'})
            elif method=='tools/list': result={'tools':TOOLS}
            elif method=='tools/call':
                name=args['name']; arg=args.get('arguments',{})
                if name=='list_directory': value=service.listing(arg.get('directory',''))
                elif name=='read_text': value=service.read(arg['path'])
                elif name=='apply_plan': value=service.apply(arg['moves'],arg['writes'])
                else: raise ValueError('지원하지 않는 도구')
                result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
            else: raise ValueError('지원하지 않는 요청')
        except Exception as exc:
            result={'content':[{'type':'text','text':str(exc)}],'isError':True}
        if isinstance(locals().get('req'),dict) and 'id' in req:
            print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
