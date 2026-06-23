import os

def print_kace_banner(subtitle="Klipper Automated Configuration Ecosystem", version="main"):
    os.system('clear' if os.name == 'posix' else 'cls')

    # ANSI Escape Codes
    Y = "\033[93m"  # Yellow
    C = "\033[96m"  # Cyan
    B = "\033[1m"   # Bold
    R = "\033[0m"   # Reset

    raw_logo = [
        "██╗  ██╗ █████╗  ██████╗███████╗",
        "██║ ██╔╝██╔══██╗██╔════╝██╔════╝",
        "█████╔╝ ███████║██║     █████╗  ",
        "██╔═██╗ ██╔══██║██║     ██╔══╝  ",
        "██║  ██╗██║  ██║╚██████╗███████╗",
        "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝"
    ]

    print("")
    max_len = max(len(l) for l in raw_logo)
    c1 = (46, 204, 113) # Vibrant Green
    c2 = (52, 152, 219) # Vibrant Blue
    
    for line in raw_logo:
        colored_line = ""
        for i, char in enumerate(line):
            ratio = i / max(1, max_len - 1)
            r = int(c1[0] + (c2[0] - c1[0]) * ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * ratio)
            colored_line += f"\033[38;2;{r};{g};{b}m{char}"
        print(f"  {colored_line}\033[0m")
    
    print(f"  {C}──────────────────────────────────────────{R}")
    if subtitle:
        print(f"  {B}{C}{subtitle}{R}")
    if version:
        padding = " " * max(0, 42 - len(version))
        print(f"  {Y}{padding}{version}{R}")
    print("")

if __name__ == '__main__':
    import sys
    subtitle = "Klipper Automated Configuration Ecosystem"
    version = "main"
    if len(sys.argv) > 1:
        subtitle = sys.argv[1]
    if len(sys.argv) > 2:
        version = sys.argv[2]
    print_kace_banner(subtitle, version)
