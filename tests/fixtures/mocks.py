# tests/fixtures/mocks.py
import os
import tempfile

_WRAPPER_DIR_OBJ = None

def get_compiler_wrapper_path() -> str:
    """Create a temporary compiler wrapper directory that filters out LTO flags, and return its path."""
    global _WRAPPER_DIR_OBJ
    if _WRAPPER_DIR_OBJ is None:
        _WRAPPER_DIR_OBJ = tempfile.TemporaryDirectory(prefix="kace_cc_wrapper_")
        w_dir = _WRAPPER_DIR_OBJ.name
        
        wrapper_code = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "import os\n"
            "import subprocess\n"
            "\n"
            "def main():\n"
            "    cmd_name = os.path.basename(sys.argv[0])\n"
            "    wrapper_dir = os.path.dirname(os.path.abspath(sys.argv[0]))\n"
            "    real_compiler = None\n"
            "    paths = os.environ.get('PATH', '').split(os.pathsep)\n"
            "    for p in paths:\n"
            "        if not p:\n"
            "            continue\n"
            "        abs_p = os.path.abspath(p)\n"
            "        if abs_p == wrapper_dir:\n"
            "            continue\n"
            "        candidate = os.path.join(p, cmd_name)\n"
            "        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):\n"
            "            real_compiler = candidate\n"
            "            break\n"
            "    if not real_compiler:\n"
            "        sys.exit(f'Compiler wrapper error: Could not find real {cmd_name} in PATH')\n"
            "    args = sys.argv[1:]\n"
            "    filtered_args = []\n"
            "    for arg in args:\n"
            "        if arg.startswith('-flto') or arg == '-fwhole-program' or arg == '-fno-use-linker-plugin':\n"
            "            continue\n"
            "        filtered_args.append(arg)\n"
            "    res = subprocess.run([real_compiler] + filtered_args)\n"
            "    sys.exit(res.returncode)\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        
        for comp in ["arm-none-eabi-gcc", "avr-gcc"]:
            wrapper_path = os.path.join(w_dir, comp)
            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(wrapper_code)
            os.chmod(wrapper_path, 0o755)
            
    return _WRAPPER_DIR_OBJ.name

def clean_compiler_wrapper() -> None:
    """Clean up the compiler wrapper temporary directory."""
    global _WRAPPER_DIR_OBJ
    if _WRAPPER_DIR_OBJ is not None:
        try:
            _WRAPPER_DIR_OBJ.cleanup()
        except Exception:
            pass
        _WRAPPER_DIR_OBJ = None
