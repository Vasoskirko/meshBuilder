import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

BASE = 'fc044b9a2f7c7408cf664b7fb9e17e12619cb726'
FILES = ('mesh_gui.py', 'bundle_subchannel_builder.py')


def git(*args):
    return subprocess.check_output(['git', *args], text=True)


def digest(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def is_main(node):
    if not isinstance(node, ast.If):
        return False
    for text in ('__name__ == "__main__"', '"__main__" == __name__'):
        if ast.dump(node.test) == ast.dump(ast.parse(text, mode='eval').body):
            return True
    return False


def inventory(source):
    tree = ast.parse(source)
    methods, connections, duplicates = {}, [], []

    def visit(scope, prefix=''):
        counts = Counter(n.name for n in scope if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
        duplicates.extend(prefix + name for name, count in counts.items() if count > 1)
        for node in scope:
            if isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + '.')
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.setdefault(prefix + node.name, []).append(dict(line=node.lineno, signature=ast.unparse(node.args), decorators=[ast.unparse(d) for d in node.decorator_list], returns=ast.unparse(node.returns) if node.returns else None, kind=type(node).__name__, ast_sha256=digest(node)))

    visit(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('connect', 'mpl_connect'):
            connections.append(dict(line=node.lineno, expression=ast.unparse(node)))
    guards = [i for i, node in enumerate(tree.body) if is_main(node)]
    tail = tree.body[guards[0] + 1:] if guards else []
    return dict(methods=methods, duplicate_definitions=duplicates, connections=connections, main_guard_lines=[tree.body[i].lineno for i in guards], after_first_main_guard=[dict(line=n.lineno, kind=type(n).__name__, name=getattr(n, 'name', None), ast_sha256=digest(n)) for n in tail])


def compare(old, new):
    a, b = old['methods'], new['methods']
    before = Counter(c['expression'] for c in old['connections'])
    after = Counter(c['expression'] for c in new['connections'])
    return dict(removed_symbols=sorted(a.keys() - b.keys()), added_symbols=sorted(b.keys() - a.keys()), changed_symbols=sorted(k for k in a.keys() & b.keys() if [{x: y for x, y in v.items() if x != 'line'} for v in a[k]] != [{x: y for x, y in v.items() if x != 'line'} for v in b[k]]), removed_connections=list((before - after).elements()), added_connections=list((after - before).elements()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default=BASE)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--output', default='gui_audit.json')
    args = parser.parse_args()
    base = git('rev-parse', '--verify', args.base + '^{commit}').strip()
    head = git('rev-parse', '--verify', args.head + '^{commit}').strip()
    report = dict(base=base, head=head, scope=list(FILES), limitations=['Static comparison only; no runtime signal verification or semantic certification.', 'Moved definitions and connections appear as removals; review extracted modules separately.', 'Nested functions and dynamically assigned methods are not inventoried as methods.', 'AST hashes ignore formatting and comments, but include docstrings.'], files={})
    for path in FILES:
        old = inventory(git('show', base + ':' + path))
        new = inventory(git('show', head + ':' + path))
        report['files'][path] = dict(baseline=old, current=new, differences=compare(old, new))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for path, data in report['files'].items():
        print(path, json.dumps(data['differences'], ensure_ascii=False))


if __name__ == '__main__':
    main()
