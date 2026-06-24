import asyncio
import os


async def run_in_sandbox(command: str, workspace_path: str, timeout: int = 30) -> tuple[str, str, int]:
    abs_workspace = os.path.abspath(workspace_path)

    docker_cmd = [
        "docker", "run",
        "--rm",
        "--network", "none",
        "--memory", "256m",
        "--cpus", "0.5",
        "--read-only",
        "--tmpfs", "/tmp:size=64m",
        "-v", f"{abs_workspace}:/workspace:ro",
        "-w", "/workspace",
        "python:3.11-slim",
        "bash", "-c", command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

        return (
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            proc.returncode,
        )

    except asyncio.TimeoutError:
        proc.kill()
        return "", f"Timed out after {timeout}s", 1

    except Exception as e:
        return "", f"Sandbox error: {str(e)}", 1