#!/usr/bin/env python3
"""
Configuration management for PAN-OS Multi-Firewall Monitor
"""
import os
import yaml
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    from dotenv import load_dotenv
    DOTENV_OK = True
except ImportError:
    DOTENV_OK = False

LOG = logging.getLogger("panos_monitor.config")

@dataclass
class FirewallConfig:
    """Configuration for a single firewall"""
    name: str
    host: str
    username: str
    password: str
    verify_ssl: bool = True
    enabled: bool = True
    poll_interval: int = 60
    dp_aggregation: str = "mean"  # mean, max, p95

@dataclass
class GlobalConfig:
    """Global configuration settings"""
    output_dir: str = "./output"
    output_type: str = "CSV"  # CSV, XLSX, TXT
    visualization: bool = True
    web_dashboard: bool = True
    web_port: int = 8080
    save_raw_xml: bool = False
    xml_retention_hours: int = 24
    database_path: str = "./data/metrics.db"
    log_level: str = "INFO"

class ConfigManager:
    """Manages configuration for multiple firewalls"""
    
    def __init__(self, config_file: str = "config.yaml"):
        self.config_file = Path(config_file)
        self.global_config = GlobalConfig()
        self.firewalls: Dict[str, FirewallConfig] = {}
        
        # Load environment variables if available
        if DOTENV_OK:
            load_dotenv()
        
        self._load_config()
    
    def _load_config(self):
        """Load configuration from file or environment variables"""
        if self.config_file.exists():
            self._load_from_yaml()
        else:
            self._load_from_env()
            self._create_default_config()
    
    def _load_from_yaml(self):
        """Load configuration from YAML file"""
        try:
            with open(self.config_file, 'r') as f:
                data = yaml.safe_load(f) or {}
            
            # Load global config
            global_data = data.get('global', {})
            for key, value in global_data.items():
                if hasattr(self.global_config, key):
                    setattr(self.global_config, key, value)
            
            # Load firewall configs
            firewalls_data = data.get('firewalls', {})
            for name, fw_data in firewalls_data.items():
                self.firewalls[name] = FirewallConfig(name=name, **fw_data)
                
            LOG.info(f"Loaded configuration for {len(self.firewalls)} firewalls from {self.config_file}")
            
        except Exception as e:
            LOG.error(f"Failed to load config from {self.config_file}: {e}")
            self._load_from_env()
    
    def _load_from_env(self):
        """Load configuration from environment variables (legacy support)"""
        # Global config from env
        self.global_config.output_dir = os.getenv("OUTPUT_DIR", self.global_config.output_dir)
        self.global_config.output_type = os.getenv("OUTPUT_TYPE", self.global_config.output_type)
        self.global_config.visualization = self._env_bool("VISUALIZATION", self.global_config.visualization)
        self.global_config.web_dashboard = self._env_bool("WEB_DASHBOARD", self.global_config.web_dashboard)
        self.global_config.web_port = int(os.getenv("WEB_PORT", str(self.global_config.web_port)))
        self.global_config.save_raw_xml = self._env_bool("SAVE_RAW_XML", self.global_config.save_raw_xml)
        self.global_config.xml_retention_hours = int(os.getenv("XML_RETENTION_HOURS", str(self.global_config.xml_retention_hours)))
        self.global_config.database_path = os.getenv("DATABASE_PATH", self.global_config.database_path)
        self.global_config.log_level = os.getenv("LOG_LEVEL", self.global_config.log_level)
        
        # Single firewall from env (legacy)
        host = os.getenv("PAN_HOST")
        username = os.getenv("PAN_USERNAME")
        password = os.getenv("PAN_PASSWORD")
        
        if host and username and password:
            fw_name = "legacy_firewall"
            self.firewalls[fw_name] = FirewallConfig(
                name=fw_name,
                host=host,
                username=username,
                password=password,
                verify_ssl=self._env_bool("VERIFY_SSL", True),
                poll_interval=int(os.getenv("POLL_INTERVAL", "60")),
                dp_aggregation=os.getenv("DP_AGGREGATION", "mean")
            )
            LOG.info("Loaded legacy firewall configuration from environment variables")
    
    def _env_bool(self, key: str, default: bool) -> bool:
        """Convert environment variable to boolean"""
        val = os.getenv(key)
        if val is None:
            return default
        return str(val).strip().lower() in {"1", "true", "yes", "y"}
    
    def _create_default_config(self):
        """Create a default configuration file"""
        if not self.firewalls:
            # Create example firewall
            self.firewalls["example_fw"] = FirewallConfig(
                name="example_fw",
                host="https://192.168.1.1",
                username="admin",
                password="password",
                enabled=False  # Disabled by default
            )
        
        self.save_config()
        LOG.info(f"Created default configuration file: {self.config_file}")
    
    def save_config(self):
        """Save current configuration to YAML file"""
        data = {
            'global': asdict(self.global_config),
            'firewalls': {name: asdict(fw) for name, fw in self.firewalls.items()}
        }
        
        # Ensure config directory exists
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_file, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)
        
        LOG.info(f"Configuration saved to {self.config_file}")
    
    def add_firewall(self, config: FirewallConfig) -> bool:
        """Add a new firewall configuration"""
        if config.name in self.firewalls:
            LOG.warning(f"Firewall {config.name} already exists, updating configuration")
        
        self.firewalls[config.name] = config
        self.save_config()
        return True
    
    def remove_firewall(self, name: str) -> bool:
        """Remove a firewall configuration"""
        if name in self.firewalls:
            del self.firewalls[name]
            self.save_config()
            LOG.info(f"Removed firewall configuration: {name}")
            return True
        return False
    
    def get_enabled_firewalls(self) -> Dict[str, FirewallConfig]:
        """Get all enabled firewall configurations"""
        return {name: fw for name, fw in self.firewalls.items() if fw.enabled}
    
    def get_firewall(self, name: str) -> Optional[FirewallConfig]:
        """Get specific firewall configuration"""
        return self.firewalls.get(name)
    
    def list_firewalls(self) -> List[str]:
        """List all firewall names"""
        return list(self.firewalls.keys())
    
    def validate_config(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        # Validate global config
        if self.global_config.web_port < 1 or self.global_config.web_port > 65535:
            errors.append("Invalid web_port: must be between 1-65535")
        
        if self.global_config.output_type not in ["CSV", "XLSX", "TXT"]:
            errors.append("Invalid output_type: must be CSV, XLSX, or TXT")
        
        # Validate firewall configs
        for name, fw in self.firewalls.items():
            if not fw.host:
                errors.append(f"Firewall {name}: host is required")
            
            if not fw.username or not fw.password:
                errors.append(f"Firewall {name}: username and password are required")
            
            if fw.poll_interval < 1:
                errors.append(f"Firewall {name}: poll_interval must be >= 1")
            
            if fw.dp_aggregation not in ["mean", "max", "p95"]:
                errors.append(f"Firewall {name}: dp_aggregation must be mean, max, or p95")
        
        return errors

def create_example_config() -> str:
    """Create an example configuration file"""
    example_config = """# PAN-OS Multi-Firewall Monitor Configuration

global:
  output_dir: "./output"
  output_type: "CSV"  # CSV, XLSX, TXT
  visualization: true
  web_dashboard: true
  web_port: 8080
  save_raw_xml: false
  xml_retention_hours: 24
  database_path: "./data/metrics.db"
  log_level: "INFO"

firewalls:
  datacenter_fw:
    host: "https://10.100.192.3"
    username: "admin"
    password: "YourPassword"
    verify_ssl: false
    enabled: true
    poll_interval: 60
    dp_aggregation: "mean"  # mean, max, p95
  
  branch_fw:
    host: "https://192.168.1.1"
    username: "admin"
    password: "YourPassword"
    verify_ssl: false
    enabled: true
    poll_interval: 30
    dp_aggregation: "max"
  
  disabled_fw:
    host: "https://192.168.2.1"
    username: "admin"
    password: "YourPassword"
    verify_ssl: false
    enabled: false  # This firewall will not be monitored
    poll_interval: 60
    dp_aggregation: "mean"
"""
    return example_config

if __name__ == "__main__":
    # Example usage
    config_manager = ConfigManager()
    
    # Validate configuration
    errors = config_manager.validate_config()
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("Configuration is valid")
    
    # Print current configuration
    print(f"\nGlobal config: {config_manager.global_config}")
    print(f"Firewalls: {list(config_manager.firewalls.keys())}")
