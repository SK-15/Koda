import os 
from pathlib import Path
from datetime import datetime

class MemoryManager:
    def __init__(self,thread_id: str, workspace_path: str):
        self.thread_id = thread_id
        self.memory_dir = Path(workspace_path) / ".koda_memory"
        self.index_path = self.memory_dir / "memory.md"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
    
    def load_index(self) -> str:
        if not self.index_path.exists():
            return ""
        return self.index_path.read_text()
    
    def write_domain(self,domain:str,content:str):
        domain_path = self.memory_dir / f"{domain}.md"
        domain_path.write_text(content)
        self._update_index(domain)
    
    def read_domain(self,domain:str) -> str:
        domain_path = self.memory_dir / f"{domain}.md"
        if not domain_path.exists():
            return ""
        return domain_path.read_text()
    
    def load_all_domains(self) -> dict:
        result = {}
        for f in self.memory_dir.glob("*.md"):
            if f.name == "memory.md":
                continue
            result[f.stem] = f.read_text()
        return result
    
    def _update_index(self,domain:str):
        existing = self.load_index()
        lines = existing.splitlines() if existing else []

        pointer = f"- [{domain}] ./({domain}.md)"
        lines = [l for l in lines if not l.startswith(f"- [{domain}]")]
        lines.append(pointer)

        timestamp = f"\n## last-updated\n{datetime.utcnow().isoformat()}"
        body = "\n".join(lines)
        self.index_path.write_text(f"# memory.md — {self.thread_id}\n\n## pointers\n{body}{timestamp}")