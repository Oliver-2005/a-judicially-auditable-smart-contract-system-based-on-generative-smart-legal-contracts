import os
import json
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

class SLCMLCompiler:
    def __init__(self, template_dir, output_dir):
        self.env = Environment(loader=FileSystemLoader(template_dir))
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile(self, extraction_data, output_filename):
        template = self.env.get_template("ContractTemplate.sol.j2")
        
        # Simplified mapping for first demo
        # In a real scenario, we'd parse the complex JSON structure thoroughly
        context = {
            "dataOwner": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", # Default Hardhat Account 0
            "modelProvider": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8", # Default Hardhat Account 1
            "bTotal": 1000 * 10**18, # 1000 Privacy Units
            "deposit": 10 * 10**18  # 10 ETH equivalent in units
        }
        
        rendered = template.render(**context)
        with open(self.output_dir / output_filename, "w", encoding="utf-8") as f:
            f.write(rendered)
        print(f"Contract compiled and saved to {self.output_dir / output_filename}")

if __name__ == "__main__":
    # Test with a dummy extraction result
    PROJECT_ROOT = Path(r"")
    compiler = SLCMLCompiler(
        template_dir=str(PROJECT_ROOT / "compiler" / "templates"),
        output_dir=str(PROJECT_ROOT / "hardhat_sim_v2" / "contracts")
    )
    
    # Load one of the high-quality extractions
    extraction_file = PROJECT_ROOT / "data" / "llm_outputs" / "raw_extractions" / "SLCML-GPT-5_1.《数据提供合同（示范文本）》（GF-2025-2615）.json"
    
    if extraction_file.exists():
        with open(extraction_file, "r", encoding="utf-8") as f:
            # Handle potential <think> tags if they are still there
            content = f.read()
            if "</think>" in content:
                json_str = content.split("</think>")[-1].strip()
            else:
                json_str = content
            data = json.loads(json_str)
            
        compiler.compile(data, "SLCML_Contract_Demo.sol")
    else:
        print(f"Extraction file not found for compilation: {extraction_file}")
