#!/usr/bin/env python3
import sys
import os
import subprocess

def main():
    cmd_name = os.path.basename(sys.argv[0])
    wrapper_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    real_compiler = None
    paths = os.environ.get('PATH', '').split(os.pathsep)
    for p in paths:
        if not p:
            continue
        abs_p = os.path.abspath(p)
        if abs_p == wrapper_dir:
            continue
        candidate = os.path.join(p, cmd_name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            real_compiler = candidate
            break
    if not real_compiler:
        sys.exit(f'Compiler wrapper error: Could not find real {cmd_name} in PATH')
    args = sys.argv[1:]
    filtered_args = []
    for arg in args:
        if arg.startswith('-flto') or arg == '-fwhole-program' or arg == '-fno-use-linker-plugin':
            continue
        filtered_args.append(arg)
    res = subprocess.run([real_compiler] + filtered_args)
    sys.exit(res.returncode)

if __name__ == '__main__':
    main()
