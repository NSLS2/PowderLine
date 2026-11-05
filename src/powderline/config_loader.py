"""Configuration file loader for PowderLine.

Loads the simulation defaults (``simulation_defaults``) from ``.powderline_config.yaml``; the
TOPAS section is read by ``gateways.topas.runner``. Nothing else lives in the file since the
Materials Project tool left PowderLine (P-36, 0.2.0).
"""

from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from ._status import CHECK, WARN


class ConfigLoader:
    """Load and manage PowderLine configuration."""
    
    DEFAULT_CONFIG_PATHS = [
        ".powderline_config.yaml",  # Current directory
        "~/.powderline_config.yaml",  # Home directory
    ]
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize config loader.
        
        Args:
            config_path: Optional explicit path to config file.
                        If None, searches default locations.
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._load_config()
    
    def _find_config_file(self) -> Optional[Path]:
        """Search for config file in default locations."""
        if self.config_path:
            path = Path(self.config_path).expanduser()
            if path.exists():
                return path
            raise FileNotFoundError(f"Config file not found: {path}")
        
        # Search default locations
        for path_str in self.DEFAULT_CONFIG_PATHS:
            path = Path(path_str).expanduser()
            if path.exists():
                return path
        
        return None
    
    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        config_file = self._find_config_file()
        
        if config_file is None:
            print(f"{WARN}  No config file found. Using defaults.")
            print("   See .powderline_config.yaml.example for the template")
            self.config = self._get_defaults()
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                loaded = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"{config_file}: not valid YAML ({e})") from e
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{config_file}: the config must be a mapping, got {type(loaded).__name__}")
        self.config = loaded
        print(f"{CHECK} Loaded config from: {config_file}")
    
    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration values (GSAS-II conventions/units)."""
        return {
            'simulation_defaults': {
                'instrument_defaults': {
                    'wavelength': 0.4133,      # Angstroms (30 keV)
                    'polarization': 0.99,      # GSAS-II 'Polariz.'
                    'zero_shift': 0.0,         # centidegrees 2theta ('Zero')
                    'axial_divergence': 0.002, # GSAS-II 'SH/L': its own floor (A91; P-05)
                    'broadening': {            # TCH pseudo-Voigt (GSAS-II U..Z)
                        'U': 1.0,
                        'V': -0.5,
                        'W': 0.1,
                        'X': 0.0,
                        'Y': 0.0,
                        'Z': 0.0
                    },
                },
                'phase_defaults': {
                    'scale': 1.0,
                    'Uiso': 0.01,       # Angstrom^2 (fallback for missing values)
                    'occupancy': 1.0,   # fallback for missing values
                    'size_broadening': {
                        'model': 'isotropic',
                        'isotropic_size': 10.0,  # microns
                        'LG_eta': 1.0,
                    },
                    'strain_broadening': {
                        'model': 'isotropic',
                        'isotropic_strain': 0.0,  # delta-d/d x 10^-6
                        'LG_eta': 1.0,
                    },
                },
                'data_range': {
                    'min_2theta': 1.0,
                    'max_2theta': 80.0,
                    'step': 0.05
                },
                'background': {
                    'chebyshev_coefficients': [10.0, 0.0, 0.0]
                }
            }
        }
    
    def get_simulation_defaults(self) -> Dict[str, Any]:
        """Get default simulation parameters."""
        return self.config.get('simulation_defaults', self._get_defaults()['simulation_defaults'])
