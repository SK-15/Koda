import re

BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r">\s*/dev/sd",
    r"mkfs\.",
    r"dd\s+if=",
    r"curl\s+.*\|.*sh",
    r"wget\s+.*\|.*sh",
    r"curl\s+[^|]+--upload-file",
    r"cat\s+.*\.env",
    r"echo\s+\$[A-Z_]+",
    r"env\s*\|\s*grep",
    r"printenv",
    r"export\s+.*KEY",
    r"export\s+.*SECRET",
    r"export\s+.*TOKEN",
    r"nc\s+-",
    r"netcat",
    r"\/etc\/passwd",
    r"\/etc\/shadow",
    r"chmod\s+777",
    r"sudo\s+",
    r"su\s+-",
    r"docker\s+run",
    r"kubectl\s+delete",
]

ALLOWED_COMMANDS = {
    "git", "pytest", "python", "pip", "npm", "npx", "node",
    "ls", "cat", "grep", "find", "sed", "awk", "head", "tail",
    "echo", "pwd", "mkdir", "cp", "mv", "touch", "wc", "sort",
    "curl",  "make", "cargo", "go", "java", "mvn",
}


def validate_bash_command(command: str) -> tuple[bool, str]:
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Blocked pattern detected: {pattern}"

    first_token = command.strip().split()[0] if command.strip() else ""
    base_cmd = first_token.split("/")[-1]

    if base_cmd and base_cmd not in ALLOWED_COMMANDS:
        return False, f"Command not in allowlist: '{base_cmd}'"

    return True, ""